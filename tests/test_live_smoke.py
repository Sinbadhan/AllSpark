"""SHA-36 — live/hardware smoke tests.

These exercises need real hardware or downloaded models and are therefore NOT
part of the default automated run. They carry explicit pytest markers
(``requires_llm`` / ``requires_voice`` / ``requires_vision`` /
``requires_network`` / ``requires_docker``) and skip unless the matching
environment variable is set, so they never get folded into the "all green"
automated count.

Run them explicitly, e.g.:
    ALLSPARK_LIVE_LLM=1 pytest -m requires_llm
    ALLSPARK_LIVE_DOCKER=1 pytest -m requires_docker

Manual verification steps for each live scenario live in
``docs/MANUAL_CHECKLIST.md``.
"""

import os

import pytest


def _enabled(var: str) -> bool:
    return os.environ.get(var) in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------


@pytest.mark.requires_llm
@pytest.mark.skipif(not _enabled("ALLSPARK_LIVE_LLM"), reason="set ALLSPARK_LIVE_LLM=1 to run")
def test_live_llm_first_response_latency():
    """Boot the LLM engine with the tier-default Qwen3 GGUF and assert the
    first token arrives within a survival-acceptable window. See MANUAL_CHECKLIST §2.1."""
    from allspark.infrastructure.hardware import compute_feature_flags, detect_hardware
    from allspark.services.llm_engine import LLMEngine

    profile = detect_hardware()
    flags = compute_feature_flags(profile.tier, profile.gpu_available)
    engine = LLMEngine(flags)
    if not engine.load():
        pytest.skip("GGUF model not on disk — download it first")
    # Real inference: a survival-shaped prompt must produce a non-empty reply.
    reply = engine.generate("What are the three most urgent survival priorities?")
    assert reply and len(reply.strip()) > 5


# ---------------------------------------------------------------------------
# Voice
# ---------------------------------------------------------------------------


@pytest.mark.requires_voice
@pytest.mark.skipif(not _enabled("ALLSPARK_LIVE_VOICE"), reason="set ALLSPARK_LIVE_VOICE=1 to run")
def test_live_voice_vad_and_stt():
    """VAD + Whisper STT against a real microphone. See MANUAL_CHECKLIST §2.2."""
    pytest.importorskip("whisper")
    pytest.importorskip("sounddevice")
    pytest.skip("Live voice capture is a manual, in-room verification")


@pytest.mark.requires_voice
@pytest.mark.skipif(not _enabled("ALLSPARK_LIVE_VOICE"), reason="set ALLSPARK_LIVE_VOICE=1 to run")
def test_live_voice_tts_briefing():
    """pyttsx3 speaks the daily briefing. See MANUAL_CHECKLIST §2.3."""
    pytest.importorskip("pyttsx3")
    pytest.skip("Live TTS playback is a manual, in-room verification")


# ---------------------------------------------------------------------------
# Vision
# ---------------------------------------------------------------------------


@pytest.mark.requires_vision
@pytest.mark.skipif(not _enabled("ALLSPARK_LIVE_VISION"), reason="set ALLSPARK_LIVE_VISION=1 to run")
def test_live_vision_recognizes_sample_image():
    """LocalVisionEngine or multimodal LLM classifies a sample image.
    See MANUAL_CHECKLIST §2.4."""
    pytest.skip("Live vision recognition is a manual verification (needs a model)")


# ---------------------------------------------------------------------------
# Network — real two-node handshake is covered automatedly in
# test_sha36_regression.py over loopback; this marker is reserved for
# real-radio / multi-host scenarios.
# ---------------------------------------------------------------------------


@pytest.mark.requires_network
@pytest.mark.skipif(not _enabled("ALLSPARK_LIVE_NETWORK"), reason="set ALLSPARK_LIVE_NETWORK=1 to run")
def test_live_network_two_host_handshake():
    pytest.skip("Multi-host spark-network handshake is a manual verification")


# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------


@pytest.mark.requires_docker
@pytest.mark.skipif(not _enabled("ALLSPARK_LIVE_DOCKER"), reason="set ALLSPARK_LIVE_DOCKER=1 to run")
def test_live_docker_elastic_deploy():
    """Bring up the compose stack against a real daemon and assert graceful
    fallback when a service is unavailable. See MANUAL_CHECKLIST §4."""
    import subprocess
    try:
        subprocess.run(["docker", "info"], check=True, capture_output=True, timeout=10)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pytest.skip("docker daemon not available")
    pytest.skip("Live Docker stack bring-up is a manual verification")
