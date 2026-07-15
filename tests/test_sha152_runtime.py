"""SHA-152: execute focus and mobile-navigation JavaScript against DOM stubs."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


def _node_result(script: str, harness: str, tmp_path: Path, name: str) -> dict[str, object]:
    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI"):
            pytest.fail("Node.js is required for the SHA-152 JavaScript runtime gate in CI")
        pytest.skip("Node.js is required for the SHA-152 JavaScript runtime gate")

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


def _function(source: str, name: str, next_marker: str) -> str:
    match = re.search(
        rf"(?:async )?function {name}\([^)]*\) \{{.*?(?={re.escape(next_marker)})",
        source,
        re.DOTALL,
    )
    assert match is not None, f"Could not extract {name}"
    return match.group(0).strip()


def test_mobile_nav_open_and_forced_close_restore_full_state(tmp_path: Path) -> None:
    source = Path("allspark/templates/base.html").read_text(encoding="utf-8")
    script = _function(source, "toggleMobileNav", "</script>")
    harness = r"""
const vm = require("node:vm");
function classList() {
  const values = new Set();
  return {
    contains: name => values.has(name),
    toggle(name, force) { force ? values.add(name) : values.delete(name); },
  };
}
function element() {
  return {
    attributes: {}, classList: classList(), inert: false, focused: false,
    setAttribute(name, value) { this.attributes[name] = String(value); },
    toggleAttribute(name, force) { if (name === "inert") this.inert = force; },
    addEventListener() {},
    querySelector() { return {focus() {}}; },
    querySelectorAll() { return []; },
    focus() { this.focused = true; },
  };
}
const overlay = element();
const toggle = element();
const backgrounds = [element(), element(), element(), element()];
const document = {
  activeElement: null,
  body: {contains: node => node === toggle},
  getElementById: id => id === "mobile-nav" ? overlay : toggle,
  querySelectorAll: () => backgrounds,
};
const context = vm.createContext({document});
vm.runInContext(__SCRIPT__, context);
vm.runInContext("toggleMobileNav(true)", context);
const opened = overlay.classList.contains("open")
  && toggle.attributes["aria-expanded"] === "true"
  && backgrounds.every(item => item.inert);
vm.runInContext("toggleMobileNav(false)", context);
process.stdout.write(JSON.stringify({
  opened,
  closed: !overlay.classList.contains("open"),
  expanded: toggle.attributes["aria-expanded"],
  backgroundsActive: backgrounds.every(item => !item.inert),
  focusRestored: toggle.focused,
}));
"""
    result = _node_result(script, harness, tmp_path, "mobile-nav")
    assert result == {
        "opened": True,
        "closed": True,
        "expanded": "false",
        "backgroundsActive": True,
        "focusRestored": True,
    }


def test_resource_save_waits_for_refresh_and_focuses_same_card(tmp_path: Path) -> None:
    source = Path("allspark/templates/index.html").read_text(encoding="utf-8")
    close_script = _function(source, "closeResEdit", "async function saveResource")
    save_script = _function(source, "saveResource", "/* === Mind")
    script = f"{close_script}\n{save_script}"
    harness = r"""
const vm = require("node:vm");
const events = [];
const previous = {focus() { events.push("detached-focus"); }};
const modal = {
  style: {display: "flex"},
  _previouslyFocused: previous,
  _resourceType: "water",
  _inputKind: "estimate",
};
function card(type) {
  return {
    type, focused: false,
    getAttribute(name) { return name === "data-resource-type" ? type : null; },
    focus() { this.focused = true; events.push(`focus-${type}`); },
  };
}
let cards = [card("food"), card("water")];
const inputs = {
  "res-edit-amount": {value: "10"},
  "res-edit-consumption": {value: "2"},
  "res-edit-intake": {value: "1"},
  "res-edit-capacity": {value: "0"},
  "res-edit-people": {value: "2"},
};
const document = {
  body: {contains: () => false},
  getElementById(id) { return id === "res-edit-modal" ? modal : inputs[id]; },
  querySelectorAll() { return cards; },
};
const context = vm.createContext({
  document,
  console,
  api: async () => { events.push("fetch"); return {}; },
  confirmDialog: async () => true,
  resourceFieldKnown: () => true,
  RESOURCE_CONTRACTS: {water: {max: 100000, range: "0-100000 L"}},
  RES_I18N: {outlierConfirm: "Confirm {range}"},
  refreshDashboard: async () => {
    events.push("refresh-start");
    await Promise.resolve();
    cards = [card("food"), card("water")];
    events.push("refresh-done");
  },
  notify: error => { throw error; },
});
vm.runInContext(__SCRIPT__, context);
(async () => {
  await vm.runInContext('saveResource("water")', context);
  process.stdout.write(JSON.stringify({events, display: modal.style.display}));
})().catch(error => { console.error(error); process.exit(1); });
"""
    result = _node_result(script, harness, tmp_path, "resource-focus")
    assert result == {
        "events": ["fetch", "refresh-start", "refresh-done", "focus-water"],
        "display": "none",
    }
