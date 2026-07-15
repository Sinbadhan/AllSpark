"""SHA-260: non-clinical, private, offline crisis-support boundary."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from allspark.adapters.web_ui import create_app
from allspark.commands.ai import LLMCommand
from allspark.container import ServiceContainer
from allspark.core.database import Database
from allspark.core.i18n import get_language, set_language
from allspark.infrastructure.hardware import FeatureFlags
from allspark.infrastructure.module_loader import ModuleRegistry
from allspark.services.psychology import PsychologyTracker, SelfHarmSupport
from allspark.services.rule_engine import RuleEngine
from allspark.services.voice import VoiceManager


@pytest.fixture(autouse=True)
def restore_language():
    original = get_language()
    yield
    set_language(original, persist=False)


@pytest.mark.parametrize(
    "text",
    [
        "我没有自杀想法",
        "我不会自杀",
        "文章讨论了自杀预防",
        "文章里写着我想自杀",
        "He said I want to kill myself",
        "他说“我想自杀”",
        'The article says "I want to kill myself".',
        "I am not suicidal",
        "I don't want to kill myself",
        "suicide prevention training",
        "我不想活了，但是这是歌词",
        "这是歌词：我不想活了",
        "This is a lyric: I want to kill myself",
    ],
)
def test_negation_and_quoted_context_do_not_trigger(text: str) -> None:
    support = SelfHarmSupport(resources={})
    assert support.process(text) is None
    assert support.status()["state"] == "idle"


@pytest.mark.parametrize(
    ("language", "text"),
    [
        ("zh", "我想自杀"),
        ("zh", "我有自杀想法"),
        ("en", "I want to kill myself"),
        ("en", "I’m having suicidal thoughts"),
    ],
)
def test_direct_signal_asks_plain_safety_question(language: str, text: str) -> None:
    set_language(language, persist=False)
    result = SelfHarmSupport(resources={}).process(text)
    assert result is not None
    assert result["status"] == "needs_direct_confirmation"
    assert result["clinical_assessment"] is False
    assert result["notification_status"] == "not_sent"
    assert result["recording_status"] == "not_recorded"
    assert "?" in result["message"] or "？" in result["message"]


@pytest.mark.parametrize(
    "text",
    [
        "我没有自杀想法，但是现在我想死。",
        "I am not suicidal, but I want to die now.",
        "文章让我很难受，但是我想自杀",
    ],
)
def test_later_first_person_disclosure_is_not_hidden_by_context(text: str) -> None:
    result = SelfHarmSupport(resources={}).process(text)
    assert result is not None
    assert result["status"] == "needs_direct_confirmation"


@pytest.mark.parametrize(
    "text",
    [
        "The movie made me realize I want to kill myself",
        "这篇文章让我意识到我想自杀",
        "The article is about suicide and I want to kill myself",
        "新闻让我很难受，我想自杀",
        "He said I want to kill myself, but I do too",
        "文章里写着“我想自杀”，但我现在也想自杀",
        "The article says I want to kill myself but I actually do",
        "她说要自杀，可我现在也想死",
        "This is a lyric, but I want to kill myself",
        "这是歌词：我不想活了，但是我现在也想自杀",
    ],
)
def test_broad_context_words_do_not_hide_first_person_disclosure(text: str) -> None:
    result = SelfHarmSupport(resources={}).process(text)
    assert result is not None
    assert result["status"] == "needs_direct_confirmation"


def test_repetition_does_not_escalate_or_count_keywords() -> None:
    support = SelfHarmSupport(resources={})
    first = support.process("I want to kill myself")
    repeated = support.process("I want to kill myself")
    assert first is not None and repeated is not None
    assert first["status"] == repeated["status"] == "needs_direct_confirmation"
    assert not ({"level", "triggers", "notify_authority", "recorded"} & repeated.keys())


@pytest.mark.parametrize(
    "text",
    ["我现在就要自杀", "I am about to kill myself right now"],
)
def test_immediate_danger_skips_delay_and_prioritizes_actions(text: str) -> None:
    result = SelfHarmSupport(resources={}).process(text)
    assert result is not None
    assert result["status"] == "immediate_danger_reported"
    assert len(result["actions"]) >= 4
    assert result["notification_status"] == "not_sent"
    assert result["recording_status"] == "not_recorded"


def test_confirmation_flow_handles_yes_no_and_unclear() -> None:
    yes_support = SelfHarmSupport(resources={})
    yes_support.process("我想伤害自己", conversation_id="zh-session")
    yes_result = yes_support.process(
        "是",
        conversation_id="zh-session",
    )
    assert yes_result is not None
    assert yes_result["status"] == "immediate_danger_reported"

    no_support = SelfHarmSupport(resources={})
    no_support.process("I want to hurt myself", conversation_id="en-session")
    no_result = no_support.process(
        "not now",
        conversation_id="en-session",
    )
    assert no_result is not None
    assert no_result["status"] == "no_immediate_danger_reported"

    unclear_support = SelfHarmSupport(resources={})
    unclear_support.process("我想自杀", conversation_id="unclear-session")
    unclear_result = unclear_support.process(
        "我不知道",
        conversation_id="unclear-session",
    )
    assert unclear_result is not None
    assert unclear_result["status"] == "confirmation_unclear"


def test_confirmation_state_is_isolated_by_conversation() -> None:
    support = SelfHarmSupport(resources={})
    support.process("我想自杀", conversation_id="session-a")

    assert support.process("是", conversation_id="session-b") is None
    assert support.status(conversation_id="session-a")["state"] == (
        "awaiting_direct_confirmation"
    )
    assert support.status(conversation_id="session-b")["state"] == "idle"


def test_invalid_or_missing_conversation_id_cannot_create_shared_pending_state() -> None:
    support = SelfHarmSupport(resources={})
    support.process("我想自杀", conversation_id="../../shared")
    assert support.process("是", conversation_id="../../shared") is None
    support.process("我想自杀")
    assert support.process("是") is None
    assert support.process("我想自杀", conversation_id=123) is not None
    assert support.process("是", conversation_id=123) is None


def test_pending_confirmation_expires(monkeypatch) -> None:
    now = 1000.0
    monkeypatch.setattr("allspark.services.psychology.time.monotonic", lambda: now)
    support = SelfHarmSupport(resources={})
    support.process("我想自杀", conversation_id="expiring-session")

    now = 1601.0
    assert support.process("是", conversation_id="expiring-session") is None
    assert support.status(conversation_id="expiring-session")["state"] == "idle"


def test_unconfigured_resources_use_global_generic_fallback_without_988() -> None:
    result = SelfHarmSupport(resources={}).process("I am about to kill myself")
    assert result is not None
    rendered = " ".join(result["actions"])
    assert "988" not in rendered
    assert "local" in rendered.lower() or "当地" in rendered


def test_local_resources_load_offline_from_config(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        """[crisis_support]
region = "Test region"
emergency_service = "Local emergency 112"
crisis_line = "Community crisis desk"
trusted_contact = "Alex on radio channel 3"
""",
        encoding="utf-8",
    )
    result = SelfHarmSupport(config_path=config).process("I will kill myself right now")
    assert result is not None
    rendered = " ".join(result["actions"])
    assert "Local emergency 112" in rendered
    assert "Community crisis desk" in rendered
    assert "Alex on radio channel 3" in rendered


def test_sensitive_exchange_is_not_written_to_timeline() -> None:
    db = MagicMock()
    tracker = PsychologyTracker(
        db,
        crisis_support=SelfHarmSupport(resources={}),
    )
    result = tracker.detect_self_harm_risk("我现在就要自杀")
    assert result is not None
    db.save_timeline_event.assert_not_called()


def test_rule_engine_intercepts_before_intent_or_llm() -> None:
    set_language("en", persist=False)
    container = ServiceContainer(db=MagicMock())
    container.register("resource_manager", MagicMock())
    personality = MagicMock()
    container.register("personality", personality)
    container.register("crisis_support", SelfHarmSupport(resources={}))
    llm = MagicMock()
    container.register("llm", llm)

    response = RuleEngine(container).process_input(
        "I want to kill myself",
        conversation_id="cli",
    )

    assert "immediate danger" in response.lower()
    personality.classify_intent.assert_not_called()
    llm.survival_chat.assert_not_called()


def test_llm_command_intercepts_before_direct_llm_call() -> None:
    set_language("en", persist=False)
    container = ServiceContainer(db=MagicMock())
    llm = MagicMock(available=True)
    container.register("llm", llm)
    container.register("registry", MagicMock())
    container.register("survival_engine", MagicMock())
    container.register("crisis_support", SelfHarmSupport(resources={}))
    command = LLMCommand(container)
    command.console = MagicMock()

    command.execute(["chat", "I", "want", "to", "kill", "myself"])

    llm.survival_chat.assert_not_called()
    command.console.print.assert_called_once()


def test_voice_open_conversation_intercepts_before_llm() -> None:
    set_language("en", persist=False)
    llm = MagicMock(available=True)
    voice = VoiceManager(
        llm_engine=llm,
        crisis_support=SelfHarmSupport(resources={}),
    )

    response = voice.handle_voice_input("hey spark I want to kill myself")

    assert "immediate danger" in response.lower()
    llm.survival_chat.assert_not_called()


def _web_client(db_path: Path) -> TestClient:
    db = Database(db_path)
    try:
        db.mark_initialized()
        ModuleRegistry(
            FeatureFlags(llm=True, web_ui=True, self_learning=True)
        ).save_to_db(db)
    finally:
        db.close()
    return TestClient(create_app(str(db_path)))


def test_chat_routes_preserve_session_and_block_streaming_llm(tmp_path: Path) -> None:
    client = _web_client(tmp_path / "web.db")
    first = client.post(
        "/api/chat",
        json={
            "message": "I want to kill myself",
            "conversation_id": "web-a",
            "language": "en",
        },
    )
    assert first.status_code == 200
    assert "immediate danger" in first.json()["response"].lower()

    confirmed = client.post(
        "/api/chat",
        json={"message": "yes", "conversation_id": "web-a"},
    )
    assert "reported immediate danger" in confirmed.json()["response"].lower()

    llm = MagicMock(available=True)
    llm.survival_chat_stream = MagicMock(return_value=iter(["unsafe"]))
    getattr(client.app, "state").container.register("llm", llm)
    streamed = client.post(
        "/api/chat/stream",
        json={"message": "I want to kill myself", "conversation_id": "web-b"},
    )
    assert streamed.status_code == 200
    assert streamed.json()["safety"] is True
    llm.survival_chat_stream.assert_not_called()


@pytest.mark.parametrize("invalid_id", [123, True])
@pytest.mark.parametrize("route", ["/api/chat", "/api/chat/stream"])
def test_chat_routes_treat_non_string_conversation_id_as_anonymous(
    tmp_path: Path,
    route: str,
    invalid_id: object,
) -> None:
    client = _web_client(tmp_path / f"invalid-{route.rsplit('/', 1)[-1]}-{invalid_id}.db")
    response = client.post(
        route,
        json={
            "message": "I want to kill myself",
            "conversation_id": invalid_id,
            "language": "en",
        },
    )
    assert response.status_code == 200
    assert "immediate danger" in response.json()["response"].lower()
