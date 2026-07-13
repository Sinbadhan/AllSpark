"""SHA-151: targeted tests for lowest-coverage command modules.

Raises coverage on comms.py (10% -> higher) and docker.py (14% -> higher)
by exercising NetworkCommand/VisionCommand/DockerCommand execute() paths.
"""
import tempfile
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from allspark.commands.comms import NetworkCommand, VisionCommand
from allspark.container import ServiceContainer
from allspark.core.database import Database
from allspark.core.i18n import set_language


@pytest.fixture
def container(tmp_path):
    db = Database(tmp_path / "test.db")
    db.mark_initialized()
    c = ServiceContainer(db)
    # Mock spark_network
    net = MagicMock()
    net.get_status.return_value = {
        "spark_id": "test-spark",
        "running": True,
        "channels": {"tcp": True, "udp": False},
        "known_nodes": 1,
        "nodes": [{"name": "node-1", "knowledge_count": 5, "status": "online"}],
    }
    net.start.return_value = {"status": "ok"}
    net.stop.return_value = {"status": "ok"}
    net.discover.return_value = {"found": 0, "nodes": []}
    c.register("spark_network", net)
    # Mock LLM
    llm = MagicMock()
    llm.available = False
    c.register("llm", llm)
    yield c
    db.close()


class TestNetworkCommand:
    def test_status(self, container):
        set_language("en")
        cmd = NetworkCommand(container)
        cmd.console = MagicMock()
        cmd.execute([])
        container.get("spark_network").get_status.assert_called_once()

    def test_start(self, container):
        set_language("en")
        cmd = NetworkCommand(container)
        cmd.console = MagicMock()
        cmd.execute(["start"])
        container.get("spark_network").start.assert_called_once()

    def test_stop(self, container):
        set_language("en")
        cmd = NetworkCommand(container)
        cmd.console = MagicMock()
        cmd.execute(["stop"])
        container.get("spark_network").stop.assert_called_once()

    def test_discover(self, container):
        set_language("en")
        cmd = NetworkCommand(container)
        cmd.console = MagicMock()
        cmd.execute(["discover"])
        container.get("spark_network").discover.assert_called_once()


class TestVisionCommand:
    def test_status_no_camera(self, container):
        set_language("en")
        cmd = VisionCommand(container)
        cmd.console = MagicMock()
        # VisionCommand with no vision service should not crash.
        cmd.execute([])


class TestDockerCommand:
    def test_status(self, container):
        set_language("en")
        from allspark.commands.docker import DockerCommand
        docker_mgr = MagicMock()
        docker_mgr.get_status.return_value = {
            "mode": "PROCESS",
            "available": False,
            "containers": [],
        }
        container.register("docker_manager", docker_mgr)
        cmd = DockerCommand(container)
        cmd.console = MagicMock()
        cmd.execute([])
        docker_mgr.get_status.assert_called_once()
