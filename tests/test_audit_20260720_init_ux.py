"""Runtime contracts for the bounded 2026-07-20 first-run UX audit fixes."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

TEMPLATE = Path("allspark/templates/init.html")


def _function(source: str, name: str) -> str:
    prefixes = (f"function {name}(", f"async function {name}(")
    for line in source.splitlines():
        if line.startswith(prefixes):
            return line
    raise AssertionError(f"Could not extract JavaScript function {name}")


def _node_result(tmp_path: Path, name: str, script: str) -> dict[str, object]:
    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI"):
            pytest.fail("Node.js is required for the first-run UX runtime gate in CI")
        pytest.skip("Node.js is required for the first-run UX runtime gate")
    path = tmp_path / f"{name}.cjs"
    path.write_text(script, encoding="utf-8")
    result = subprocess.run(
        [node, str(path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return json.loads(result.stdout)


def test_template_exposes_truthful_boundary_step_status_and_bounded_defer() -> None:
    template = TEMPLATE.read_text(encoding="utf-8")

    assert '<ol class="progress" aria-hidden="true">' in template
    assert (
        'id="step-status" class="sr-only" role="status" '
        'aria-live="polite" aria-atomic="true"'
    ) in template
    assert "web_init_step_status" in template

    boundary = template.index('data-i18n="web_init_data_boundary_heading"')
    assert boundary < template.index('id="step-2"')
    assert 'data-i18n="web_init_data_boundary_body"' in template
    assert 'role="note"' in template
    assert "localStorage" not in template
    assert "sessionStorage" not in template

    assert 'data-action="defer-noncritical"' in template
    assert "['power','fire','storage']" in template
    assert "['water','food']" not in _function(template, "deferNonCriticalResources")


def test_step_status_announces_current_step_without_exposing_progress_bar(
    tmp_path: Path,
) -> None:
    source = TEMPLATE.read_text(encoding="utf-8")
    script = f"""
const status = {{textContent: ''}};
const $ = id => status;
const tr = key => key === 'web_init_step_status' ? 'Step {{step}} of {{total}}' : key;
let currentStep = 3;
{_function(source, "renderStepStatus")}
renderStepStatus();
process.stdout.write(JSON.stringify({{text: status.textContent}}));
"""

    assert _node_result(tmp_path, "step-status", script) == {"text": "Step 3 of 4"}


def test_preview_failure_retains_recovery_and_focuses_retryable_error(
    tmp_path: Path,
) -> None:
    source = TEMPLATE.read_text(encoding="utf-8")
    functions = "\n".join(
        _function(source, name)
        for name in ("clearDraftError", "showDraftError", "continueDraft")
    )
    script = f"""
function classList(hidden) {{
  const values = new Set(hidden ? ['hidden'] : []);
  return {{
    add: value => values.add(value),
    remove: value => values.delete(value),
    contains: value => values.has(value),
  }};
}}
const elements = {{
  'draft-error': {{classList: classList(true), focused: false, focus() {{ this.focused = true; }}}},
  'draft-error-message': {{textContent: ''}},
  'draft-recovery': {{classList: classList(false)}},
  'draft-save-status': {{textContent: 'unchanged'}},
  'assessment-confirmed': {{checked: true}},
}};
const $ = id => elements[id];
const tr = key => ({{
  web_init_draft_preview_failed: 'Preview failed. Review the saved draft and retry.',
  web_init_draft_resumed: 'Draft restored',
}})[key] || key;
let selectedLang = 'en';
let draftHydrating = false;
let draftRevision = 0;
let selectedPrimaryActionId = 'action-1';
let lastAssessment = null;
let lastSummary = null;
let lastPlan = null;
let showStepCalls = 0;
const draftRecord = {{
  revision: 7,
  payload: {{language: 'en', step: 4, assessment: {{health: {{status: 'unknown'}}}}, selected_primary_action_id: 'action-1'}},
}};
function selectLanguage(language) {{ selectedLang = language; }}
function hydrateAssessment() {{}}
function populateSummary() {{}}
function populatePlan() {{}}
function updateCompleteState() {{}}
function showStep() {{ showStepCalls += 1; }}
async function api() {{ const error = new Error('preview unavailable'); error.status = 503; throw error; }}
{functions}
(async () => {{
  await continueDraft();
  process.stdout.write(JSON.stringify({{
    recoveryHidden: elements['draft-recovery'].classList.contains('hidden'),
    errorHidden: elements['draft-error'].classList.contains('hidden'),
    errorFocused: elements['draft-error'].focused,
    errorMessage: elements['draft-error-message'].textContent,
    saveStatus: elements['draft-save-status'].textContent,
    draftHydrating,
    draftRevision,
    showStepCalls,
  }}));
}})().catch(error => {{ console.error(error); process.exit(1); }});
"""

    assert _node_result(tmp_path, "draft-preview-failure", script) == {
        "recoveryHidden": False,
        "errorHidden": False,
        "errorFocused": True,
        "errorMessage": "Preview failed. Review the saved draft and retry.",
        "saveStatus": "unchanged",
        "draftHydrating": False,
        "draftRevision": 7,
        "showStepCalls": 0,
    }


def test_delete_conflict_service_failure_and_transport_failure_keep_draft(
    tmp_path: Path,
) -> None:
    source = TEMPLATE.read_text(encoding="utf-8")
    functions = "\n".join(
        _function(source, name)
        for name in ("clearDraftError", "showDraftError", "discardDraft")
    )
    script = f"""
function classList(hidden) {{
  const values = new Set(hidden ? ['hidden'] : []);
  return {{
    add: value => values.add(value),
    remove: value => values.delete(value),
    contains: value => values.has(value),
  }};
}}
const elements = {{
  'draft-error': {{classList: classList(true), focused: false, focus() {{ this.focused = true; }}}},
  'draft-error-message': {{textContent: ''}},
  'draft-recovery': {{classList: classList(false)}},
  'draft-confirm': {{classList: classList(false)}},
  'draft-save-status': {{textContent: 'unchanged'}},
}};
const confirmButton = {{disabled: false}};
const document = {{
  querySelector(selector) {{
    if (selector === '[data-action="draft-discard-confirm"]') return confirmButton;
    throw new Error(`Unexpected selector: ${{selector}}`);
  }},
}};
const $ = id => elements[id];
const tr = key => key;
let draftRevision = 9;
let draftRecord = {{revision: 9}};
let failureStatus = 409;
async function api() {{
  const error = new Error('delete failed');
  if (failureStatus !== null) error.status = failureStatus;
  throw error;
}}
{functions}
async function run(status) {{
  failureStatus = status;
  draftRevision = 9;
  draftRecord = {{revision: 9}};
  confirmButton.disabled = false;
  elements['draft-error'].classList.add('hidden');
  elements['draft-error'].focused = false;
  elements['draft-recovery'].classList.remove('hidden');
  elements['draft-confirm'].classList.remove('hidden');
  elements['draft-save-status'].textContent = 'unchanged';
  const result = await discardDraft();
  return {{
    status,
    result,
    draftRevision,
    hasDraft: draftRecord !== null,
    recoveryHidden: elements['draft-recovery'].classList.contains('hidden'),
    confirmHidden: elements['draft-confirm'].classList.contains('hidden'),
    errorHidden: elements['draft-error'].classList.contains('hidden'),
    errorFocused: elements['draft-error'].focused,
    message: elements['draft-error-message'].textContent,
    buttonDisabled: confirmButton.disabled,
    saveStatus: elements['draft-save-status'].textContent,
  }};
}}
(async () => {{
  const results = [];
  for (const status of [409, 503, null]) results.push(await run(status));
  process.stdout.write(JSON.stringify({{results}}));
}})().catch(error => {{ console.error(error); process.exit(1); }});
"""

    result = _node_result(tmp_path, "draft-delete-failures", script)
    rows = result["results"]
    assert isinstance(rows, list)
    assert [row["message"] for row in rows] == [
        "web_init_draft_conflict",
        "web_init_draft_delete_failed",
        "web_init_draft_delete_failed",
    ]
    for row, status, message in zip(
        rows,
        (409, 503, None),
        (
            "web_init_draft_conflict",
            "web_init_draft_delete_failed",
            "web_init_draft_delete_failed",
        ),
        strict=True,
    ):
        assert row == {
            "status": status,
            "result": False,
            "draftRevision": 9,
            "hasDraft": True,
            "recoveryHidden": False,
            "confirmHidden": False,
            "errorHidden": False,
            "errorFocused": True,
            "message": message,
            "buttonDisabled": False,
            "saveStatus": "unchanged",
        }


def test_defer_sets_only_power_fire_and_storage_to_explicit_unknown(
    tmp_path: Path,
) -> None:
    source = TEMPLATE.read_text(encoding="utf-8")
    functions = "\n".join(
        _function(source, name)
        for name in ("setRadio", "deferNonCriticalResources")
    )
    script = rf"""
function classList() {{
  const values = new Set();
  return {{add: value => values.add(value), contains: value => values.has(value)}};
}}
const types = ['power', 'water', 'food', 'fire', 'storage'];
const radios = {{}};
for (const type of types) {{
  for (const dimension of ['amount', 'rate']) {{
    const name = `${{type}}-${{dimension}}-state`;
    for (const value of dimension === 'amount' ? ['known', 'unknown'] : ['estimate', 'unknown']) {{
      radios[`${{name}}:${{value}}`] = {{name, value, _checked: value === (dimension === 'amount' ? 'known' : 'estimate')}};
      Object.defineProperty(radios[`${{name}}:${{value}}`], 'checked', {{
        get() {{ return this._checked; }},
        set(next) {{
          if (next) Object.values(radios).filter(item => item.name === this.name).forEach(item => {{ item._checked = false; }});
          this._checked = next;
        }},
      }});
    }}
  }}
}}
const elements = {{'resource-defer-status': {{textContent: ''}}}};
for (const type of types) {{
  elements[`${{type}}-amount`] = {{value: `${{type}}-amount`}};
  elements[`${{type}}-consumption`] = {{value: `${{type}}-consumption`}};
  elements[`${{type}}-intake`] = {{value: `${{type}}-intake`}};
  elements[`${{type}}-confirm-outlier`] = {{checked: true}};
  elements[`${{type}}-outlier`] = {{classList: classList()}};
}}
const document = {{
  querySelector(selector) {{
    const match = selector.match(/^input\[name="([^"]+)"\]\[value="([^"]+)"\]$/);
    return match ? radios[`${{match[1]}}:${{match[2]}}`] : null;
  }},
}};
const $ = id => elements[id];
const tr = key => key === 'web_init_noncritical_deferred' ? 'Deferred' : key;
let syncCalls = 0;
let saveCalls = 0;
function syncDraftControls() {{ syncCalls += 1; }}
function scheduleDraftSave() {{ saveCalls += 1; }}
{functions}
deferNonCriticalResources();
const state = {{}};
for (const type of types) {{
  state[type] = {{
    amountKnown: radios[`${{type}}-amount-state:known`]._checked,
    amountUnknown: radios[`${{type}}-amount-state:unknown`]._checked,
    rateEstimate: radios[`${{type}}-rate-state:estimate`]._checked,
    rateUnknown: radios[`${{type}}-rate-state:unknown`]._checked,
    amount: elements[`${{type}}-amount`].value,
    consumption: elements[`${{type}}-consumption`].value,
    intake: elements[`${{type}}-intake`].value,
    confirmed: elements[`${{type}}-confirm-outlier`].checked,
    outlierHidden: elements[`${{type}}-outlier`].classList.contains('hidden'),
  }};
}}
process.stdout.write(JSON.stringify({{state, syncCalls, saveCalls, status: elements['resource-defer-status'].textContent}}));
"""

    result = _node_result(tmp_path, "defer-noncritical", script)
    deferred = {
        "amountKnown": False,
        "amountUnknown": True,
        "rateEstimate": False,
        "rateUnknown": True,
        "amount": "",
        "consumption": "",
        "intake": "",
        "confirmed": False,
        "outlierHidden": True,
    }
    assert result["state"]["power"] == deferred
    assert result["state"]["fire"] == deferred
    assert result["state"]["storage"] == deferred
    for resource in ("water", "food"):
        assert result["state"][resource] == {
            "amountKnown": True,
            "amountUnknown": False,
            "rateEstimate": True,
            "rateUnknown": False,
            "amount": f"{resource}-amount",
            "consumption": f"{resource}-consumption",
            "intake": f"{resource}-intake",
            "confirmed": True,
            "outlierHidden": False,
        }
    assert result["syncCalls"] == 1
    assert result["saveCalls"] == 1
    assert result["status"] == "Deferred"
