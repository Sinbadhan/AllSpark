"""SHA-151: init_wizard (init critical path) branch coverage.

The wizard is interactive (console.input-driven); these tests mock the input
stream, hardware detection, and model download to exercise the language/tier/
model/survivor/summary branches that were uncovered. Network download paths
mock urllib.request.urlopen.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from allspark.adapters import init_wizard
from allspark.adapters.init_wizard import (
    _ask_tier_override,
    _choose_other_model,
    _download_model,
    _select_multi,
    _step_assessment_summary,
    _step_hardware_detect,
    _step_initial_assessment,
    _step_language_select,
    _step_model_setup,
    _step_plan_selection,
    _step_summary,
    run_init_wizard,
)
from allspark.core.database import Database
from allspark.infrastructure.hardware import HardwareTier


def _mock_input(monkeypatch, values):
    it = iter(values)
    monkeypatch.setattr(init_wizard.console, "input", lambda *a, **k: next(it))


def _profile(tier=HardwareTier.MINIMUM):
    return SimpleNamespace(
        tier=tier, cpu_arch="x86_64", cpu_model="CPU", cpu_cores=4,
        ram_total_gb=8.0, ram_available_gb=6.0, storage_total_gb=100.0,
        storage_available_gb=50.0, gpu_info="none", gpu_available=False,
        os_name="Linux", os_version="5.0",
    )


# ─── _step_language_select ───────────────────────────────────────────────────


def test_language_select_zh(monkeypatch) -> None:
    _mock_input(monkeypatch, ["1"])
    assert _step_language_select() == "zh"


def test_language_select_en_aliases(monkeypatch) -> None:
    _mock_input(monkeypatch, ["english"])
    assert _step_language_select() == "en"


def test_language_select_invalid_then_valid(monkeypatch) -> None:
    _mock_input(monkeypatch, ["bad", "9", "2"])
    assert _step_language_select() == "en"


def test_language_select_empty_uses_default(monkeypatch) -> None:
    # Empty input -> default (locale-dependent; just assert it returns zh or en).
    _mock_input(monkeypatch, [""])
    assert _step_language_select() in ("zh", "en")


# ─── _ask_tier_override ──────────────────────────────────────────────────────


def test_ask_tier_phantom_early_return() -> None:
    # PHANTOM is idx 0 -> returned immediately without prompting.
    assert _ask_tier_override(HardwareTier.PHANTOM) == HardwareTier.PHANTOM


def test_ask_tier_keep_auto(monkeypatch) -> None:
    _mock_input(monkeypatch, ["0"])
    assert _ask_tier_override(HardwareTier.RECOMMENDED) == HardwareTier.RECOMMENDED


def test_ask_tier_override_lower(monkeypatch) -> None:
    _mock_input(monkeypatch, ["1"])
    assert _ask_tier_override(HardwareTier.RECOMMENDED) == HardwareTier.PHANTOM


def test_ask_tier_invalid_then_valid(monkeypatch) -> None:
    _mock_input(monkeypatch, ["abc", "9", "2"])
    assert _ask_tier_override(HardwareTier.RECOMMENDED) == HardwareTier.MINIMUM


def test_step_hardware_detect_with_tier_override(monkeypatch, tmp_path) -> None:
    # Override to a lower tier -> recomputes flags + prints updated report.
    fake = _profile(HardwareTier.RECOMMENDED)
    monkeypatch.setattr(init_wizard, "detect_hardware", lambda: fake)
    monkeypatch.setattr(init_wizard, "_ask_tier_override", lambda tier: HardwareTier.MINIMUM)
    db = Database(tmp_path / "hw2.db")
    try:
        result = _step_hardware_detect(db)
        assert result["profile"].tier == HardwareTier.MINIMUM
        assert db.get_hardware_profile()["tier"] == "minimum"
    finally:
        db.close()


# ─── _step_model_setup ───────────────────────────────────────────────────────


def _hw_result(llm=True, llm_model="qwen3-1_7b-instruct-q4", tier=HardwareTier.MINIMUM):
    flags = SimpleNamespace(llm=llm, llm_model=llm_model)
    return {"flags": flags, "profile": _profile(tier)}


def test_model_setup_no_flags_returns_none(monkeypatch) -> None:
    assert _step_model_setup(MagicMock(), {"flags": None, "profile": None}) == \
        {"model": None, "downloaded": False}


def test_model_setup_existing_model_matches(monkeypatch, tmp_path) -> None:
    # Place a .gguf whose stem matches the recommended model -> already downloaded.
    monkeypatch.setattr(init_wizard, "MODELS_DIR", tmp_path)
    (tmp_path / "qwen3-1_7b-instruct-q4.gguf").write_bytes(b"x")
    db = Database(tmp_path / "m.db")
    try:
        r = _step_model_setup(db, _hw_result())
        assert r == {"model": "qwen3-1_7b-instruct-q4", "downloaded": True}
    finally:
        db.close()


def test_model_setup_no_llm_flag(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(init_wizard, "MODELS_DIR", tmp_path)
    db = Database(tmp_path / "m2.db")
    try:
        r = _step_model_setup(db, _hw_result(llm=False))
        assert r == {"model": None, "downloaded": False}
    finally:
        db.close()


def test_model_setup_download_choice(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(init_wizard, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(init_wizard, "_download_model", lambda *a, **k: None)
    _mock_input(monkeypatch, ["1"])
    db = Database(tmp_path / "m3.db")
    try:
        r = _step_model_setup(db, _hw_result())
        assert r == {"model": "qwen3-1_7b-instruct-q4", "downloaded": True}
    finally:
        db.close()


def test_model_setup_skip_choice(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(init_wizard, "MODELS_DIR", tmp_path)
    _mock_input(monkeypatch, ["2"])
    db = Database(tmp_path / "m4.db")
    try:
        r = _step_model_setup(db, _hw_result())
        assert r["downloaded"] is False
    finally:
        db.close()


def test_model_setup_other_choice(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(init_wizard, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(init_wizard, "_choose_other_model", lambda: {"model": "other", "downloaded": True})
    _mock_input(monkeypatch, ["3"])
    db = Database(tmp_path / "m5.db")
    try:
        r = _step_model_setup(db, _hw_result())
        assert r == {"model": "other", "downloaded": True}
    finally:
        db.close()


def test_model_setup_invalid_then_skip(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(init_wizard, "MODELS_DIR", tmp_path)
    _mock_input(monkeypatch, ["x", "9", "2"])
    db = Database(tmp_path / "m6.db")
    try:
        assert _step_model_setup(db, _hw_result())["downloaded"] is False
    finally:
        db.close()


def test_model_setup_recommended_not_in_catalog(monkeypatch, tmp_path) -> None:
    # Recommended model name not in registry -> KeyError -> placeholders (covers [197,200]).
    monkeypatch.setattr(init_wizard, "MODELS_DIR", tmp_path)
    _mock_input(monkeypatch, ["2"])
    db = Database(tmp_path / "m7.db")
    try:
        r = _step_model_setup(db, _hw_result(llm_model="not-a-real-model"))
        assert r["downloaded"] is False
    finally:
        db.close()


# ─── _choose_other_model ─────────────────────────────────────────────────────


def test_choose_other_model_valid(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(init_wizard, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(init_wizard, "_download_model", lambda *a, **k: None)
    _mock_input(monkeypatch, ["1"])
    r = _choose_other_model()
    assert r["downloaded"] is True
    assert "model" in r


def test_choose_other_model_invalid_then_valid(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(init_wizard, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(init_wizard, "_download_model", lambda *a, **k: None)
    _mock_input(monkeypatch, ["bad", "99", "1"])
    r = _choose_other_model()
    assert r["downloaded"] is True


# ─── _download_model (non-network + mocked-network branches) ─────────────────


def test_download_model_unknown_name_returns() -> None:
    # Not in registry -> KeyError -> return before any filesystem access.
    assert _download_model("not-a-real-model", 1.0) is None


def test_download_model_dest_exists(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(init_wizard, "MODELS_DIR", tmp_path)
    name = "qwen3-1_7b-instruct-q4"
    entry = init_wizard._registry.get_model(name)
    dest = tmp_path / entry.url_hf.split("/")[-1]
    dest.write_bytes(b"x")
    assert _download_model(name, 1.0) is None  # already exists -> return


def test_download_model_no_url_returns(monkeypatch, tmp_path) -> None:
    # url_hf empty -> return (covers [281,282]).
    monkeypatch.setattr(init_wizard, "MODELS_DIR", tmp_path)
    fake_entry = SimpleNamespace(url_hf="", url_mirror="")
    monkeypatch.setattr(init_wizard._registry, "get_model", lambda n: fake_entry)
    assert _download_model("anything", 1.0) is None


def test_download_model_network_failure_records(monkeypatch, tmp_path) -> None:
    import urllib.request
    monkeypatch.setattr(init_wizard, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("net")))
    # Should not raise; all sources fail -> prints failure message.
    assert _download_model("qwen3-1_7b-instruct-q4", 1.0) is None


# ─── explicit shared assessment ──────────────────────────────────────────────


def test_initial_assessment_requires_explicit_unknown_for_every_domain(monkeypatch) -> None:
    # people, health, urgency, shelter, threats, then amount/rate for 5 resources.
    _mock_input(monkeypatch, ["2", "6", "5", "7", "3", *("2", "1") * 5])
    result = _step_initial_assessment()
    assert result["people_count"] == {"status": "unknown", "value": None}
    assert result["threats"] == {"status": "unknown", "values": []}
    assert all(
        resource["status"] == "unknown"
        and resource["rates"]["status"] == "unknown"
        for resource in result["resources"].values()
    )


def test_assessment_summary_requires_explicit_confirmation(monkeypatch) -> None:
    from allspark.services.initial_assessment import validate_initial_assessment
    from tests.assessment_helpers import valid_initial_assessment

    _mock_input(monkeypatch, ["", "maybe", "yes"])
    assert _step_assessment_summary(
        validate_initial_assessment(valid_initial_assessment())
    ) is True


# ─── _select_multi remaining branches ────────────────────────────────────────


def test_select_multi_empty_choice_returns_empty(monkeypatch) -> None:
    _mock_input(monkeypatch, [""])
    opts = [{"key": "a", "label_key": "q_a"}]
    assert _select_multi("pick", opts, allow_skip=True) == []


def test_select_multi_custom_skip(monkeypatch) -> None:
    _mock_input(monkeypatch, ["0", "custom-pick"])
    opts = [{"key": "a", "label_key": "q_a"}]
    assert _select_multi("pick", opts, allow_skip=True) == ["custom-pick"]


def test_select_multi_valid_index_and_free_text(monkeypatch) -> None:
    # "1" (valid idx) + "free" (free text) + duplicate "1" (deduped).
    _mock_input(monkeypatch, ["1, free, 1"])
    opts = [{"key": "a", "label_key": "q_a"}, {"key": "b", "label_key": "q_b"}]
    result = _select_multi("pick", opts)
    assert "a" in result and "free" in result
    assert result.count("a") == 1  # deduped


# ─── _step_summary + run_init_wizard ─────────────────────────────────────────


def test_step_summary_renders(monkeypatch) -> None:
    # Just assert it doesn't raise; covers the summary table build branches.
    flags = SimpleNamespace(llm_model="qwen3-1_7b-instruct-q4")
    profile = _profile()
    result = {
        "hardware": {"profile": profile, "flags": flags},
        "model": {"downloaded": True},
        "survivor": {"name": "Alice"},
    }
    _step_summary(result)  # no assertion needed; renders a table


def test_step_plan_selection_discloses_full_primary_contract_and_later_actions(
    monkeypatch,
) -> None:
    output = []
    monkeypatch.setattr(
        init_wizard.console,
        "print",
        lambda *values, **_kwargs: output.append(" ".join(map(str, values))),
    )
    _mock_input(monkeypatch, ["bad", "1"])
    plan = {
        "phase_description": "Phase pending assessment",
        "primary_candidate_ids": ["primary"],
        "actions": [
            {
                "id": "primary",
                "title": "Verify water",
                "why_now_text": "Water evidence is missing",
                "prerequisite_texts": ["Use measured facts"],
                "done_when_text": "Water facts are recorded",
                "risk_text": "Do not guess",
                "reassess_at_text": "Reassess within 1 hour",
            },
            {
                "id": "later",
                "title": "Review power",
                "why_now_text": "Power can be checked next",
                "prerequisite_texts": [],
                "done_when_text": "Power is recorded",
                "risk_text": "Do not guess",
                "reassess_at_text": "Reassess within 4 hours",
            },
        ],
    }

    assert _step_plan_selection(plan) == "primary"
    rendered = "\n".join(output)
    for expected in (
        "Phase pending assessment",
        "Verify water",
        "Water evidence is missing",
        "Use measured facts",
        "Water facts are recorded",
        "Do not guess",
        "Reassess within 1 hour",
        "Review power",
        "Power can be checked next",
    ):
        assert expected in rendered


def test_run_init_wizard_orchestrates_without_publishing(monkeypatch, tmp_path) -> None:
    # The wizard writes draft data only; the adapter publishes after bootstrap.
    monkeypatch.setattr(init_wizard, "_step_language_select", lambda: "zh")
    from allspark.services.initial_assessment import validate_initial_assessment
    from tests.assessment_helpers import valid_initial_assessment
    assessment = validate_initial_assessment(valid_initial_assessment())
    monkeypatch.setattr(init_wizard, "_step_initial_assessment", lambda: assessment)
    monkeypatch.setattr(init_wizard, "_step_assessment_summary", lambda value: True)
    monkeypatch.setattr(
        init_wizard,
        "_step_plan_selection",
        lambda plan: plan["primary_candidate_ids"][0],
    )
    monkeypatch.setattr(
        init_wizard,
        "_prepare_hardware_automatically",
        lambda db: {"profile": _profile(), "flags": SimpleNamespace(llm_model="x")},
    )
    db = Database(tmp_path / "run.db")
    try:
        r = run_init_wizard(db)
        assert r["language"] == "zh"
        assert r["assessment"] is assessment
        assert r["plan_id"]
        assert r["primary_action_id"]
        assert "survivor" not in r and "model" not in r
        assert db.is_initialized() is False
    finally:
        db.close()


# ─── remaining branches: phantom tier, select_multi edges, download success ──


def test_step_hardware_detect_phantom_warns(monkeypatch, tmp_path) -> None:
    # PHANTOM tier -> prints the below-minimum warning (covers [75,76]).
    fake = _profile(HardwareTier.PHANTOM)
    monkeypatch.setattr(init_wizard, "detect_hardware", lambda: fake)
    monkeypatch.setattr(init_wizard, "_ask_tier_override", lambda tier: tier)
    db = Database(tmp_path / "pw.db")
    try:
        result = _step_hardware_detect(db)
        assert result["profile"].tier == HardwareTier.PHANTOM
    finally:
        db.close()


def test_select_multi_custom_empty_not_appended(monkeypatch) -> None:
    # "0" (custom) then empty input -> not appended (covers [514,510]).
    _mock_input(monkeypatch, ["0", ""])
    opts = [{"key": "a", "label_key": "q_a"}]
    assert _select_multi("pick", opts, allow_skip=True) == []


def test_select_multi_empty_part_skipped(monkeypatch) -> None:
    # "1,,free" -> the empty middle part is skipped (covers [526,510]).
    _mock_input(monkeypatch, ["1,,free"])
    opts = [{"key": "a", "label_key": "q_a"}, {"key": "b", "label_key": "q_b"}]
    result = _select_multi("pick", opts)
    assert "a" in result and "free" in result


def test_download_model_success_writes_dest(monkeypatch, tmp_path) -> None:
    # Mock urlopen to yield chunks -> tmp written then renamed to dest
    # (covers the read-loop + rename branches [325,326],[328,329],[328,330]).
    import urllib.request

    monkeypatch.setattr(init_wizard, "MODELS_DIR", tmp_path)

    class _FakeResp:
        def __init__(self, chunks):
            self._chunks = list(chunks)
            self.headers = {"Content-Length": str(sum(len(c) for c in self._chunks))}

        def read(self, _n):
            return self._chunks.pop(0) if self._chunks else b""

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: _FakeResp([b"chunk1", b"chunk2"]))
    name = "qwen3-1_7b-instruct-q4"
    _download_model(name, 1.0)
    entry = init_wizard._registry.get_model(name)
    dest = tmp_path / entry.url_hf.split("/")[-1]
    assert dest.exists()
    assert dest.read_bytes() == b"chunk1chunk2"
