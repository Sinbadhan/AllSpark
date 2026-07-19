"""Regression gates for the 2026-07-20 shell and dashboard audit."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

TEMPLATES = Path("allspark/templates")


def _template(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def _node_result(script: str, harness: str, tmp_path: Path, name: str) -> dict[str, object]:
    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI"):
            pytest.fail("Node.js is required for the shell JavaScript runtime gate in CI")
        pytest.skip("Node.js is required for the shell JavaScript runtime gate")

    path = tmp_path / f"{name}.cjs"
    path.write_text(harness.replace("__SCRIPT__", json.dumps(script)), encoding="utf-8")
    result = subprocess.run(
        [node, str(path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return json.loads(result.stdout)


def test_safe_error_message_keeps_actionable_fields_only(tmp_path: Path) -> None:
    source = _template("base.html")
    start = source.index("function _safeErrorPart")
    end = source.index("function notify", start)
    script = source[start:end]
    harness = r"""
const vm = require("node:vm");
const context = vm.createContext({I18N: {web_error_occurred: "Localized fallback"}});
vm.runInContext(__SCRIPT__, context);
const result = vm.runInContext(`({
  native: safeErrorMessage(Object.assign(new Error("Network down"), {
    detail: "Request failed",
    next_action: "Retry locally",
    stack: "do not expose",
  })),
  json: safeErrorMessage({
    detail: {message: "Invalid amount", private_context: "hidden"},
    next_action: "Review water",
  }),
  validation: safeErrorMessage({
    detail: [{msg: "Amount required"}, {message: "Unit required", stack: "hidden"}],
  }),
  controls: safeErrorMessage("Bad\\u0000  input"),
  fallback: safeErrorMessage({stack: "private stack"}),
})`, context);
process.stdout.write(JSON.stringify(result));
"""
    result = _node_result(script, harness, tmp_path, "safe-error-message")
    assert result == {
        "native": "Network down · Request failed · Retry locally",
        "json": "Invalid amount · Review water",
        "validation": "Amount required · Unit required",
        "controls": "Bad input",
        "fallback": "Localized fallback",
    }


def test_modal_background_manager_nests_and_restores_state(tmp_path: Path) -> None:
    source = _template("base.html")
    match = re.search(
        r"const modalBackgroundManager = \(\(\) => \{.*?\n\}\)\(\);",
        source,
        re.DOTALL,
    )
    assert match is not None
    harness = r"""
const vm = require("node:vm");
function element(name) {
  const attrs = new Set();
  return {
    name, attrs, parentElement: null, children: [], focusCount: 0,
    append(child) { child.parentElement = this; this.children.push(child); },
    hasAttribute(attr) { return attrs.has(attr); },
    setAttribute(attr) { attrs.add(attr); },
    removeAttribute(attr) { attrs.delete(attr); },
    contains(target) {
      return this === target || this.children.some(child => child.contains(target));
    },
    closest(selector) {
      let current = this;
      while (current) {
        if (selector === "[inert]" && current.hasAttribute("inert")) return current;
        current = current.parentElement;
      }
      return null;
    },
    focus() { this.focusCount += 1; },
  };
}
const body = element("body");
const background = element("background");
const trigger = element("trigger");
background.append(trigger);
const persistent = element("persistent");
persistent.setAttribute("inert");
const modalOne = element("modal-one");
const innerTrigger = element("inner-trigger");
modalOne.append(innerTrigger);
body.append(background);
body.append(persistent);
body.append(modalOne);
const document = {body, activeElement: trigger};
const context = vm.createContext({document});
vm.runInContext(__SCRIPT__, context);

const firstDepth = vm.runInContext("modalBackgroundManager.activate", context)(modalOne, trigger);
const firstIsolated = background.hasAttribute("inert");
const modalTwo = element("modal-two");
background.append(modalTwo);
const secondDepth = vm.runInContext("modalBackgroundManager.activate", context)(modalTwo, innerTrigger);
const firstModalIsolated = modalOne.hasAttribute("inert");
const nestedPathExposed = !background.hasAttribute("inert");
vm.runInContext("modalBackgroundManager.deactivate", context)(modalTwo);
const nestedRestored = !modalOne.hasAttribute("inert") && innerTrigger.focusCount === 1;
const remainingDepth = vm.runInContext("modalBackgroundManager.count", context);
vm.runInContext("modalBackgroundManager.deactivate", context)(modalOne);
process.stdout.write(JSON.stringify({
  firstDepth,
  secondDepth,
  remainingDepth,
  firstIsolated,
  firstModalIsolated,
  nestedPathExposed,
  nestedRestored,
  backgroundRestored: !background.hasAttribute("inert"),
  persistentPreserved: persistent.hasAttribute("inert"),
  triggerRestored: trigger.focusCount === 1,
}));
"""
    result = _node_result(match.group(0), harness, tmp_path, "modal-background")
    assert result == {
        "firstDepth": 1,
        "secondDepth": 2,
        "remainingDepth": 1,
        "firstIsolated": True,
        "firstModalIsolated": True,
        "nestedPathExposed": True,
        "nestedRestored": True,
        "backgroundRestored": True,
        "persistentPreserved": True,
        "triggerRestored": True,
    }


def test_resource_modal_and_cards_use_shell_accessibility_contract() -> None:
    source = _template("index.html")
    assert "modalBackgroundManager.activate(modal, modal._previouslyFocused)" in source
    assert "modalBackgroundManager.deactivate(m, fallbackCard)" in source
    assert "const resourceAria = [label, amountText, statusText, sourceText, remainingText" in source
    assert "aria-label=\"' + escHtml(resourceAria)" in source
    assert "aria-label=\"' + RES_I18N.edit_label" not in source


def test_briefing_and_experimental_entries_expose_state() -> None:
    source = _template("index.html")
    assert '<button type="button" style=' in source
    assert 'data-index-action="toggle-briefing" aria-expanded="false"' in source
    assert 'aria-controls="briefing-full"' in source
    assert 'trigger.setAttribute("aria-expanded", "true")' in source
    assert 'trigger.setAttribute("aria-expanded", "false")' in source
    assert source.count("{{ t('web_release_experimental') }}") >= 4
    assert "release-status-badge" in source
