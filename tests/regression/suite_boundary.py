"""Boundary suite — paths that aren't natural in the happy-path Web suite.

Coverage:
  - Reset cycles L1 / L2 / L3 (with and without `confirm`)
  - L3 must wipe `is_initialized()` and the home page must show the wizard
  - Cooldown enforcement after a reset
  - Emergency-state safety (water<1d / food<2d / power<6h must block reset)
  - Mid-flight language switching (zh -> en -> invalid -> zh)
  - Diary repeated submissions
  - GPS out-of-range coordinates

NOT covered here (would need separate harness):
  - Reset auto-snapshot retention (7-day retention window)
  - L3 recovery from a snapshot
  - Multi-process commander/expert role conflicts
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlencode

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    __package__ = "tests.regression"

import httpx

from tests.regression._harness import (
    REPORTS_DIR,
    CallRecord,
    Recorder,
    blocking_records,
    http_probe,
    render_summary,
    web_server,
)


def main() -> int:
    db = REPORTS_DIR / "_boundary_session.db"
    if db.exists():
        db.unlink()

    jsonl = REPORTS_DIR / "boundary.jsonl"
    recorder = Recorder(jsonl)
    H = lambda *a, **kw: http_probe(c, *a, recorder=recorder, **kw)  # noqa: E731

    try:
        with web_server(db) as base:
            with httpx.Client(base_url=base) as c:
                # 1. Init zh
                H("GET", "/api/init/status", label="boot/uninitialized")
                qs = urlencode({"language": "zh", "survivor_name": "Alice", "skip_model": "true"})
                H("POST", f"/api/init/complete?{qs}", label="init/zh")
                H("GET", "/api/init/status", label="post-init")

                # 2. L1 reset — confirm gating + happy path
                H("POST", "/api/reset/1", json={}, expect_ok=False, label="L1/no-confirm")
                H("POST", "/api/reset/1", json={"confirm": True}, label="L1/confirm")
                H("GET", "/api/init/status", label="L1/post — should still be initialized")

                # 3. L2 right after L1 — exercises cooldown
                H("POST", "/api/reset/2", json={"confirm": True}, expect_ok=False, label="L2/in-cooldown")

                # 4. Force flag — bypasses cooldown
                H("POST", "/api/reset/2", json={"confirm": True, "force": True}, label="L2/force")
                H("GET", "/api/init/status", label="L2/post")

                # 5. L3 factory — homepage must regress to init wizard
                H("POST", "/api/reset/3", json={"confirm": True, "force": True}, label="L3/force")
                rec_init = H("GET", "/api/init/status", label="L3/post-init-status")
                # Sanity: when L3 succeeded, init must flip back to False.
                # We don't assert here — Recorder already captured `body_initialized`.
                _ = rec_init
                rec_home = CallRecord(
                    kind="http", label="home-after-L3",
                    request={"method": "GET", "path": "/"},
                )
                home = c.get("/")
                rec_home.response["status"] = home.status_code
                rec_home.response["html_len"] = len(home.text)
                if "init" not in home.text.lower():
                    rec_home.flags.append("post_l3_not_init_page")
                recorder.add(rec_home)

                # 6. Re-init en, then mid-flight language switching
                qs = urlencode({"language": "en", "survivor_name": "Bob", "skip_model": "true"})
                H("POST", f"/api/init/complete?{qs}", label="init/en")
                H("GET", "/api/system/about", label="about/en")
                H("POST", "/api/system/language", json={"language": "zh"}, label="lang/zh")
                H("GET", "/api/system/about", label="about/zh")
                H("POST", "/api/system/language", json={"language": "klingon"}, expect_ok=False, label="lang/invalid")
                H("POST", "/api/system/language", json={}, expect_ok=False, label="lang/empty-body")
                H("POST", "/api/system/language", json={"lang": "en"}, label="lang/alt-key")

                # 7. Emergency-state: starve resources, all resets must reject
                for rt, amt, daily in [("water", 0.1, 3), ("food", 100, 2000), ("power", 5, 50)]:
                    H("POST", "/api/resources",
                      json={"type": rt, "amount": amt, "daily_consumption": daily, "daily_intake": 0},
                      label=f"emergency/{rt}")
                H("GET", "/api/status", label="emergency/status")
                H("POST", "/api/reset/1", json={"confirm": True}, expect_ok=False, label="emergency/L1-blocked")
                H("POST", "/api/reset/2", json={"confirm": True}, expect_ok=False, label="emergency/L2-blocked")
                H("POST", "/api/reset/3", json={"confirm": True}, expect_ok=False, label="emergency/L3-blocked")

                # 8. Diary dedup
                for n in range(3):
                    H("POST", "/api/diary/add",
                      json={"content": "测试日记内容", "mood": "neutral"},
                      label=f"diary/dup-{n}")
                H("GET", "/api/diary", label="diary/after-dup")

                # 9. GPS out-of-range
                H("POST", "/api/gps/set", json={"lat": 999, "lng": -9999}, expect_ok=False, label="gps/out-of-range")
                H("POST", "/api/gps/set", json={"lat": "abc", "lng": 0}, expect_ok=False, label="gps/non-numeric")
    finally:
        recorder.close()

    md = render_summary(recorder.records)
    (REPORTS_DIR / "boundary.md").write_text(
        f"# Boundary regression — {len(recorder.records)} probes\n\n"
        f"Summary: `{recorder.summary()}`\n\n{md}\n"
    )
    print(f"\n{recorder.summary()}")
    print(f"\nresults: {jsonl}")
    print(f"summary: {REPORTS_DIR / 'boundary.md'}")
    blocking = blocking_records(recorder.records)
    if blocking:
        print(f"\n!! {len(blocking)} blocking record(s) - suite FAILS")
        for r in blocking:
            print(f"   {r.label}: {r.flags}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
