"""HTML render suite — fetch every Web UI page in zh and en, save snapshots,
flag obvious i18n leaks (zh in en mode, English UI words in zh mode).

Coverage:
  /             index.html       Dashboard
  /system       system.html      System monitor
  /executions   executions.html  Goals/Tasks/Timeline
  /config       config.html      Config editor
  /repository   repository.html  Knowledge / Community / Trade

Snapshots land in `tests/regression/reports/html/{lang}/{name}.html` for
human eyeball review when an automated check is impractical.

NOT covered:
  - init.html (only served when uninitialized; needs a fresh DB run)
  - JavaScript-rendered DOM after fetch (we only see the server-rendered shell)
  - Visual layout / responsive breakpoints (would need headless browser)
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    __package__ = "tests.regression"

import httpx

from tests.regression._harness import (
    REPORTS_DIR,
    CallRecord,
    Recorder,
    render_summary,
    seed_initialized_db,
    web_server,
)

PAGES = [
    ("/", "index"),
    ("/system", "system"),
    ("/executions", "executions"),
    ("/config", "config"),
    ("/repository", "repository"),
]

# Plain-English UI words that should be translated when serving zh.
# Skip JS identifiers / CSS classes by only matching against `<body>` text.
# SHA-60: "GPS" is an intentional cross-language acronym (PRD keeps hardware
# protocol names untranslated), so it is excluded from the leak scan.
_EN_UI_WORDS = re.compile(
    r"\b(Dashboard|Loading|Active|Inactive|Goals|Tasks|Timeline|Diary|Mind|"
    r"Location|Weather|Environment|Briefing|Reset|Snapshot|Backup|Module|"
    r"Modules|Knowledge|Community|Trade|Power|Sensor|Map|Network|Vision)\b"
)


def _visible_body(html: str) -> str:
    """Strip script/style and tags so we can scan visible text only."""
    body = re.search(r"<body[^>]*>(.+?)</body>", html, re.DOTALL)
    if not body:
        return ""
    inner = body.group(1)
    inner = re.sub(r"<script[^>]*>.+?</script>", "", inner, flags=re.DOTALL)
    inner = re.sub(r"<style[^>]*>.+?</style>", "", inner, flags=re.DOTALL)
    # SHA-60: Material Symbols icon ligature names ("dashboard", "bolt", ...)
    # live inside <span class="material-symbols-outlined">NAME</span>. They are
    # NOT user-visible UI strings (the font replaces them with glyphs; offline
    # they are hidden by the .icons-offline fallback). Drop the whole span so
    # its ligature name does not register as an untranslated English word.
    inner = re.sub(r"<span[^>]*class=\"[^\"]*material-symbols-outlined[^\"]*\"[^>]*>[^<]*</span>", " ", inner)
    inner = re.sub(r"<[^>]+>", " ", inner)
    return inner


def main() -> int:
    db = REPORTS_DIR / "_html_session.db"
    if db.exists():
        db.unlink()
    seed_initialized_db(db, language="zh")

    out_dir = REPORTS_DIR / "html"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir()

    jsonl = REPORTS_DIR / "html_render.jsonl"
    recorder = Recorder(jsonl)

    try:
        with web_server(db) as base:
            with httpx.Client(base_url=base) as c:
                for lang in ("zh", "en"):
                    c.post("/api/system/language", json={"language": lang})
                    (out_dir / lang).mkdir(parents=True, exist_ok=True)
                    for path, name in PAGES:
                        rec = CallRecord(
                            kind="http",
                            label=f"GET {path}",
                            lang=lang,
                            request={"method": "GET", "path": path},
                        )
                        try:
                            r = c.get(path, timeout=10)
                            rec.response["status"] = r.status_code
                            rec.response["html_len"] = len(r.text)
                            (out_dir / lang / f"{name}.html").write_text(r.text)
                            visible = _visible_body(r.text)
                            if lang == "en":
                                # Untranslated zh chars in en view (excluding our seeded data).
                                zh = [m for m in re.findall(r"[一-鿿]+", visible)
                                      if m not in {"火种"}]
                                if zh:
                                    rec.flags.append("zh_in_en_visible")
                                    rec.response["zh_samples"] = list(set(zh))[:5]
                            elif lang == "zh":
                                en = sorted(set(_EN_UI_WORDS.findall(visible)))
                                if en:
                                    rec.flags.append("en_in_zh_visible")
                                    rec.response["en_samples"] = en[:10]
                        except Exception as e:
                            rec.flags.append("transport_error")
                            rec.response["error"] = str(e)[:200]
                        recorder.add(rec)
    finally:
        recorder.close()

    md = render_summary(recorder.records)
    (REPORTS_DIR / "html_render.md").write_text(
        f"# HTML render regression — {len(recorder.records)} pages\n\n"
        f"Summary: `{recorder.summary()}`\n\n"
        f"Snapshots: `tests/regression/reports/html/`\n\n{md}\n"
    )
    print(f"\n{recorder.summary()}")
    print(f"\nresults: {jsonl}")
    print(f"snapshots: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
