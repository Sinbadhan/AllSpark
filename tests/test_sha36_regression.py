"""SHA-36 — regression coverage for the three areas that previously only had
manual verification: Spark Network two-node handshake, Docker graceful
degradation, and the adaptive TaskScheduler.

Design notes:
- Network: spin up TWO real SparkNetwork instances in the same process on
  ephemeral loopback ports and drive a full request_exchange -> send_knowledge
  -> receive_knowledge round trip. No real radios — pure TCP on 127.0.0.1.
- Docker: DockerManager must degrade gracefully when the docker binary is
  absent (the CI/local-dev case). We assert the no-daemon path explicitly so
  a future refactor can't silently start shelling out to a missing docker.
- Scheduler: ScheduledTask.should_run() reads wall-clock time, so we drive
  the "long-time" scenarios (mode-gated suppression, interval expiry, error
  capture) deterministically by manipulating _last_run instead of sleeping.
"""

from __future__ import annotations

import os
import socket
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from allspark.core.database import Database
from allspark.core.models import KnowledgeEntry, OperatingMode, ResourceType
from allspark.docker_manager import DockerManager
from allspark.infrastructure.hardware import DeployMode, FeatureFlags
from allspark.services.scheduler import ScheduledTask, TaskScheduler, create_default_scheduler
from allspark.services.spark_network import NodeStatus, SparkNetwork

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", 0))
        except PermissionError as exc:
            pytest.skip(f"localhost TCP bind unavailable in this environment: {exc}")
        return s.getsockname()[1]


class _TempDb:
    def __enter__(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db = Database(self.path)
        return self.db

    def __exit__(self, *exc):
        self.db.close()
        if os.path.exists(self.path):
            os.unlink(self.path)


def _seed_knowledge(db, *, eid, category, title, language="zh"):
    db.save_knowledge(KnowledgeEntry(
        id=eid, category=category, subcategory="general", priority=1,
        title=title, summary="test summary", language=language,
    ))


# ---------------------------------------------------------------------------
# Spark Network — two-node exchange over loopback
# ---------------------------------------------------------------------------


class TestSparkNetworkTwoNode:
    """Spin up a server node and a client node on 127.0.0.1 and exchange."""

    def test_exchange_request_returns_remote_index(self):
        with _TempDb() as server_db, _TempDb() as client_db:
            _seed_knowledge(server_db, eid="srv/water/1", category="survival", title="Water")
            _seed_knowledge(client_db, eid="cli/fire/1", category="energy", title="Fire")

            port = _free_port()
            server = SparkNetwork(db=server_db, spark_id="server-node")
            client = SparkNetwork(db=client_db, spark_id="client-node")

            started = server.start_exchange_server(host="127.0.0.1", port=port)
            assert started["status"] == "started"
            try:
                # Manually register the server as a known, connected peer on the
                # client (discovery via UDP beacon is flaky under test load and
                # not what we are exercising here).
                from allspark.services.spark_network import ChannelType, SparkNode
                client.nodes["server-node"] = SparkNode(
                    node_id="server-node", spark_id="server-node",
                    address="127.0.0.1", port=port, channel=ChannelType.LAN,
                    status=NodeStatus.CONNECTED,
                )

                result = client.request_exchange("server-node")
                assert result["status"] == "ok", result
                # Server's index advertises the survival category.
                assert "survival" in result["remote_index"].get("categories", {})
                # The server computes complementary = remote_cats - my_cats,
                # i.e. what the CLIENT has that the server lacks. The client
                # seeded the energy category, so the server flags it back.
                assert "energy" in result["complementary"]
            finally:
                server.stop_discovery()

    def test_knowledge_transfer_round_trip(self):
        with _TempDb() as server_db, _TempDb() as client_db:
            # The CLIENT owns an entry it will push to the server.
            _seed_knowledge(client_db, eid="cli/fire/1", category="energy", title="Fire making")

            port = _free_port()
            server = SparkNetwork(db=server_db, spark_id="server-node")
            client = SparkNetwork(db=client_db, spark_id="client-node")
            server.start_exchange_server(host="127.0.0.1", port=port)
            try:
                from allspark.services.spark_network import ChannelType, SparkNode
                client.nodes["server-node"] = SparkNode(
                    node_id="server-node", spark_id="server-node",
                    address="127.0.0.1", port=port, channel=ChannelType.LAN,
                    status=NodeStatus.CONNECTED,
                )

                # send_knowledge looks the entries up in the SENDER's (client) DB.
                send = client.send_knowledge("server-node", ["cli/fire/1"])
                assert send["status"] == "ok", send
                # The server received and stored the transferred entry.
                got = server.db.get_knowledge("cli/fire/1")
                assert got is not None
                assert got.source == "other_spark"
                assert got.verification == "unverified"
            finally:
                server.stop_discovery()

    def test_receive_knowledge_downgrades_sender_verification_claims(self):
        with _TempDb() as db:
            _seed_knowledge(
                db,
                eid="local/water/overlap",
                category="survival",
                title="Water treatment",
            )
            network = SparkNetwork(db=db, spark_id="receiver")
            for claim in ("expert_verified", "field_tested"):
                entry_id = f"attacker/{claim}"
                result = network.receive_knowledge([{
                    "id": entry_id,
                    "category": "survival",
                    "subcategory": "water",
                    "priority": 1,
                    "title": "Water treatment",
                    "summary": "Attacker supplied claim",
                    "verification": claim,
                    "source": "pre_collapse",
                }])
                assert result["accepted_count"] == 0
                assert result["pending_count"] == 1
                persisted = db.get_knowledge(entry_id)
                assert persisted is not None
                assert persisted.source == "other_spark"
                assert persisted.verification == "unverified"

    def test_request_exchange_unknown_node_errors_cleanly(self):
        with _TempDb() as db:
            net = SparkNetwork(db=db, spark_id="solo")
            result = net.request_exchange("no-such-node")
            assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Docker — graceful degradation when the daemon is absent
# ---------------------------------------------------------------------------


class TestDockerGracefulDegradation:
    """When `docker` is not on PATH (CI, dev laptops), DockerManager must report
    unavailable and refuse to start/migrate — never shell out to a missing
    binary. This is the no-hardware Docker case from SHA-36."""

    def _manager(self, db, *, deploy_mode=DeployMode.PROCESS):
        flags = FeatureFlags()
        return DockerManager(db, flags=flags, deploy_mode=deploy_mode)

    def test_status_reports_unavailable_without_daemon(self):
        with _TempDb() as db:
            mgr = self._manager(db)
            with patch("allspark.docker_manager.subprocess.run", side_effect=FileNotFoundError):
                status = mgr.get_status()
            assert status["docker_available"] is False
            assert status["deploy_mode"] == DeployMode.PROCESS.value
            assert status["services"] == {}

    def test_start_service_refuses_without_daemon(self):
        with _TempDb() as db:
            mgr = self._manager(db)
            with patch("allspark.docker_manager.subprocess.run", side_effect=FileNotFoundError):
                result = mgr.start_service("kiwix")
            assert result["status"] == "error"

    def test_migrate_to_docker_blocks_without_daemon(self):
        with _TempDb() as db:
            mgr = self._manager(db)
            with patch("allspark.docker_manager.subprocess.run", side_effect=FileNotFoundError):
                result = mgr.migrate_to_docker()
            assert result["status"] == "error"

    def test_migrate_to_process_works_without_daemon(self):
        """Down-migrating to PROCESS must succeed even with no daemon — it is
        the safe fallback tier and shouldn't depend on docker being present."""
        with _TempDb() as db:
            mgr = self._manager(db, deploy_mode=DeployMode.DOCKER)
            with patch("allspark.docker_manager.subprocess.run", side_effect=FileNotFoundError):
                result = mgr.migrate_to_process()
            assert result["status"] == "ok"
            assert result["deploy_mode"] == "process"
            assert mgr.deploy_mode == DeployMode.PROCESS


# ---------------------------------------------------------------------------
# Scheduler — adaptive cadence + long-time scenarios without sleeping
# ---------------------------------------------------------------------------


class TestTaskScheduler:
    def test_tick_runs_due_task_once(self):
        calls = []
        task = ScheduledTask("ping", lambda: calls.append(1) or "done", interval_hours=1)
        sched = TaskScheduler(get_mode=lambda: OperatingMode.STANDARD)
        sched.register(task)
        results = sched.tick()
        assert len(results) == 1
        assert results[0]["status"] == "ok"
        # A second immediate tick does NOT re-run (interval not elapsed).
        sched.tick()
        assert len(calls) == 1

    def test_hibernation_suppresses_non_critical_tasks(self):
        ran = []
        task = ScheduledTask("housekeeping", lambda: ran.append(1), interval_hours=1)
        sched = TaskScheduler(get_mode=lambda: OperatingMode.HIBERNATION)
        sched.register(task)
        sched.tick()
        assert ran == []  # suppressed

    def test_critical_only_task_runs_in_economy(self):
        ran = []
        task = ScheduledTask("critical_check", lambda: ran.append(1), interval_hours=1, critical_only=True)
        sched = TaskScheduler(get_mode=lambda: OperatingMode.ECONOMY)
        sched.register(task)
        sched.tick()
        assert ran == [1]

    def test_interval_expiry_re_runs_task(self):
        calls = []
        task = ScheduledTask("periodic", lambda: calls.append(1), interval_hours=1)
        # Force the last run far enough in the past that the interval expired,
        # simulating the "long-time scheduler" passage without sleeping.
        task._last_run = datetime.now() - timedelta(hours=2)
        sched = TaskScheduler(get_mode=lambda: OperatingMode.STANDARD)
        sched.register(task)
        sched.tick()
        assert calls == [1]

    def test_handler_exception_is_captured_not_raised(self):
        def boom():
            raise RuntimeError("kaboom")
        task = ScheduledTask("boom", boom, interval_hours=1)
        sched = TaskScheduler(get_mode=lambda: OperatingMode.STANDARD)
        sched.register(task)
        results = sched.tick()
        assert results[0]["status"] == "error"
        assert "kaboom" in results[0]["error"]
        # Scheduler stays usable after a failing task.
        assert sched.get_status()["running"] is False


# ---------------------------------------------------------------------------
# Default scheduler wiring — resource_check + daily_briefing registered
# ---------------------------------------------------------------------------


class TestDefaultSchedulerWiring:
    def test_default_scheduler_registers_core_tasks(self):
        with _TempDb() as db:
            db.mark_initialized()
            from allspark.bootstrap import ApplicationBootstrap
            container = ApplicationBootstrap(db, flags=FeatureFlags()).bootstrap()
            sched = create_default_scheduler(container)
            names = set(sched._tasks.keys())
            # The two long-time scenarios SHA-36 calls out.
            assert "resource_check" in names
            assert "daily_briefing" in names

    def test_resource_check_task_reports_warnings(self):
        from allspark.bootstrap import ApplicationBootstrap

        with _TempDb() as db:
            db.mark_initialized()
            # Seed a water resource that will run out soon -> should warn.
            from allspark.core.models import Resource
            db.upsert_resource(Resource(
                type=ResourceType.WATER, current_amount=1.0, unit="L",
                daily_consumption=3.0, daily_intake=0.0,
            ))
            container = ApplicationBootstrap(db, flags=FeatureFlags()).bootstrap()
            sched = create_default_scheduler(container)
            task = sched._tasks["resource_check"]
            result = task.execute()
            assert result["status"] == "ok"
            # check_warnings returns a list of warning dicts when critical.
            assert isinstance(result["result"], list)
