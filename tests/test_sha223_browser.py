"""SHA-223: real-browser evidence gating for environment guidance."""

from __future__ import annotations

from pathlib import Path

from allspark.adapters.web_ui import create_app
from allspark.core.database import Database
from tests.test_sha196_browser import _Chrome, _chrome_binary, _serve


def test_fresh_environment_page_never_presents_actionable_score(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "environment-browser.db"
    database = Database(db_path)
    database.mark_initialized()
    database.close()

    app = create_app(str(db_path))
    with _serve(app) as base_url, _Chrome(
        _chrome_binary(), tmp_path / "chrome-profile"
    ) as browser:
        browser.navigate(f"{base_url}/system")
        browser.wait_for(
            "document.getElementById('env-score')?.textContent.trim().length > 0"
        )
        state = browser.evaluate(
            """(() => ({
              score: document.getElementById('env-score').textContent.trim(),
              completeness: document.getElementById('env-completeness').textContent,
              sources: document.getElementById('env-sources').textContent,
              fullText: document.getElementById('env-result').textContent,
            }))()"""
        )

    assert state["score"] in {"证据不足", "Insufficient evidence"}
    assert state["score"] not in {"0%", "65%"}
    assert "33%" not in state["completeness"]
    assert "0%" in state["completeness"]
    assert all(
        label in state["fullText"]
        for label in ("气候", "地形", "资源")
    ) or all(
        label in state["fullText"]
        for label in ("Climate", "Terrain", "Resources")
    )
    assert "unknown" in state["sources"] or "未知" in state["sources"]
    assert not any(
        phrase in state["fullText"].lower()
        for phrase in (
            "可进行探索",
            "基础生存稳定",
            "can explore",
            "survival stable",
            "即将耗尽",
            "严重不足",
            "食物已耗尽",
            "nearly depleted",
            "critically low",
            "food is depleted",
        )
    )
