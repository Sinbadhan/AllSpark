import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from allspark.core.database import Database
from allspark.core.i18n import set_language, t
from allspark.core.models import ResetLevel
from allspark.docker_manager import _DOCKER_SERVICES, DockerManager
from allspark.infrastructure.hardware import (
    DEPLOY_MODE_MAP,
    DeployMode,
    FeatureFlags,
    HardwareProfile,
    HardwareTier,
    compute_feature_flags,
    detect_hardware,
    format_hardware_report,
)
from allspark.services.reset_manager import ResetManager


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    database = Database(path)
    yield database
    database.close()
    os.unlink(path)


class TestDeployMode:
    def test_phantom_maps_to_process(self):
        assert DEPLOY_MODE_MAP[HardwareTier.PHANTOM] == DeployMode.PROCESS

    def test_minimum_maps_to_process(self):
        assert DEPLOY_MODE_MAP[HardwareTier.MINIMUM] == DeployMode.PROCESS

    def test_recommended_maps_to_docker(self):
        assert DEPLOY_MODE_MAP[HardwareTier.RECOMMENDED] == DeployMode.DOCKER

    def test_comfortable_maps_to_docker(self):
        assert DEPLOY_MODE_MAP[HardwareTier.COMFORTABLE] == DeployMode.DOCKER

    def test_flagship_maps_to_integration(self):
        assert DEPLOY_MODE_MAP[HardwareTier.FLAGSHIP] == DeployMode.INTEGRATION

    def test_deploy_mode_values(self):
        assert DeployMode.PROCESS.value == "process"
        assert DeployMode.DOCKER.value == "docker"
        assert DeployMode.INTEGRATION.value == "integration"


class TestFeatureFlagsDocker:
    def test_phantom_no_docker(self):
        flags = compute_feature_flags(HardwareTier.PHANTOM)
        assert flags.deploy_mode == "process"
        assert flags.docker_enabled is False
        assert flags.docker_services == []

    def test_minimum_no_docker(self):
        flags = compute_feature_flags(HardwareTier.MINIMUM)
        assert flags.deploy_mode == "process"
        assert flags.docker_enabled is False
        assert flags.docker_services == []

    def test_recommended_has_docker(self):
        flags = compute_feature_flags(HardwareTier.RECOMMENDED)
        assert flags.deploy_mode == "docker"
        assert flags.docker_enabled is True
        assert "web" in flags.docker_services
        assert "llm" in flags.docker_services
        assert "rag" in flags.docker_services
        assert "kiwix" in flags.docker_services

    def test_comfortable_has_docker(self):
        flags = compute_feature_flags(HardwareTier.COMFORTABLE)
        assert flags.deploy_mode == "docker"
        assert flags.docker_enabled is True

    def test_flagship_has_integration(self):
        flags = compute_feature_flags(HardwareTier.FLAGSHIP)
        assert flags.deploy_mode == "integration"
        assert flags.docker_enabled is True

    def test_docker_services_includes_web(self):
        for tier in [HardwareTier.RECOMMENDED, HardwareTier.COMFORTABLE, HardwareTier.FLAGSHIP]:
            flags = compute_feature_flags(tier)
            assert "web" in flags.docker_services

    def test_docker_services_includes_llm_when_enabled(self):
        flags = compute_feature_flags(HardwareTier.RECOMMENDED)
        assert flags.llm is True
        assert "llm" in flags.docker_services

    def test_docker_services_includes_rag_when_enabled(self):
        flags = compute_feature_flags(HardwareTier.RECOMMENDED)
        assert flags.vector_rag is True
        assert "rag" in flags.docker_services


class TestHardwareProfileDeployMode:
    def test_profile_has_deploy_mode(self):
        profile = HardwareProfile()
        assert hasattr(profile, "deploy_mode")
        assert profile.deploy_mode == DeployMode.PROCESS

    @patch("allspark.infrastructure.hardware._detect_ram")
    @patch("allspark.infrastructure.hardware._detect_storage")
    @patch("allspark.infrastructure.hardware._detect_gpu")
    def test_detect_sets_deploy_mode(self, mock_gpu, mock_storage, mock_ram):
        mock_ram.return_value = None
        mock_storage.return_value = None
        mock_gpu.return_value = None
        profile = HardwareProfile()
        profile.ram_total_gb = 16.0
        profile.storage_available_gb = 128.0
        profile.os_name = "Linux"
        profile.os_version = "5.15"
        profile.hostname = "test"
        profile.cpu_arch = "x86_64"
        profile.cpu_model = "Test CPU"
        profile.cpu_cores = 8
        profile.gpu_available = False
        profile.gpu_info = "None"
        mock_ram.side_effect = lambda p: setattr(p, "ram_total_gb", 16.0) or setattr(p, "ram_available_gb", 10.0)
        mock_storage.side_effect = lambda p: setattr(p, "storage_total_gb", 256.0) or setattr(p, "storage_available_gb", 128.0)
        mock_gpu.side_effect = lambda p: None
        result = detect_hardware()
        assert result.deploy_mode == DeployMode.DOCKER


class TestFormatHardwareReport:
    def test_zh_report_includes_deploy_mode(self):
        profile = HardwareProfile(
            tier=HardwareTier.RECOMMENDED,
            ram_total_gb=8.0,
            ram_available_gb=5.0,
            storage_total_gb=128.0,
            storage_available_gb=64.0,
            cpu_model="Test",
            cpu_cores=4,
            cpu_arch="x86_64",
            os_name="Linux",
            os_version="5.15",
            gpu_info="None",
        )
        flags = compute_feature_flags(HardwareTier.RECOMMENDED)
        set_language("zh")
        report = format_hardware_report(profile, flags, lang="zh")
        assert "部署模式" in report
        assert "Docker" in report

    def test_en_report_includes_deploy_mode(self):
        profile = HardwareProfile(
            tier=HardwareTier.RECOMMENDED,
            ram_total_gb=8.0,
            ram_available_gb=5.0,
            storage_total_gb=128.0,
            storage_available_gb=64.0,
            cpu_model="Test",
            cpu_cores=4,
            cpu_arch="x86_64",
            os_name="Linux",
            os_version="5.15",
            gpu_info="None",
        )
        flags = compute_feature_flags(HardwareTier.RECOMMENDED)
        report = format_hardware_report(profile, flags, lang="en")
        assert "Deployment Mode" in report
        assert "Docker" in report

    def test_process_mode_report(self):
        profile = HardwareProfile(
            tier=HardwareTier.MINIMUM,
            ram_total_gb=4.0,
            ram_available_gb=2.0,
            storage_total_gb=64.0,
            storage_available_gb=32.0,
            cpu_model="Test",
            cpu_cores=2,
            cpu_arch="x86_64",
            os_name="Linux",
            os_version="5.15",
            gpu_info="None",
        )
        flags = compute_feature_flags(HardwareTier.MINIMUM)
        report = format_hardware_report(profile, flags, lang="zh")
        assert "进程模式" in report


class TestDockerManager:
    def _make_manager(self, db, tier=HardwareTier.RECOMMENDED):
        flags = compute_feature_flags(tier)
        deploy_mode = DEPLOY_MODE_MAP.get(tier, DeployMode.PROCESS)
        return DockerManager(db=db, flags=flags, deploy_mode=deploy_mode)

    @patch("subprocess.run")
    def test_is_docker_available_true(self, mock_run, db):
        mock_run.return_value = MagicMock(returncode=0)
        mgr = self._make_manager(db)
        assert mgr.is_docker_available() is True

    @patch("subprocess.run")
    def test_is_docker_available_false(self, mock_run, db):
        mock_run.side_effect = FileNotFoundError()
        mgr = self._make_manager(db)
        assert mgr.is_docker_available() is False

    @patch("subprocess.run")
    def test_is_docker_available_timeout(self, mock_run, db):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="docker", timeout=10)
        mgr = self._make_manager(db)
        assert mgr.is_docker_available() is False

    def test_is_docker_available_caches(self, db):
        mgr = self._make_manager(db)
        mgr._docker_available = True
        assert mgr.is_docker_available() is True

    @patch("subprocess.run")
    def test_get_status_docker_unavailable(self, mock_run, db):
        mock_run.side_effect = FileNotFoundError()
        mgr = self._make_manager(db)
        status = mgr.get_status()
        assert status["docker_available"] is False
        assert status["deploy_mode"] == "docker"

    @patch("subprocess.run")
    def test_get_status_docker_available(self, mock_run, db):
        mock_run.return_value = MagicMock(returncode=0, stdout="true\n")
        mgr = self._make_manager(db)
        mgr._docker_available = True
        status = mgr.get_status()
        assert status["docker_available"] is True
        assert "services" in status

    @patch("subprocess.run")
    def test_start_service_docker_unavailable(self, mock_run, db):
        mock_run.side_effect = FileNotFoundError()
        mgr = self._make_manager(db)
        result = mgr.start_service("web")
        assert result["status"] == "error"

    def test_start_service_unknown(self, db):
        mgr = self._make_manager(db)
        mgr._docker_available = True
        result = mgr.start_service("nonexistent")
        assert result["status"] == "error"

    @patch("subprocess.run")
    def test_start_service_success(self, mock_run, db):
        mock_run.return_value = MagicMock(returncode=0)
        mgr = self._make_manager(db)
        mgr._docker_available = True
        result = mgr.start_service("web")
        assert result["status"] == "ok"
        assert result["action"] == "started"

    @patch("subprocess.run")
    def test_stop_service_success(self, mock_run, db):
        mock_run.return_value = MagicMock(returncode=0)
        mgr = self._make_manager(db)
        mgr._docker_available = True
        result = mgr.stop_service("web")
        assert result["status"] == "ok"

    @patch("subprocess.run")
    def test_start_all(self, mock_run, db):
        mock_run.return_value = MagicMock(returncode=0)
        mgr = self._make_manager(db)
        mgr._docker_available = True
        result = mgr.start_all()
        assert result["status"] == "ok"

    @patch("subprocess.run")
    def test_stop_all(self, mock_run, db):
        mock_run.return_value = MagicMock(returncode=0)
        mgr = self._make_manager(db)
        mgr._docker_available = True
        result = mgr.stop_all()
        assert result["status"] == "ok"

    @patch("subprocess.run")
    def test_migrate_to_docker(self, mock_run, db):
        mock_run.return_value = MagicMock(returncode=0)
        mgr = self._make_manager(db)
        mgr._docker_available = True
        result = mgr.migrate_to_docker()
        assert result["status"] == "ok"

    @patch("subprocess.run")
    def test_migrate_to_docker_unavailable(self, mock_run, db):
        mock_run.side_effect = FileNotFoundError()
        mgr = self._make_manager(db)
        result = mgr.migrate_to_docker()
        assert result["status"] == "error"

    @patch("subprocess.run")
    def test_migrate_to_process(self, mock_run, db):
        mock_run.return_value = MagicMock(returncode=0)
        mgr = self._make_manager(db)
        mgr._docker_available = True
        result = mgr.migrate_to_process()
        assert result["status"] == "ok"
        assert result["deploy_mode"] == "process"
        assert mgr.flags.docker_enabled is False
        assert mgr.flags.docker_services == []

    @patch("subprocess.run")
    def test_get_logs(self, mock_run, db):
        mock_run.return_value = MagicMock(stdout="log line 1\n", stderr="")
        mgr = self._make_manager(db)
        mgr._docker_available = True
        logs = mgr.get_logs("web", lines=10)
        assert "log line 1" in logs

    def test_get_logs_unknown_service(self, db):
        mgr = self._make_manager(db)
        result = mgr.get_logs("nonexistent")
        assert "nonexistent" in result or "error" in result.lower() or "未知" in result

    @patch("subprocess.run")
    def test_reset(self, mock_run, db):
        mock_run.return_value = MagicMock(returncode=0)
        mgr = self._make_manager(db)
        mgr._docker_available = True
        result = mgr.reset()
        assert result["status"] == "ok"
        assert result["action"] == "reset"
        assert mgr.flags.deploy_mode == "process"
        assert mgr.flags.docker_enabled is False

    @patch("subprocess.run")
    def test_reset_docker_unavailable(self, mock_run, db):
        mock_run.side_effect = FileNotFoundError()
        mgr = self._make_manager(db)
        mgr._docker_available = False
        result = mgr.reset()
        assert result["status"] == "ok"


class TestDockerManagerProcessMode:
    def test_process_mode_no_docker(self, db):
        flags = compute_feature_flags(HardwareTier.MINIMUM)
        mgr = DockerManager(db=db, flags=flags, deploy_mode=DeployMode.PROCESS)
        assert mgr.deploy_mode == DeployMode.PROCESS
        assert mgr.flags.docker_enabled is False


class TestResetManagerDockerIntegration:
    @patch("subprocess.run")
    def test_factory_reset_stops_docker(self, mock_run, db):
        mock_run.return_value = MagicMock(returncode=0)
        flags = compute_feature_flags(HardwareTier.RECOMMENDED)
        docker_mgr = DockerManager(db=db, flags=flags, deploy_mode=DeployMode.DOCKER)
        docker_mgr._docker_available = True

        rm = ResetManager(db=db, docker_manager=docker_mgr)
        rm.execute_reset(ResetLevel.FACTORY, force=True)

        assert mock_run.called

    def test_factory_reset_without_docker(self, db):
        rm = ResetManager(db=db, docker_manager=None)
        result = rm.execute_reset(ResetLevel.FACTORY, force=True)
        assert result["status"] == "ok"


class TestDockerI18n:
    def test_zh_docker_keys_exist(self):
        set_language("zh")
        assert t("deploy_mode_process") == "进程模式"
        assert t("deploy_mode_docker") == "Docker 模式"
        assert t("deploy_mode_integration") == "集成模式（Docker + NOMAD）"
        assert t("docker_not_available") == "Docker 不可用"
        assert t("docker_not_configured") == "Docker 未配置，当前为进程模式"
        assert t("docker_state_running") == "运行中"
        assert t("docker_state_stopped") == "已停止"
        assert t("docker_start_ok") == "服务启动成功"
        assert t("docker_stop_ok") == "服务已停止"
        assert t("docker_process_mode_hint") == "当前为进程模式，所有服务原生运行"

    def test_en_docker_keys_exist(self):
        set_language("en")
        assert t("deploy_mode_process") == "Process Mode"
        assert t("deploy_mode_docker") == "Docker Mode"
        assert t("deploy_mode_integration") == "Integration Mode (Docker + NOMAD)"
        assert t("docker_not_available") == "Docker is not available"
        assert t("docker_not_configured") == "Docker not configured, running in process mode"
        assert t("docker_state_running") == "Running"
        assert t("docker_state_stopped") == "Stopped"
        assert t("docker_start_ok") == "Service started successfully"
        assert t("docker_stop_ok") == "Service stopped"
        assert t("docker_process_mode_hint") == "Running in process mode, all services run natively"

    def test_docker_i18n_key_parity(self):
        from allspark.core.i18n import MESSAGES
        zh_keys = set(MESSAGES["zh"].keys())
        en_keys = set(MESSAGES["en"].keys())
        docker_zh = {k for k in zh_keys if k.startswith("docker_") or k.startswith("deploy_")}
        docker_en = {k for k in en_keys if k.startswith("docker_") or k.startswith("deploy_")}
        assert docker_zh == docker_en, f"Missing keys: zh-only={docker_zh - docker_en}, en-only={docker_en - docker_zh}"


class TestDockerServicesConfig:
    def test_all_services_have_required_fields(self):
        for name, info in _DOCKER_SERVICES.items():
            assert "container" in info, f"Service {name} missing 'container'"
            assert "port" in info, f"Service {name} missing 'port'"
            assert "requires_flag" in info, f"Service {name} missing 'requires_flag'"

    def test_service_names(self):
        assert "llm" in _DOCKER_SERVICES
        assert "rag" in _DOCKER_SERVICES
        assert "web" in _DOCKER_SERVICES
        assert "kiwix" in _DOCKER_SERVICES

    def test_service_ports(self):
        assert _DOCKER_SERVICES["llm"]["port"] == 11434
        assert _DOCKER_SERVICES["rag"]["port"] == 6333
        assert _DOCKER_SERVICES["web"]["port"] == 8080
        assert _DOCKER_SERVICES["kiwix"]["port"] == 8081


class TestBootstrapDockerIntegration:
    def test_process_mode_skips_docker(self, db):
        from allspark.bootstrap import ApplicationBootstrap
        flags = FeatureFlags()
        flags.docker_enabled = False
        flags.deploy_mode = "process"
        bootstrap = ApplicationBootstrap(db, flags=flags)
        container = bootstrap.bootstrap()
        assert container.get("docker_manager") is None

    @patch("subprocess.run")
    def test_docker_mode_registers_manager(self, mock_run, db):
        mock_run.side_effect = FileNotFoundError()
        from allspark.bootstrap import ApplicationBootstrap
        flags = FeatureFlags()
        flags.docker_enabled = True
        flags.deploy_mode = "docker"
        flags.docker_services = ["web"]
        flags.llm = True
        flags.vector_rag = True
        flags.kiwix = True
        flags.web_ui = True
        bootstrap = ApplicationBootstrap(db, flags=flags)
        bootstrap.bootstrap()
        assert flags.deploy_mode == "process"
        assert flags.docker_enabled is False

    @patch("subprocess.run")
    def test_docker_available_registers_manager(self, mock_run, db):
        mock_run.return_value = MagicMock(returncode=0)
        from allspark.bootstrap import ApplicationBootstrap
        flags = FeatureFlags()
        flags.docker_enabled = True
        flags.deploy_mode = "docker"
        flags.docker_services = ["web"]
        flags.llm = True
        flags.vector_rag = True
        flags.kiwix = True
        flags.web_ui = True
        bootstrap = ApplicationBootstrap(db, flags=flags)
        container = bootstrap.bootstrap()
        docker_mgr = container.get("docker_manager")
        assert docker_mgr is not None
