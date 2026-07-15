"""SHA-222: the CLI first-choice screen must be understandable in a real PTY."""

from __future__ import annotations

import os
import pty
import re
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _read_until(fd: int, marker: str, timeout: float = 15) -> str:
    chunks: list[bytes] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.1)
        if not ready:
            continue
        try:
            chunks.append(os.read(fd, 4096))
        except OSError:
            break
        text = _ANSI.sub("", b"".join(chunks).decode("utf-8", errors="replace"))
        if marker in text:
            return text
    raise AssertionError(f"PTY output did not reach {marker!r}: {text}")


def test_en_locale_is_understandable_before_first_input(tmp_path: Path) -> None:
    master, slave = pty.openpty()
    env = os.environ.copy()
    env.update({"LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TERM": "xterm-256color"})
    process = subprocess.Popen(
        [sys.executable, "-m", "allspark", "--db", str(tmp_path / "fresh.db")],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        start_new_session=True,
    )
    os.close(slave)
    try:
        output = _read_until(master, "default 2")
    finally:
        os.close(master)
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)

    assert "Initialization" in output
    assert "First launch" in output
    assert "Step 1/3: Language" in output
    assert "Choose your language" in output
    assert "中文 / Chinese (zh)" in output
    assert "English / 英语 (en)" in output
    assert "初次启动" not in output


def test_cli_publishes_after_assessment_without_profile_or_hardware_prompts(
    tmp_path: Path,
) -> None:
    master, slave = pty.openpty()
    env = os.environ.copy()
    env.update({"LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TERM": "xterm-256color"})
    process = subprocess.Popen(
        [sys.executable, "-m", "allspark", "--db", str(tmp_path / "complete.db")],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        start_new_session=True,
    )
    os.close(slave)
    try:
        _read_until(master, "default 2")
        # Language; five critical domains; amount/rate state for every resource.
        # Water is a known observed amount plus an explicit group_total rate
        # estimate while people_count remains unknown.
        answers = [
            "2", "2", "6", "5", "7", "3",
            "2", "1",  # power unknown amount/rate
            "1", "10", "2", "4", "1",  # water amount + rate estimate
            "2", "1",  # food
            "2", "1",  # fire
            "2", "1",  # storage
            "yes",
        ]
        os.write(master, ("\n".join(answers) + "\n").encode())
        output = _read_until(master, "Initialization complete", timeout=30)
    finally:
        os.close(master)
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)

    assert "Estimated total daily consumption 4.0 L/day" in output
    assert "Mixed sources" in output
    assert "total basis" in output
    assert "Step 3/3: Review before initialization" in output
    assert "Choose hardware tier" not in output
    assert "GPS" not in output
    assert "Skills" not in output
    assert "AI Model Setup" not in output


def test_cli_known_people_count_rejects_empty_input(tmp_path: Path) -> None:
    master, slave = pty.openpty()
    env = os.environ.copy()
    env.update({"LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TERM": "xterm-256color"})
    process = subprocess.Popen(
        [sys.executable, "-m", "allspark", "--db", str(tmp_path / "people.db")],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        start_new_session=True,
    )
    os.close(slave)
    try:
        _read_until(master, "default 2")
        os.write(master, b"2\n1\n")
        _read_until(master, "People in your group (including you) >")
        os.write(master, b"\n")
        output = _read_until(master, "People in your group (including you) >")
    finally:
        os.close(master)
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)

    assert "must be a whole number" in output
    assert "[1]" not in output
