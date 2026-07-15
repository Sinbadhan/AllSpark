"""Web API regression — fan out across ~90 endpoints in zh and en.

Coverage (mapped to PRD §三 modules):
  M1  Survival assessment   /api/status
  M2  Mission planner        /api/tasks, /api/tasks/{id}/{action}
  M3  Knowledge engine       /api/knowledge/*
  M4  Personality            /api/system/personality
  M5  Governance             /api/governance/*
  M6  Spark network          /api/network/*
  M7  Resource self-mgmt     /api/resources, /api/power/*
  M8  Multilingual           /api/system/language, /api/system/about
  M9  Web layer              /, /system, /executions, /config, /repository
  M10 Goals & missions       /api/goals/*, /api/milestones/*
  M11 Reset                  /api/reset/{level}
  M12 Daily briefing         /api/briefing*
  M13 Timeline               /api/timeline*
  M14 Weather                /api/weather*
  M15 Psychology             /api/psych*
  M16 Diary                  /api/diary*
  +   GPS / environment      /api/gps*, /api/environment
  +   SKF / verify           /api/skf/*, /api/verify/*
  +   Vision / sensors       /api/vision/*, /api/sensor/*
  +   Data preservation      /api/preserve/*
  +   Modules                /api/modules*
  +   Trade                  /api/trade/*
  +   LLM / chat             /api/llm/*, /api/chat*

NOT covered here (live-resource probes, see README §下一轮):
  - LLM real inference (requires llama-cpp-python + downloaded GGUF)
  - Voice STT/TTS  (requires whisper + audio device)
  - Vision real inference (requires multimodal LLM)
  - Spark network handshake across two real processes
  - Docker elastic deploy
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import quote

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


def _run_lang(c: httpx.Client, recorder: Recorder, lang: str, *, fresh_init: bool) -> None:
    """Drive every endpoint once for a given language."""
    H = lambda *a, **kw: http_probe(c, *a, recorder=recorder, lang=lang, **kw)  # noqa: E731

    # ------------ Init & language ------------
    H("GET", "/api/init/status")
    H("GET", "/api/init/hardware")
    H("GET", "/api/init/models")
    if fresh_init:
        from tests.assessment_helpers import valid_initial_assessment

        H(
            "POST",
            "/api/init/complete",
            json={"language": lang, "survivor_name": "TestRunner", "assessment": valid_initial_assessment()},
        )
    H("POST", "/api/system/language", json={"language": lang})

    # ------------ Survival assessment & resources (M1, M7) ------------
    H("GET", "/api/status")
    H("GET", "/api/resources")
    H("POST", "/api/resources", json={"type": "water", "amount": 10, "daily_consumption": 3, "daily_intake": 0})
    H("GET", "/api/resources")

    # ------------ Knowledge (M3) ------------
    H("GET", "/api/knowledge/categories")
    H("GET", f"/api/knowledge/search?q={quote('water')}")
    H("GET", f"/api/knowledge/search?q={quote('水')}")
    H("GET", "/api/knowledge/category/survival")

    # ------------ Chat / LLM / experience ------------
    H("POST", "/api/chat", json={"message": "hello"})
    H("GET", "/api/llm/status")
    H("GET", "/api/experience")
    H("POST", "/api/experience", json={"event": "drank from creek", "outcome": "success", "lesson": "boil first"})
    H("GET", "/api/experience/patterns")

    # ------------ Tasks & modules (M2, +modules) ------------
    H("GET", "/api/tasks")
    H("GET", "/api/modules")

    # ------------ Goals (M10) ------------
    H("POST", "/api/goals/add", json={"title": f"goal-{lang}", "priority": "high", "category": "survival"})
    H("GET", "/api/goals")
    # Re-read the goal list to grab an id for the detail probe.
    try:
        goals = c.get("/api/goals").json()
        if isinstance(goals, dict) and goals.get("goals"):
            gid = goals["goals"][0].get("id")
            if gid:
                H("GET", f"/api/goals/{gid}")
    except Exception:
        pass

    # ------------ Briefing & timeline & diary (M12, M13, M16) ------------
    H("GET", "/api/briefing")
    H("GET", "/api/briefing/short")
    H("GET", "/api/timeline")
    H("GET", "/api/timeline/recent")
    H("GET", "/api/diary")
    H("POST", "/api/diary/add", json={"content": f"diary {lang}", "mood": "neutral"})
    H("GET", "/api/diary/review")

    # ------------ GPS / weather / environment / map ------------
    H("GET", "/api/gps")
    H("POST", "/api/gps/set", json={"lat": 31.23, "lng": 121.47, "label": "Test City"})
    H("GET", "/api/gps/nearby")
    H("GET", "/api/weather")
    H("POST", "/api/weather/pressure", json={"hpa": 1012})
    H("GET", "/api/environment")
    H("GET", "/api/map/poi")
    H("POST", "/api/map/poi", json={"name": "TestPOI", "lat": 31.23, "lng": 121.47, "kind": "shelter"})

    # ------------ Psychology (M15) ------------
    H("GET", "/api/psych")
    H("GET", "/api/psych/questions")
    H("GET", "/api/reset/logs")

    # ------------ System: personality, mode, modules (M4, +modules) ------------
    H("GET", "/api/system/about")
    H("POST", "/api/system/personality", json={"mode": "stable"})
    H("POST", "/api/system/operating-mode", json={"mode": "standard"})

    # ------------ Network / vision / hardware (M6, +vision, +hardware) ------------
    # SHA-60: these optional services are NOT loaded in the unit-test/CI env
    # (no peer discovery hardware, no multimodal model). A 503 here is expected
    # graceful degradation, not a regression — mark it allowlisted so the
    # combined report separates it from a real 5xx failure.
    H("GET", "/api/network/status", expect_ok=False,
      expect_degraded=True, allowlist_reason="spark_network needs network hardware")
    H("GET", "/api/vision/status", expect_ok=False,
      expect_degraded=True, allowlist_reason="vision_engine needs multimodal model")
    H("GET", "/api/power/status")
    H("GET", "/api/power/runtime")
    H("GET", "/api/power/history")
    H("POST", "/api/power/manual?energy_wh=50&charging=false")
    H("GET", "/api/sensor/status")
    H("GET", "/api/sensor/snapshot")
    H("GET", "/api/preserve/status")

    # ------------ SKF / verify ------------
    H("GET", "/api/skf/info?path=missing.skf", expect_ok=False)
    H("POST", "/api/skf/export?path=test.skf")
    H("GET", "/api/verify/stats")
    H("POST", "/api/verify/batch?mode=unverified")

    # ------------ Governance / trade (M5) ------------
    H("GET", "/api/governance/status")
    H("GET", "/api/governance/members")
    H("POST", "/api/governance/member/add",
      json={"name": "Alice", "role": "expert", "domains": ["medical"]})
    H("GET", "/api/governance/assess")
    H("GET", "/api/governance/recommend")
    H("GET", "/api/trade/status")
    H("GET", "/api/trade/list")
    # Body-shape contract guards (regression: B-4)
    H("POST", "/api/governance/member/add", json={}, expect_ok=False, label="gov-addmember-empty")
    H("POST", "/api/trade/propose", json={}, expect_ok=False, label="trade-propose-empty")

    # ------------ HTML pages (M9) ------------
    for path in ("/", "/system", "/executions", "/config", "/repository"):
        rec = CallRecord(kind="http", label=f"GET {path}", lang=lang,
                         request={"method": "GET", "path": path})
        try:
            r = c.get(path, timeout=10)
            rec.response["status"] = r.status_code
            rec.response["html_len"] = len(r.text)
        except Exception as e:
            rec.flags.append("transport_error")
            rec.response["error"] = str(e)[:200]
        recorder.add(rec)


def _run_negative_paths(c: httpx.Client, recorder: Recorder) -> None:
    """Exercise contract-violation paths once (language-independent)."""
    H = lambda *a, **kw: http_probe(c, *a, recorder=recorder, lang=None, **kw)  # noqa: E731

    # Boundary: invalid params should NOT 5xx and should NOT silently 200.
    H("GET", "/api/knowledge/search?q=", expect_ok=False, label="empty-q")
    H("GET", "/api/knowledge/category/__none__", expect_ok=False, label="bad-category")
    H("GET", "/api/goals/__none__", expect_ok=False, label="bad-goal-id")
    H("POST", "/api/system/personality", json={"mode": "evil"}, expect_ok=False, label="bad-personality")
    H("POST", "/api/system/operating-mode", json={"mode": "ultra"}, expect_ok=False, label="bad-op-mode")
    H("POST", "/api/system/language", json={"language": "klingon"}, expect_ok=False, label="bad-lang")
    H("POST", "/api/modules/__none__/enable", expect_ok=False, label="enable-missing-module")
    H("POST", "/api/reset/9", json={"confirm": True}, expect_ok=False, label="bad-reset-level")
    # Wrong-shape body to /api/experience — historical 500 trap.
    H("POST", "/api/experience", json={"category": "x", "content": "y"}, expect_ok=False, label="bad-exp-shape")
    # Path traversal on SKF.
    H("POST", f"/api/skf/export?path={quote('../../etc/passwd')}", expect_ok=False, label="skf-traversal")
    H("POST", f"/api/skf/import?path={quote('../../../etc/passwd')}", expect_ok=False, label="skf-import-traversal")


def main() -> int:
    db = REPORTS_DIR / "_web_api_session.db"
    jsonl = REPORTS_DIR / "web_api.jsonl"

    if db.exists():
        db.unlink()

    recorder = Recorder(jsonl)
    try:
        with web_server(db) as base:
            with httpx.Client(base_url=base) as c:
                _run_lang(c, recorder, "zh", fresh_init=True)
                _run_lang(c, recorder, "en", fresh_init=False)
                _run_negative_paths(c, recorder)
    finally:
        recorder.close()

    summary = recorder.summary()
    md = render_summary(recorder.records)
    (REPORTS_DIR / "web_api.md").write_text(
        f"# Web API regression — {len(recorder.records)} probes\n\n"
        f"Summary: `{summary}`\n\n{md}\n"
    )
    print(f"\n{summary}")
    print(f"\nresults: {jsonl}")
    print(f"summary: {REPORTS_DIR / 'web_api.md'}")
    # SHA-60: blocking flags (transport_error / non-allowlist 5xx / 4xx / etc.)
    # must fail the suite so run_all cannot false-green.
    blocking = blocking_records(recorder.records)
    if blocking:
        print(f"\n!! {len(blocking)} blocking record(s) - suite FAILS")
        for r in blocking:
            print(f"   {r.label}: {r.flags}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
