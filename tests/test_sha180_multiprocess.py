"""SHA-180: Spark Network integration across independent OS processes."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from allspark.core.config import SPARKNET_MAX_INCOMING_BYTES
from allspark.core.database import Database
from allspark.core.models import KnowledgeEntry
from allspark.services.spark_network import (
    ChannelType,
    NetworkMessage,
    NodeStatus,
    SparkNetwork,
    SparkNode,
)

_SECRET = "sha180-shared-secret"
_SERVER_READY_TIMEOUT_SECONDS = 30
_SERVER_ORPHAN_TIMEOUT_SECONDS = 90


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _write_ready(path: Path, payload: dict[str, object]) -> None:
    pending = path.with_suffix(f"{path.suffix}.tmp")
    pending.write_text(json.dumps(payload), encoding="utf-8")
    pending.replace(path)


def _server_worker(
    db_path: Path,
    port: int,
    ready_path: Path,
    stop_path: Path,
    max_incoming_bytes: int | None = None,
) -> int:
    if max_incoming_bytes is not None:
        import allspark.services.spark_network as network_module

        network_module.SPARKNET_MAX_INCOMING_BYTES = max_incoming_bytes

    db = Database(db_path)
    db.save_survivor_state("network_shared_secret", _SECRET)
    db.save_knowledge(
        KnowledgeEntry(
            id="server/water/1",
            category="water",
            subcategory="general",
            priority=1,
            title="Server water",
            summary="Server process knowledge",
        )
    )
    network = SparkNetwork(db=db, spark_id="server-process")
    try:
        result = network.start_exchange_server(host="127.0.0.1", port=port)
        _write_ready(ready_path, result)
        if result.get("status") != "started":
            return 1

        deadline = time.monotonic() + _SERVER_ORPHAN_TIMEOUT_SECONDS
        while not stop_path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        return 0 if stop_path.exists() else 2
    except Exception as exc:
        _write_ready(ready_path, {"status": "error", "message": repr(exc)})
        return 1
    finally:
        network.stop_discovery()
        time.sleep(1.1)
        db.close()


def _start_server(
    db_path: Path,
    port: int,
    *,
    max_incoming_bytes: int | None = None,
) -> tuple[subprocess.Popen[str], Path]:
    ready_path = db_path.with_suffix(".ready.json")
    stop_path = db_path.with_suffix(".stop")
    ready_path.unlink(missing_ok=True)
    stop_path.unlink(missing_ok=True)
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--db-path",
        str(db_path),
        "--port",
        str(port),
        "--ready-path",
        str(ready_path),
        "--stop-path",
        str(stop_path),
    ]
    if max_incoming_bytes is not None:
        command.extend(["--max-incoming-bytes", str(max_incoming_bytes)])
    env = os.environ.copy()
    project_root = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = (
        project_root + os.pathsep + env["PYTHONPATH"]
        if env.get("PYTHONPATH") else project_root
    )
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    deadline = time.monotonic() + _SERVER_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if ready_path.exists():
            started = json.loads(ready_path.read_text(encoding="utf-8"))
            break
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(
                "server process exited before readiness "
                f"(exitcode={process.returncode}, stdout={stdout!r}, stderr={stderr!r})"
            )
        time.sleep(0.05)
    else:
        alive_at_timeout = process.poll() is None
        exitcode_at_timeout = process.poll()
        if alive_at_timeout:
            process.terminate()
        stdout, stderr = process.communicate(timeout=5)
        raise AssertionError(
            "server process did not report readiness "
            f"within {_SERVER_READY_TIMEOUT_SECONDS}s "
            f"(alive={alive_at_timeout}, exitcode={exitcode_at_timeout}, "
            f"stdout={stdout!r}, stderr={stderr!r})"
        )
    if started["status"] != "started":
        stop_path.touch()
        stdout, stderr = process.communicate(timeout=5)
        raise AssertionError(
            f"server failed to start: {started!r} "
            f"(exitcode={process.returncode}, stdout={stdout!r}, stderr={stderr!r})"
        )
    return process, stop_path


def _stop_server(process: subprocess.Popen[str], stop_path: Path) -> None:
    stop_path.touch()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(timeout=5)
    stdout, stderr = process.communicate()
    assert process.returncode == 0, (stdout, stderr)


def _node(port: int) -> SparkNode:
    return SparkNode(
        node_id="server-process",
        spark_id="server-process",
        address="127.0.0.1",
        port=port,
        channel=ChannelType.LAN,
        status=NodeStatus.CONNECTED,
    )


def _entry_payload(entry_id: str) -> dict[str, object]:
    return {
        "id": entry_id,
        "category": "energy",
        "subcategory": "general",
        "priority": 1,
        "title": "Transferred fire",
        "summary": "Signed process transfer",
        "steps": ["prepare fuel"],
        "prerequisites": [],
        "warnings": [],
        "verification": "unverified",
        "source": "pre_collapse",
        "version": 1,
        "language": "en",
    }


def _send_raw(port: int, message: NetworkMessage) -> NetworkMessage | None:
    with socket.create_connection(("127.0.0.1", port), timeout=3) as sock:
        sock.sendall(message.to_json().encode("utf-8"))
        sock.shutdown(socket.SHUT_WR)
        response = b""
        while chunk := sock.recv(65536):
            response += chunk
    return NetworkMessage.from_json(response.decode("utf-8")) if response else None


def _knowledge_exists(db_path: Path, entry_id: str) -> bool:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        with sqlite3.connect(db_path) as conn:
            found = conn.execute(
                "SELECT 1 FROM knowledge WHERE id=?", (entry_id,)
            ).fetchone()
        if found:
            return True
        time.sleep(0.05)
    return False


def test_signed_transfer_tamper_rejection_disconnect_and_restart(tmp_path: Path) -> None:
    server_db_path = tmp_path / "server.db"
    client_db = Database(tmp_path / "client.db")
    client_db.save_survivor_state("network_shared_secret", _SECRET)
    entry = KnowledgeEntry(
        id="client/fire/1",
        category="energy",
        subcategory="general",
        priority=1,
        title="Transferred fire",
        summary="Signed process transfer",
        steps=["prepare fuel"],
        prerequisites=[],
        warnings=[],
        verification="unverified",
        source="pre_collapse",
        version=1,
        language="en",
    )
    client_db.save_knowledge(entry)
    client = SparkNetwork(db=client_db, spark_id="client-process")
    port = _free_port()
    process, stop = _start_server(server_db_path, port)
    client.nodes["server-process"] = _node(port)

    try:
        exchange = client.request_exchange("server-process")
        assert exchange["status"] == "ok", exchange
        assert "water" in exchange["remote_index"]["categories"]

        sent = client.send_knowledge("server-process", [entry.id])
        assert sent["status"] == "ok", sent
        assert sent["pending_count"] == 1
        assert _knowledge_exists(server_db_path, entry.id)

        tampered = NetworkMessage(
            msg_type="knowledge_transfer",
            sender_id="client-process",
            payload={
                "entries": [_entry_payload("client/tampered/1")],
                "signatures": {"client/tampered/1": "0" * 64},
            },
        )
        tampered_ack = _send_raw(port, tampered)
        assert tampered_ack is not None
        assert tampered_ack.payload["sig_rejected_count"] == 1
        assert not _knowledge_exists(server_db_path, "client/tampered/1")

        unsigned = NetworkMessage(
            msg_type="knowledge_transfer",
            sender_id="client-process",
            payload={"entries": [_entry_payload("client/unsigned/1")]},
        )
        unsigned_ack = _send_raw(port, unsigned)
        assert unsigned_ack is not None
        assert unsigned_ack.payload["sig_rejected_count"] == 1
        assert not _knowledge_exists(server_db_path, "client/unsigned/1")
    finally:
        _stop_server(process, stop)

    disconnected = client.request_exchange("server-process")
    assert disconnected["status"] == "error"

    restarted_process, restarted_stop = _start_server(server_db_path, port)
    try:
        recovered = client.request_exchange("server-process")
        assert recovered["status"] == "ok", recovered
        assert "water" in recovered["remote_index"]["categories"]
    finally:
        _stop_server(restarted_process, restarted_stop)
        client_db.close()


def test_configured_size_limit_drops_payload_and_server_recovers(tmp_path: Path) -> None:
    port = _free_port()
    process, stop = _start_server(
        tmp_path / "limited-server.db",
        port,
        max_incoming_bytes=1024,
    )
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=3) as sock:
            sock.sendall(b"x" * 1025)
            sock.shutdown(socket.SHUT_WR)
            assert sock.recv(1) == b""

        request = NetworkMessage(
            msg_type="exchange_request",
            sender_id="limit-client",
            payload={"categories": [], "index": {"categories": {}, "total": 0}},
        )
        response = _send_raw(port, request)
        assert response is not None
        assert response.msg_type == "exchange_response"
    finally:
        _stop_server(process, stop)

    assert SPARKNET_MAX_INCOMING_BYTES == 50 * 1024 * 1024


def _worker_cli() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true", required=True)
    parser.add_argument("--db-path", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--ready-path", type=Path, required=True)
    parser.add_argument("--stop-path", type=Path, required=True)
    parser.add_argument("--max-incoming-bytes", type=int)
    args = parser.parse_args()
    return _server_worker(
        args.db_path,
        args.port,
        args.ready_path,
        args.stop_path,
        args.max_incoming_bytes,
    )


if __name__ == "__main__":
    raise SystemExit(_worker_cli())
