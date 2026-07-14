"""SHA-196: real-Chrome stored-XSS regression for the public SKF import path."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
import uvicorn
from websockets.sync.client import connect

from allspark.adapters.routes import skf as skf_routes
from allspark.adapters.web_ui import create_app
from allspark.core.database import Database
from allspark.core.models import KnowledgeEntry
from allspark.services.skf_manager import SKFPackage, _sanitize_kf_field


def _chrome_binary() -> str:
    candidates = [
        os.environ.get("CHROME_BIN", ""),
        shutil.which("google-chrome") or "",
        shutil.which("google-chrome-stable") or "",
        shutil.which("chromium") or "",
        shutil.which("chromium-browser") or "",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    if os.environ.get("CI"):
        pytest.fail("Chrome is required for the SHA-196 browser security gate in CI")
    pytest.skip("Chrome is required for the SHA-196 browser security gate")


@contextmanager
def _serve(app: Any) -> Iterator[str]:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="error",
            ws="none",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(200):
            try:
                urllib.request.urlopen(f"{base_url}/api/system/health", timeout=0.2)
                break
            except (OSError, urllib.error.URLError):
                time.sleep(0.05)
        else:
            raise AssertionError("AllSpark browser-test server did not start")
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        assert not thread.is_alive(), "AllSpark browser-test server did not stop"


class _Chrome:
    def __init__(self, binary: str, profile: Path):
        self.binary = binary
        self.profile = profile
        self.process: subprocess.Popen[bytes] | None = None
        self.ws: Any = None
        self._request_id = 0

    def __enter__(self) -> _Chrome:
        self.process = subprocess.Popen(
            [
                self.binary,
                "--headless=new",
                "--disable-background-networking",
                "--disable-component-update",
                "--disable-default-apps",
                "--disable-dev-shm-usage",
                "--disable-extensions",
                "--disable-gpu",
                "--no-default-browser-check",
                "--no-first-run",
                f"--user-data-dir={self.profile}",
                "--remote-debugging-port=0",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        active_port = self.profile / "DevToolsActivePort"
        for _ in range(600):
            if active_port.exists():
                break
            if self.process.poll() is not None:
                raise AssertionError("Chrome exited before DevTools became available")
            time.sleep(0.05)
        else:
            self._stop_process()
            raise AssertionError("Chrome DevTools did not become available")

        port = active_port.read_text(encoding="utf-8").splitlines()[0]
        targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
        page = next(target for target in targets if target["type"] == "page")
        self.ws = connect(page["webSocketDebuggerUrl"], open_timeout=5, max_size=None)
        self.call("Page.enable")
        self.call("Runtime.enable")
        return self

    def __exit__(self, *_args: object) -> None:
        if self.ws is not None:
            self.ws.close()
        self._stop_process()

    def _stop_process(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._request_id += 1
        request_id = self._request_id
        self.ws.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
        while True:
            message = json.loads(self.ws.recv(timeout=10))
            if message.get("id") == request_id:
                if "error" in message:
                    raise AssertionError(f"Chrome DevTools error: {message['error']}")
                return message

    def evaluate(self, expression: str, *, await_promise: bool = False) -> Any:
        message = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": await_promise,
            },
        )
        result = message["result"]
        if "exceptionDetails" in result:
            details = result["exceptionDetails"]
            description = details.get("exception", {}).get("description")
            raise AssertionError(description or details.get("text", "JavaScript failed"))
        return result["result"].get("value")

    def navigate(self, url: str) -> None:
        self.call("Page.navigate", {"url": url})
        self.wait_for("document.readyState === 'complete'")

    def wait_for(self, expression: str, timeout: float = 10) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.evaluate(expression):
                return
            time.sleep(0.05)
        raise AssertionError(f"Browser condition timed out: {expression}")


def _post(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, method="POST")
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def _invalid_priority_skf(path: Path) -> None:
    manifest = {"skf": {"version": "1.0", "spark_id": "bad-priority", "created": "now"}}
    knowledge = [
        {
            "id": "priority-probe",
            "category": "security",
            "subcategory": "browser",
            "priority": '<img id="priority-probe" onerror="alert(1)">',
            "title": "invalid priority",
            "content": {"summary": "must be rejected"},
        }
    ]
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("knowledge.json", json.dumps(knowledge))


def test_public_skf_import_is_inert_in_repository_and_dashboard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = "PWNED_BROWSER_SENTINEL"
    raw_id = f'<img id="audit-xss-probe" src=x onerror="document.title=\'{sentinel}\'">'
    raw_category = f'<svg id="category-probe" onload="document.title=\'{sentinel}\'"></svg>'
    raw_subcategory = f'"><script>document.title="{sentinel}"</script>'
    raw_verification = '<b id="verification-probe">unverified</b>'

    safe_dir = tmp_path / "skf"
    safe_dir.mkdir()
    monkeypatch.setattr(skf_routes, "_SAFE_SKF_DIR", safe_dir)
    db_path = tmp_path / "browser.db"
    database = Database(db_path)
    database.mark_initialized()
    database.close()

    package = SKFPackage()
    package.spark_id = "browser-xss"
    package.created = "2026-07-14T00:00:00Z"
    package.knowledge_entries = [
        KnowledgeEntry(
            id=raw_id,
            category=raw_category,
            subcategory=raw_subcategory,
            priority=1,
            title=f'<img id="title-probe" src=x onerror="document.title=\'{sentinel}\'">',
            summary=f'<svg id="summary-probe" onload="document.title=\'{sentinel}\'"></svg>',
            steps=[f'<img id="step-probe" src=x onerror="document.title=\'{sentinel}\'">'],
            prerequisites=[],
            warnings=[f'<svg id="warning-probe" onload="document.title=\'{sentinel}\'"></svg>'],
            verification=raw_verification,
            source='<img id="source-probe" src=x>',
            language="zh",
        )
    ]
    package_path = safe_dir / "malicious.skf"
    package.export_to_file(str(package_path))
    bad_priority_path = safe_dir / "bad-priority.skf"
    _invalid_priority_skf(bad_priority_path)

    safe_id = _sanitize_kf_field(raw_id, "id")
    safe_category = _sanitize_kf_field(raw_category, "category")
    app = create_app(str(db_path))
    with _serve(app) as base_url:
        imported = _post(
            f"{base_url}/api/skf/import?path="
            f"{urllib.parse.quote(str(package_path), safe='')}&verify=true"
        )
        assert imported["status"] == "ok"
        assert imported["imported"]["knowledge"] == 1

        with pytest.raises(urllib.error.HTTPError) as invalid:
            _post(
                f"{base_url}/api/skf/import?path="
                f"{urllib.parse.quote(str(bad_priority_path), safe='')}&verify=true"
            )
        assert invalid.value.code == 400

        detail_url = f"{base_url}/api/knowledge/{urllib.parse.quote(safe_id, safe='')}"
        with urllib.request.urlopen(detail_url, timeout=10) as response:
            detail = json.load(response)
        assert detail["id"] == safe_id
        assert detail["category"] == safe_category
        assert detail["source"] == "other_spark"

        hierarchical_id = "survival/water/purification/boiling"
        hierarchical_url = (
            f"{base_url}/api/knowledge/{urllib.parse.quote(hierarchical_id, safe='')}"
        )
        with urllib.request.urlopen(hierarchical_url, timeout=10) as response:
            hierarchical_detail = json.load(response)
        assert hierarchical_detail["id"] == hierarchical_id

        with _Chrome(_chrome_binary(), tmp_path / "chrome-profile") as browser:
            browser.navigate(f"{base_url}/repository")
            browser.evaluate("initialRepositoryLoad", await_promise=True)
            assert browser.evaluate(
                f"_repoEntries.some(entry => entry.id === {json.dumps(safe_id)})"
            )
            browser.evaluate(
                f"_repoFilters.category = {json.dumps(safe_category)}; "
                "_repoFilters.lang = 'all'; _repoPage = 1; _repoRender();"
            )
            browser.wait_for(
                f"Array.from(document.querySelectorAll('tr[data-kid]'))"
                f".some(row => row.dataset.kid === {json.dumps(safe_id)})"
            )
            repo_state = browser.evaluate(
                "({title: document.title, probes: document.querySelectorAll("
                "'#audit-xss-probe,#category-probe,#verification-probe,#title-probe').length, "
                f"row: Array.from(document.querySelectorAll('tr[data-kid]')).find("
                f"row => row.dataset.kid === {json.dumps(safe_id)}).outerHTML}})"
            )
            assert repo_state["title"] != sentinel
            assert repo_state["probes"] == 0
            assert "&lt;img" in repo_state["row"]

            browser.evaluate(
                f"openRepoDetail({json.dumps(safe_id)})", await_promise=True
            )
            browser.wait_for("document.querySelector('#repo-detail-modal .card') !== null")
            repo_detail = browser.evaluate(
                "({title: document.title, probes: document.querySelectorAll("
                "'#audit-xss-probe,#category-probe,#verification-probe,#title-probe,"
                "#summary-probe,#step-probe,#warning-probe,#source-probe').length, "
                "html: document.querySelector('#repo-detail-modal').innerHTML})"
            )
            assert repo_detail["title"] != sentinel
            assert repo_detail["probes"] == 0
            assert "&lt;img" in repo_detail["html"]
            assert "&lt;svg" in repo_detail["html"]

            browser.navigate(f"{base_url}/?q={sentinel}")
            browser.wait_for("document.querySelector('.kb-entry') !== null")
            dashboard_state = browser.evaluate(
                "({title: document.title, probes: document.querySelectorAll("
                "'#audit-xss-probe,#category-probe,#title-probe,#summary-probe').length, "
                "html: document.querySelector('#knowledge-results').innerHTML})"
            )
            assert dashboard_state["title"] != sentinel
            assert dashboard_state["probes"] == 0
            assert "&lt;img" in dashboard_state["html"]

            browser.evaluate(f"showKnowledge({json.dumps(safe_id)})", await_promise=True)
            browser.wait_for("document.querySelector('#knowledge-detail .kb-detail') !== null")
            dashboard_detail = browser.evaluate(
                "({title: document.title, probes: document.querySelectorAll("
                "'#audit-xss-probe,#category-probe,#verification-probe,#title-probe,"
                "#summary-probe,#step-probe,#warning-probe,#source-probe').length, "
                "html: document.querySelector('#knowledge-detail').innerHTML})"
            )
            assert dashboard_detail["title"] != sentinel
            assert dashboard_detail["probes"] == 0
            assert "&lt;img" in dashboard_detail["html"]
            assert "&lt;svg" in dashboard_detail["html"]
