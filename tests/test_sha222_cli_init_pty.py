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
    assert "Step 1/4: Language" in output
    assert "Choose your language" in output
    assert "中文 / Chinese (zh)" in output
    assert "English / 英语 (en)" in output
    assert "初次启动" not in output
