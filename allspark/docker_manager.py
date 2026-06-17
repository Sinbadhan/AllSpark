import logging
import subprocess
from pathlib import Path
from typing import Optional

from allspark.core.i18n import t
from allspark.infrastructure.hardware import DeployMode, FeatureFlags

logger = logging.getLogger(__name__)

_DOCKER_SERVICES: dict[str, dict[str, object]] = {
    "llm": {
        "container": "allspark-llm",
        "port": 11434,
        "requires_flag": "llm",
    },
    "rag": {
        "container": "allspark-rag",
        "port": 6333,
        "requires_flag": "vector_rag",
    },
    "web": {
        "container": "allspark-web",
        "port": 8080,
        "requires_flag": "web_ui",
    },
    "kiwix": {
        "container": "allspark-kiwix",
        "port": 8081,
        "requires_flag": "kiwix",
    },
}


class DockerManager:
    def __init__(self, db, flags: FeatureFlags, deploy_mode: DeployMode):
        self.db = db
        self.flags = flags
        self.deploy_mode = deploy_mode
        self._compose_path = Path(__file__).parent / "docker" / "docker-compose.yml"
        self._docker_available: Optional[bool] = None

    def is_docker_available(self) -> bool:
        if self._docker_available is not None:
            return self._docker_available
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True, text=True, timeout=10,
            )
            self._docker_available = result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self._docker_available = False
        return self._docker_available

    def get_status(self) -> dict:
        if not self.is_docker_available():
            return {
                "docker_available": False,
                "deploy_mode": self.deploy_mode.value,
                "services": {},
            }

        services = {}
        for name, info in _DOCKER_SERVICES.items():
            if not getattr(self.flags, str(info["requires_flag"]), False):
                continue
            container = str(info["container"])
            services[name] = {
                "container": container,
                "port": info["port"],
                "running": self._is_container_running(container),
            }

        return {
            "docker_available": True,
            "deploy_mode": self.deploy_mode.value,
            "services": services,
        }

    def start_service(self, service: str) -> dict:
        if not self.is_docker_available():
            return {"status": "error", "message": t("docker_not_available")}

        if service not in _DOCKER_SERVICES:
            return {"status": "error", "message": t("docker_unknown_service", service=service)}

        info = _DOCKER_SERVICES[service]
        if not getattr(self.flags, str(info["requires_flag"]), False):
            return {"status": "error", "message": t("docker_service_disabled", service=service)}

        try:
            result = subprocess.run(
                ["docker", "compose", "-f", str(self._compose_path),
                 "up", "-d", service],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
                return {"status": "ok", "service": service, "action": "started"}
            return {"status": "error", "message": result.stderr.strip()}
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            return {"status": "error", "message": str(e)}

    def stop_service(self, service: str) -> dict:
        if not self.is_docker_available():
            return {"status": "error", "message": t("docker_not_available")}

        if service not in _DOCKER_SERVICES:
            return {"status": "error", "message": t("docker_unknown_service", service=service)}

        try:
            result = subprocess.run(
                ["docker", "compose", "-f", str(self._compose_path),
                 "stop", service],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0:
                return {"status": "ok", "service": service, "action": "stopped"}
            return {"status": "error", "message": result.stderr.strip()}
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            return {"status": "error", "message": str(e)}

    def start_all(self) -> dict:
        if not self.is_docker_available():
            return {"status": "error", "message": t("docker_not_available")}

        results = {}
        for service in self.flags.docker_services:
            results[service] = self.start_service(service)
        return {"status": "ok", "services": results}

    def stop_all(self) -> dict:
        if not self.is_docker_available():
            return {"status": "error", "message": t("docker_not_available")}

        try:
            result = subprocess.run(
                ["docker", "compose", "-f", str(self._compose_path), "down"],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
                return {"status": "ok", "action": "all_stopped"}
            return {"status": "error", "message": result.stderr.strip()}
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            return {"status": "error", "message": str(e)}

    def migrate_to_docker(self) -> dict:
        if not self.is_docker_available():
            return {"status": "error", "message": t("docker_not_available")}

        if self.deploy_mode == DeployMode.DOCKER or self.deploy_mode == DeployMode.INTEGRATION:
            start_result = self.start_all()
            self._save_deploy_mode(self.deploy_mode.value)
            return {
                "status": "ok",
                "deploy_mode": self.deploy_mode.value,
                "services": start_result.get("services", {}),
            }

        return {"status": "error", "message": t("docker_hardware_insufficient")}

    def migrate_to_process(self) -> dict:
        stop_result = self.stop_all()
        self._save_deploy_mode("process")
        self.deploy_mode = DeployMode.PROCESS
        self.flags.deploy_mode = "process"
        self.flags.docker_enabled = False
        self.flags.docker_services = []
        return {
            "status": "ok",
            "deploy_mode": "process",
            "stop_result": stop_result,
        }

    def get_logs(self, service: str, lines: int = 50) -> str:
        if service not in _DOCKER_SERVICES:
            return t("docker_unknown_service", service=service)

        container = str(_DOCKER_SERVICES[service]["container"])
        try:
            result = subprocess.run(
                ["docker", "logs", "--tail", str(lines), container],
                capture_output=True, text=True, timeout=30,
            )
            return result.stdout + result.stderr
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            return str(e)

    def reset(self) -> dict:
        if not self.is_docker_available():
            return {"status": "ok", "message": t("docker_not_available")}

        try:
            subprocess.run(
                ["docker", "compose", "-f", str(self._compose_path), "down", "-v"],
                capture_output=True, text=True, timeout=120,
            )
            for name, info in _DOCKER_SERVICES.items():
                try:
                    subprocess.run(
                        ["docker", "rm", "-f", str(info["container"])],
                        capture_output=True, text=True, timeout=30,
                    )
                except Exception:
                    pass
            self._save_deploy_mode("process")
            self.deploy_mode = DeployMode.PROCESS
            self.flags.deploy_mode = "process"
            self.flags.docker_enabled = False
            self.flags.docker_services = []
            return {"status": "ok", "action": "reset"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _is_container_running(self, container_name: str) -> bool:
        try:
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
                capture_output=True, text=True, timeout=10,
            )
            return result.stdout.strip().lower() == "true"
        except Exception:
            return False

    def _save_deploy_mode(self, mode: str):
        try:
            self.db.conn.execute(
                "INSERT OR REPLACE INTO operating_state (key, value) VALUES (?, ?)",
                ("deploy_mode", mode),
            )
            self.db.conn.commit()
        except Exception as e:
            logger.warning(f"Failed to save deploy mode: {e}")

    def format_status_text(self) -> str:
        status = self.get_status()

        if not status["docker_available"]:
            return t("docker_not_available")

        deploy_names = {
            "process": t("deploy_mode_process"),
            "docker": t("deploy_mode_docker"),
            "integration": t("deploy_mode_integration"),
        }
        lines = [
            t("docker_status_header"),
            t("docker_deploy_mode", mode=deploy_names.get(status["deploy_mode"], status["deploy_mode"])),
        ]

        services = status.get("services", {})
        if not services:
            lines.append(t("docker_no_services"))
        else:
            for name, info in services.items():
                state = t("docker_state_running") if info["running"] else t("docker_state_stopped")
                lines.append(f"  {name}: {state} (:{info['port']})")

        return "\n".join(lines)
