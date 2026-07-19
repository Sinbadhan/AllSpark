"""Repository and Execution Center robustness contracts from the 2026-07-20 audit."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_web_ui_v11 import _client

ROOT = Path(__file__).parents[1]
REPOSITORY = ROOT / "allspark" / "templates" / "repository.html"
EXECUTIONS = ROOT / "allspark" / "templates" / "executions.html"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _between(source: str, start: str, end: str) -> str:
    return source[source.index(start) : source.index(end, source.index(start))]


def test_workspace_pages_render_without_launching_a_browser(tmp_path: Path) -> None:
    client = _client(str(tmp_path / "workspace-contracts.db"))

    assert client.get("/repository").status_code == 200
    assert client.get("/executions").status_code == 200


def test_rendered_workspace_scripts_pass_node_syntax_check(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI"):
            pytest.fail("Node.js is required for the workspace JavaScript syntax gate")
        pytest.skip("Node.js is required for the workspace JavaScript syntax gate")

    client = _client(str(tmp_path / "workspace-syntax.db"))
    for route, marker in (
        ("/repository", "const REPO_I18N"),
        ("/executions", "const TASK_I18N"),
    ):
        html = client.get(route).text
        script = next(
            block
            for block in re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL)
            if marker in block
        )
        script_path = tmp_path / f"{route.removeprefix('/')}.js"
        script_path.write_text(script, encoding="utf-8")
        result = subprocess.run(
            [node, "--check", str(script_path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr


def test_repository_failure_empty_and_retry_states_are_distinct() -> None:
    source = _source(REPOSITORY)
    loader = _between(source, "async function loadKnowledgeTable", "function _repoRender")

    assert 'cats?._http_error || !Array.isArray(cats)' in loader
    assert loader.index('cats?._http_error || !Array.isArray(cats)') < loader.index(
        "if (!cats.length)"
    )
    assert 'entries?._http_error || !Array.isArray(entries)' in loader
    assert '_repoLoadFailure("retry-knowledge")' in loader
    assert 'data-repo-action="retry-knowledge"' not in loader
    assert 'action === "retry-knowledge"' in source


def test_repository_detail_failure_is_retryable_and_modal_uses_inert_manager() -> None:
    source = _source(REPOSITORY)
    detail = _between(source, "async function openRepoDetail", "async function loadExperienceTable")

    assert 'e?._http_error || !e || typeof e !== "object" || !e.id' in detail
    assert 'data-repo-action="retry-detail"' in detail
    assert 'action === "retry-detail"' in source
    assert "modalBackgroundManager.activate(modal, modal._previouslyFocused)" in detail
    assert "modalBackgroundManager.deactivate(m, previous)" in detail


def test_repository_experimental_entries_are_explicit() -> None:
    source = _source(REPOSITORY)

    assert source.count("{{ t('web_release_experimental') }}") >= 5
    assert 'data-section="experience"' in source
    assert 'data-section="models"' in source
    assert '_repoLoadFailure("retry-section", "experience")' in source
    assert '_repoLoadFailure("retry-section", "models")' in source


def test_execution_core_and_auxiliary_loads_have_independent_failure_states() -> None:
    source = _source(EXECUTIONS)
    refresh = _between(
        source,
        "async function refreshExecutions",
        "async function refreshExecutionExperiences",
    )
    auxiliary = _between(
        source,
        "async function refreshExecutionExperiences",
        "function toggleExecDetail",
    )

    assert 'tasks?._http_error || !Array.isArray(tasks)' in refresh
    assert "container.innerHTML = tasks.map" in refresh
    assert "applyExecutionSearch();" in refresh
    assert "await refreshExecutionExperiences();" in refresh
    assert 'experiences?._http_error || !Array.isArray(experiences)' in auxiliary
    assert 'id="exec-experience-error"' in auxiliary
    assert 'data-exec-action="retry-experience"' in auxiliary
    assert 'action === "retry-experience"' in source


def test_goal_writes_check_http_success_before_clearing_or_refreshing() -> None:
    source = _source(EXECUTIONS)
    add_goal = _between(source, "async function addGoal", "async function completeGoal")
    complete_goal = _between(
        source, "async function completeGoal", "/* === Timeline === */"
    )

    assert "if (!response.ok)" in add_goal
    assert add_goal.index("if (!response.ok)") < add_goal.index('input.value = ""')
    assert add_goal.index('input.value = ""') < add_goal.index("await refreshGoals()")
    assert "if (!response.ok)" in complete_goal
    assert complete_goal.index("if (!response.ok)") < complete_goal.index(
        "await refreshGoals()"
    )


def test_execution_search_filters_tasks_and_goals_with_accessible_feedback() -> None:
    source = _source(EXECUTIONS)
    search = _between(source, "function applyExecutionSearch", "refreshExecutions();")

    assert 'data-exec-search-item="task"' in source
    assert 'data-exec-search-item="goal"' in source
    assert 'item.dataset.execSearchText || ""' in search
    assert 'EXEC_I18N.search_results.replace("{n}", String(visible))' in search
    assert "empty.hidden = !query || visible > 0" in search
    assert 'document.getElementById("exec-search").addEventListener("input"' in source
    assert 'event.key !== "Escape"' in source
    assert 'event.currentTarget.value = ""' in source


def test_task_outcome_modal_uses_global_inert_manager() -> None:
    source = _source(EXECUTIONS)
    modal = _between(source, "function openTaskOutcome", "async function saveTaskOutcome")

    assert "window.setModalBackgroundInert(true)" in modal
    assert "window.setModalBackgroundInert(false)" in modal


def test_new_translation_keys_are_bounded_to_workspace_error_copy() -> None:
    combined = _source(REPOSITORY) + _source(EXECUTIONS)
    expected = {
        "web_repository_load_failed",
        "web_executions_load_failed",
        "web_executions_auxiliary_load_failed",
        "web_executions_search_results",
        "web_goals_write_failed",
    }

    for key in expected:
        assert f"t('{key}')" in combined
