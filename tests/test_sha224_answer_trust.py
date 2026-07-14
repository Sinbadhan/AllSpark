"""SHA-224: answer trust must agree with system and resource state."""

from __future__ import annotations

from pathlib import Path

from allspark.core.models import ResourceType
from allspark.services.system_health import assess_system_health
from tests.test_sha196_browser import _Chrome, _chrome_binary, _serve
from tests.test_web_ui_v11 import TempDb, _client


def test_rule_answer_separates_health_resources_and_match() -> None:
    with TempDb() as path:
        client = _client(path)
        client.post("/api/system/language", json={"language": "en"})
        health = client.get("/api/system/health").json()
        response = client.post(
            "/api/chat",
            json={"message": "How to start a fire with a battery?"},
        ).json()["response"]
        direct = client.app.state.container.get("rule_engine").process_input(
            "How to start a fire with a battery?"
        )

        assert health == assess_system_health(client.app.state.container)

    assert health["state"] == "degraded"
    assert "Standard guidance" in response
    assert "Status Normal" not in response
    assert "System health: degraded" in response
    assert "Resource data: unknown" in response
    assert "Answer match: specific" in response
    assert "Battery Fire Starting" in response
    assert "System health: degraded" in direct
    assert "Answer match: specific" in direct


def test_generic_and_missing_matches_are_not_success_styled() -> None:
    with TempDb() as path:
        client = _client(path)
        client.post("/api/system/language", json={"language": "en"})
        generic = client.post(
            "/api/chat", json={"message": "How can I make a fire?"}
        ).json()["response"]
        missing = client.post(
            "/api/chat", json={"message": "How to start a fire with a potato?"}
        ).json()["response"]

    assert "Answer match: general; verify applicability" in generic
    assert "Status Normal" not in generic
    assert "✅" not in generic
    assert "Answer match: no direct match" in missing
    assert "Status Normal" not in missing


def test_bilingual_resource_trust_tracks_real_configuration() -> None:
    with TempDb() as path:
        client = _client(path)
        container = client.app.state.container
        manager = container.get("resource_manager")
        engine = container.get("rule_engine")

        client.post("/api/system/language", json={"language": "zh"})
        unknown = engine.process_input("用电池取火")
        assert "系统健康：降级" in unknown
        assert "资源数据：未知" in unknown
        assert "答案匹配：具体匹配" in unknown

        manager.update_resource(
            ResourceType.POWER, 0.0, consumption=20.0, intake=0.0
        )
        manager.update_resource(
            ResourceType.WATER, 20.0, consumption=2.0, intake=0.0
        )
        manager.update_resource(
            ResourceType.FOOD, 30000.0, consumption=2000.0, intake=0.0
        )
        critical = engine.process_input("用电池取火")
        assert "资源数据：严重不足" in critical

        manager.update_resource(
            ResourceType.POWER, 100.0, consumption=20.0, intake=0.0
        )
        ready = engine.process_input("用电池取火")
        assert "资源数据：已配置" in ready


def test_browser_chat_health_matches_footer(tmp_path: Path) -> None:
    db_path = tmp_path / "answer-trust.db"
    client = _client(str(db_path))
    client.post("/api/system/language", json={"language": "en"})

    with _serve(client.app) as base_url, _Chrome(
        _chrome_binary(), tmp_path / "chrome-profile"
    ) as browser:
        browser.navigate(base_url)
        browser.wait_for(
            "document.getElementById('footer-status').textContent.includes('degraded')"
        )
        browser.evaluate(
            "document.getElementById('chat-input').value = "
            "'How to start a fire with a battery?'; sendChat()"
        )
        browser.wait_for(
            "document.querySelector('#chat-messages .chat-msg.system:last-child "
            ".bubble')?.textContent.includes('Answer match: specific')"
        )
        state = browser.evaluate(
            """({
              footer: document.getElementById('footer-status').textContent,
              response: document.querySelector(
                '#chat-messages .chat-msg.system:last-child .bubble'
              ).textContent,
            })"""
        )

    assert "degraded" in state["footer"]
    assert "System health: degraded" in state["response"]
    assert "Resource data: unknown" in state["response"]
    assert "Status Normal" not in state["response"]
