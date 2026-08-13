"""Render AllSpark's first Web page from an installed wheel using only runtime deps."""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from pathlib import Path


def _reserve_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def validate_rendered_page(status: int, headers: Mapping[str, str], body: str) -> None:
    normalized_headers = {key.lower(): value for key, value in headers.items()}
    if status != 200:
        raise RuntimeError(f"expected HTTP 200, received {status}")
    if not normalized_headers.get("content-type", "").startswith("text/html"):
        raise RuntimeError("first-run route did not render HTML")
    if "script-src-attr 'none'" not in normalized_headers.get(
        "content-security-policy", ""
    ):
        raise RuntimeError("first-run response is missing the enforcing CSP contract")
    for marker in (
        "<!DOCTYPE html>",
        'id="immediate-danger-open"',
        'id="immediate-danger-dialog"',
    ):
        if marker not in body:
            raise RuntimeError(f"rendered first-run page is missing {marker}")


def smoke_installed_web(timeout_seconds: float = 20.0) -> None:
    port = _reserve_loopback_port()
    with tempfile.TemporaryDirectory(prefix="allspark-wheel-web-") as temp_dir:
        temp_path = Path(temp_dir)
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "allspark",
                "--web",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--db",
                str(temp_path / "smoke.db"),
            ],
            cwd=temp_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            deadline = time.monotonic() + timeout_seconds
            last_error = "server did not accept a request"
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    output = process.stdout.read() if process.stdout else ""
                    raise RuntimeError(
                        f"installed-wheel Web server exited with {process.returncode}:\n{output}"
                    )
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/", timeout=1.0
                    ) as response:
                        body = response.read(4_000_000).decode("utf-8")
                        validate_rendered_page(
                            response.status,
                            dict(response.headers.items()),
                            body,
                        )
                        return
                except (OSError, UnicodeDecodeError, urllib.error.URLError) as exc:
                    last_error = str(exc)
                    time.sleep(0.1)
            raise RuntimeError(
                f"installed-wheel Web page did not become ready in {timeout_seconds:.1f}s: "
                f"{last_error}"
            )
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5.0)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render the AllSpark first-run Web page from the active Python installation."
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()
    smoke_installed_web(args.timeout)
    print("Installed-wheel Web render passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
