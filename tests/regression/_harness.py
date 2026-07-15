"""Shared scaffolding for AllSpark regression suites.

These suites are NOT pytest cases — they're scripted explorations that
record everything to JSONL for review. They're meant to be:

- runnable in isolation (`python -m tests.regression.suite_web_api`)
- runnable as a batch (`python -m tests.regression.run_all`)
- reusable: import this module and write your own probe

Why not pytest? Because the suites surface UX bugs that don't make sense
as pass/fail (e.g. "i18n key leaks across 14 endpoints"). They produce
artifacts that humans triage. Once a bug is fixed, promote the specific
check to a real pytest case in tests/test_*.py.
"""
from __future__ import annotations

import json
import re
import socket
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REGRESSION_DIR = Path(__file__).resolve().parent
REPORTS_DIR = REGRESSION_DIR / "reports"
REPORTS_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Server boot helpers
# ---------------------------------------------------------------------------

class EnvironmentBlocked(RuntimeError):
    """Raised when the current host forbids resources required by a suite."""


def _free_port(start: int = 18800, span: int = 200) -> int:
    """Pick a free TCP port in [start, start+span) for an ephemeral server."""
    permission_error: PermissionError | None = None
    for port in range(start, start + span):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except PermissionError as exc:
                permission_error = exc
            except OSError:
                continue
    if permission_error is not None:
        raise EnvironmentBlocked(
            f"localhost TCP bind unavailable in this environment: {permission_error}"
        ) from permission_error
    raise RuntimeError(f"no free port in [{start}, {start + span})")


@contextmanager
def web_server(db_path: Path, *, log_level: str = "error") -> Iterator[str]:
    """Yield a base URL pointing at an ephemeral allspark Web UI server.

    Caller is responsible for setting up `db_path` (fresh or pre-seeded).
    Server lifetime is bound to the with-block.
    """
    import httpx
    import uvicorn  # noqa: WPS433 — local import to keep module light

    from allspark.adapters.web_ui import create_app

    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    app = create_app(str(db_path))
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level=log_level)
    server = uvicorn.Server(config)
    th = threading.Thread(target=server.run, daemon=True)
    th.start()

    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            httpx.get(f"{base}/api/init/status", timeout=1)
            break
        except Exception:
            time.sleep(0.3)
    else:
        server.should_exit = True
        th.join(timeout=3)
        raise RuntimeError(f"server did not start on {base} within 30s")

    try:
        yield base
    finally:
        server.should_exit = True
        th.join(timeout=3)


# ---------------------------------------------------------------------------
# i18n leak detection
# ---------------------------------------------------------------------------

# A bare dotted-lowercase identifier that smells like an unrendered i18n key.
# Matches `web_xxx.yyy`, `t.something`, etc. Skipped if it looks like a
# knowledge id, a version string, an IP, or a file path.
_LEAK_RE = re.compile(r"\b([a-z][a-z0-9_]+(?:\.[a-z0-9_]+){2,})\b")
_LEAK_ALLOW_PREFIXES = (
    "survival.", "medical.", "agriculture.", "engineering.", "science.",
    "127.0.", "0.0.", "192.168.", "10.0.",
)
_LEAK_ALLOW_SUFFIXES = (".gguf", ".db", ".json", ".yaml", ".html", ".py", ".skf")


def detect_i18n_leaks(text: str) -> list[str]:
    """Return identifier-like strings that smell like unrendered i18n keys.

    Heuristic only. Tune `_LEAK_ALLOW_PREFIXES` / `_LEAK_ALLOW_SUFFIXES`
    when false positives multiply.
    """
    if not isinstance(text, str) or len(text) > 5000:
        return []
    out = []
    for match in _LEAK_RE.findall(text):
        if any(match.startswith(p) for p in _LEAK_ALLOW_PREFIXES):
            continue
        if match.endswith(_LEAK_ALLOW_SUFFIXES):
            continue
        # Version strings like "1.0.0" — already absorbed by the prefix list,
        # but keep this defensive filter for "vN.M.P" forms.
        if re.fullmatch(r"v?\d+(\.\d+)+", match):
            continue
        out.append(match)
    return out


def walk_strings(obj: Any, path: str = "") -> Iterator[tuple[str, str]]:
    """Yield (json-path, str) for every string in a nested structure."""
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk_strings(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_strings(v, f"{path}[{i}]")


# ---------------------------------------------------------------------------
# Recorder — every suite uses this to log calls to JSONL.
# ---------------------------------------------------------------------------

@dataclass
class CallRecord:
    """One probe — typically an HTTP request or a CLI command."""
    kind: str                       # "http" / "cli" / "static" / "db"
    label: str                      # human-readable handle
    lang: str | None = None         # zh / en / None
    request: dict[str, Any] = field(default_factory=dict)
    response: dict[str, Any] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)   # e.g. ["i18n_leak", "5xx", "boundary_pass"]
    note: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class Recorder:
    """Append-only sink for CallRecord. One file per suite run."""

    def __init__(self, path: Path):
        self.path = path
        self._fh = path.open("w", encoding="utf-8")
        self._records: list[CallRecord] = []

    def add(self, rec: CallRecord) -> CallRecord:
        self._records.append(rec)
        self._fh.write(rec.to_json() + "\n")
        self._fh.flush()
        return rec

    def close(self) -> None:
        self._fh.close()

    @property
    def records(self) -> list[CallRecord]:
        return list(self._records)

    def summary(self) -> dict[str, int]:
        out: dict[str, int] = {}
        out["total"] = len(self._records)
        for r in self._records:
            for f in r.flags:
                out[f] = out.get(f, 0) + 1
        return out



# ---------------------------------------------------------------------------
# SHA-60: blocking-flag detection. A suite whose records carry any blocking
# flag must return non-zero so run_all fails (no false green). Flags marked
# here indicate a real regression; ``degraded_allowlisted`` (expected graceful
# degradation) and informational flags (``boundary_pass``, ``environment_blocked``)
# are NOT blocking.
# ---------------------------------------------------------------------------
BLOCKING_FLAGS = frozenset({
    "transport_error", "5xx", "4xx_unexpected", "ok_unexpected",
    "i18n_leak", "json_error",
})


def blocking_records(records: list[CallRecord]) -> list[CallRecord]:
    """Return records carrying any blocking flag (SHA-60)."""
    return [r for r in records if any(f in BLOCKING_FLAGS for f in r.flags)]

# ---------------------------------------------------------------------------
# HTTP probe — wraps httpx with auto-recording + flag extraction.
# ---------------------------------------------------------------------------

def http_probe(
    client,
    method: str,
    path: str,
    *,
    recorder: Recorder,
    lang: str | None = None,
    expect_ok: bool = True,
    expect_degraded: bool = False,
    allowlist_reason: str | None = None,
    label: str | None = None,
    **kwargs,
) -> CallRecord:
    """Run an HTTP request, record everything, flag anomalies.

    Flags emitted:
      - "5xx": response status >= 500
      - "4xx_unexpected": 4xx but caller declared expect_ok=True
      - "ok_unexpected": 2xx but caller declared expect_ok=False
      - "i18n_leak": at least one leaked key in response body
      - "json_error": response body claimed json but failed to parse
      - "transport_error": httpx raised

    SHA-60: ``expect_degraded=True`` + ``allowlist_reason`` marks a probe whose
    5xx is an EXPECTED graceful-degradation (the backing optional service is
    not loaded in this environment, e.g. spark_network/vision without the
    matching hardware). Such probes are tagged ``degraded_allowlisted`` instead
    of a bare ``5xx`` so the combined report can separate real failures from
    known-unsupported optional services at a glance.
    """
    rec = CallRecord(
        kind="http",
        label=label or f"{method} {path}",
        lang=lang,
        request={"method": method, "path": path, "kwargs_keys": list(kwargs)},
        response={},
    )
    if allowlist_reason:
        rec.response["allowlist_reason"] = allowlist_reason
    try:
        r = client.request(method, path, timeout=15, **kwargs)
    except Exception as e:
        rec.flags.append("transport_error")
        rec.response = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
        return recorder.add(rec)

    rec.response["status"] = r.status_code
    if r.status_code >= 500:
        if expect_degraded and allowlist_reason:
            rec.flags.append("degraded_allowlisted")
        else:
            rec.flags.append("5xx")
    if expect_ok and 400 <= r.status_code < 500:
        rec.flags.append("4xx_unexpected")
    if not expect_ok and 200 <= r.status_code < 300:
        rec.flags.append("ok_unexpected")

    try:
        body = r.json()
        rec.response["body_kind"] = type(body).__name__
        if isinstance(body, dict):
            rec.response["body_keys"] = list(body.keys())[:30]
            for k in ("error", "detail", "message", "status"):
                if k in body and isinstance(body[k], (str, list)):
                    rec.response[f"body_{k}"] = str(body[k])[:300]
        elif isinstance(body, list):
            rec.response["body_kind"] = f"list[{len(body)}]"

        leaks = []
        for ppath, s in walk_strings(body):
            for leak in detect_i18n_leaks(s):
                leaks.append({"at": ppath, "leak": leak, "snippet": s[:120]})
        if leaks:
            rec.flags.append("i18n_leak")
            rec.response["i18n_leaks"] = leaks[:5]
    except Exception:
        rec.flags.append("json_error")
        rec.response["body_text"] = r.text[:300]

    return recorder.add(rec)


# ---------------------------------------------------------------------------
# DB seeding — many suites need an "already initialized" DB to skip the wizard.
# ---------------------------------------------------------------------------

def initialization_payload(
    client,
    *,
    language: str = "zh",
    survivor_name: str = "TestRunner",
) -> dict:
    """Build the current preview-bound initialization contract."""
    from tests.assessment_helpers import valid_initial_assessment

    assessment = valid_initial_assessment(confirmed=False)
    preview = client.post(
        "/api/init/assessment/preview",
        json={"language": language, "assessment": assessment},
        timeout=15,
    )
    if preview.status_code != 200:
        raise RuntimeError(
            f"assessment preview failed: {preview.status_code} {preview.text[:200]}"
        )
    body = preview.json()
    assessment["as_of"] = body["summary"]["as_of"]
    assessment["confirmed"] = True
    return {
        "language": language,
        "survivor_name": survivor_name,
        "assessment": assessment,
        "plan_id": body["plan"]["id"],
        "primary_action_id": body["plan"]["primary_candidate_ids"][0],
    }


def seed_initialized_db(db_path: Path, *, language: str = "zh", survivor_name: str = "TestRunner") -> None:
    """Stand up a fresh DB that has gone through the init wizard.

    Hits POST /api/init/complete with skip_model=true so the suite can
    proceed to feature-level probes without LLM weights on disk.
    """
    import httpx

    if db_path.exists():
        db_path.unlink()
    with web_server(db_path) as base:
        with httpx.Client(base_url=base) as c:
            # Hardware detection populates the model registry.
            c.get("/api/init/hardware", timeout=10)
            r = c.post(
                "/api/init/complete",
                json=initialization_payload(
                    c, language=language, survivor_name=survivor_name
                ),
                timeout=15,
            )
            if r.status_code != 200:
                raise RuntimeError(f"init failed: {r.status_code} {r.text[:200]}")


# ---------------------------------------------------------------------------
# Reporting — turn recorder JSONL into a triage-friendly markdown summary.
# ---------------------------------------------------------------------------

def render_summary(records: list[CallRecord]) -> str:
    """Render an at-a-glance markdown table grouped by flag."""
    by_flag: dict[str, list[CallRecord]] = {}
    for r in records:
        for f in r.flags:
            by_flag.setdefault(f, []).append(r)

    lines = [f"**Total probes:** {len(records)}", ""]
    if not by_flag:
        lines.append("_No flagged anomalies._")
        return "\n".join(lines)

    for flag in sorted(by_flag):
        items = by_flag[flag]
        lines.append(f"### `{flag}` × {len(items)}")
        lines.append("")
        for r in items[:30]:
            status = r.response.get("status", "—")
            body_msg = (
                r.response.get("body_message")
                or r.response.get("body_detail")
                or r.response.get("body_error")
                or ""
            )
            body_msg = str(body_msg)[:120]
            leaks = r.response.get("i18n_leaks") or []
            leak_str = (
                f" leaks={[ll['leak'] for ll in leaks[:3]]}" if leaks else ""
            )
            lines.append(
                f"- `[{r.lang or '-'}]` **{r.label}** → `{status}` {body_msg}{leak_str}"
            )
        if len(items) > 30:
            lines.append(f"- … and {len(items) - 30} more")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Subprocess-driven CLI helper
# ---------------------------------------------------------------------------

def cli_drive(db_path: Path, commands: list[str], *, timeout: int = 180) -> tuple[str, str, int]:
    """Run `python -m allspark --db DB`, feed commands via stdin, capture output.

    Returns (stdout, stderr, returncode). Caller decides what to flag.
    """
    import subprocess

    repo_root = Path(__file__).resolve().parents[2]
    inp = "\n".join(commands) + "\n"
    p = subprocess.run(
        [sys.executable, "-m", "allspark", "--db", str(db_path)],
        input=inp,
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return p.stdout, p.stderr, p.returncode
