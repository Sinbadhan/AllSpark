"""SHA-212: execute the rendered Repository JavaScript against DOM stubs."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.test_web_ui_v11 import TempDb, _client


def _repository_script(html: str) -> str:
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL)
    return next(script for script in scripts if "const REPO_I18N" in script)


def _runtime_result(html: str, scenario: dict[str, Any], tmp_path: Path) -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI"):
            pytest.fail("Node.js is required for the Repository JavaScript runtime gate in CI")
        pytest.skip("Node.js is required for the Repository JavaScript runtime gate")

    script = _repository_script(html)
    harness = f"""
const vm = require("node:vm");
const scenario = {json.dumps(scenario)};

function makeClassList(initial = []) {{
  const values = new Set(initial);
  return {{
    toggle(name) {{
      if (values.has(name)) {{ values.delete(name); return false; }}
      values.add(name); return true;
    }},
    contains(name) {{ return values.has(name); }},
  }};
}}

function makeElement() {{
  return {{
    innerHTML: "",
    textContent: "",
    value: "",
    style: {{}},
    classList: makeClassList(),
    attributes: {{}},
    setAttribute(name, value) {{ this.attributes[name] = String(value); }},
    getAttribute(name) {{ return this.attributes[name] || null; }},
    addEventListener() {{}},
    querySelectorAll() {{ return []; }},
    focus() {{}},
  }};
}}

const elements = {{
  "section-title": makeElement(),
  "repo-content": makeElement(),
  "file-tree": makeElement(),
  "file-tree-toggle": makeElement(),
}};
elements["file-tree"].classList = makeClassList(["hidden"]);
elements["file-tree-toggle"].attributes["aria-expanded"] = "false";

const documentStub = {{
  body: {{ appendChild() {{}} }},
  querySelectorAll() {{ return []; }},
  getElementById(id) {{
    if (!elements[id]) elements[id] = makeElement();
    return elements[id];
  }},
  createElement() {{
    let text = "";
    const el = makeElement();
    Object.defineProperty(el, "textContent", {{
      get() {{ return text; }},
      set(value) {{ text = String(value ?? ""); }},
    }});
    Object.defineProperty(el, "innerHTML", {{
      get() {{
        return text.replaceAll("&", "&amp;").replaceAll("<", "&lt;")
          .replaceAll(">", "&gt;").replaceAll('"', "&quot;");
      }},
      set(value) {{ text = String(value ?? ""); }},
    }});
    return el;
  }},
}};

const context = vm.createContext({{
  console,
  document: documentStub,
  LANG: scenario.lang || "zh",
  I18N: {{
    web_tab_knowledge: "knowledge",
    web_tab_experience: "experience",
    web_tab_llm: "models",
    web_tab_skf: "skf",
    web_tab_community: "community",
    web_th_id: "ID",
    web_th_title: "title",
    web_th_category: "category",
    web_th_tier: "tier",
  }},
  URLSearchParams,
  fetch: async () => ({{ json: async () => ({{}}) }}),
  api: async (path) => {{
    if (path === "/api/knowledge/categories") return scenario.categories;
    if (path.startsWith("/api/knowledge/category/")) return scenario.entries;
    throw new Error("Unexpected API call: " + path);
  }},
  toast() {{}},
  notify() {{}},
  setTimeout,
  clearTimeout,
}});

(async () => {{
  const completion = vm.runInContext({json.dumps(script)}, context);
  await completion;
  vm.runInContext("toggleFileTree()", context);
  process.stdout.write(JSON.stringify({{
    content: elements["repo-content"].innerHTML,
    treeExpanded: elements["file-tree-toggle"].attributes["aria-expanded"],
    treeHidden: elements["file-tree"].classList.contains("hidden"),
  }}));
}})().catch(error => {{
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
}});
"""
    harness_path = tmp_path / "repository-runtime.cjs"
    harness_path.write_text(harness, encoding="utf-8")
    result = subprocess.run(
        [node, str(harness_path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return json.loads(result.stdout)


def _entry(index: int, *, language: str = "zh") -> dict[str, Any]:
    return {
        "id": f"kid-{index}",
        "title": f"entry-{index}",
        "summary": "summary",
        "category": "medicine",
        "priority": 1,
        "verification": "expert_verified",
        "language": language,
    }


def test_all_repository_i18n_consumers_are_declared() -> None:
    source = Path("allspark/templates/repository.html").read_text(encoding="utf-8")
    declaration = re.search(r"const REPO_I18N = \{(.*?)\n\};", source, re.DOTALL)
    assert declaration is not None
    declared = set(re.findall(r"^\s*([A-Za-z_]\w*)\s*:", declaration.group(1), re.MULTILINE))
    consumed = set(re.findall(r"REPO_I18N\.([A-Za-z_]\w*)", source))
    assert consumed <= declared, f"Missing REPO_I18N mappings: {sorted(consumed - declared)}"


@pytest.mark.parametrize(
    ("scenario", "expected"),
    [
        ({"categories": [], "entries": []}, ["没有知识条目"]),
        (
            {"categories": [{"category": "medicine"}], "entries": [_entry(1, language="en")]},
            ["无匹配条目", "共 0 条"],
        ),
        (
            {"categories": [{"category": "medicine"}], "entries": [_entry(1)]},
            ["repo-search", "kid-1", "entry-1", "共 1 条", "1 / 1"],
        ),
        (
            {"categories": [{"category": "medicine"}], "entries": [_entry(i) for i in range(25)]},
            ["kid-0", "kid-19", "共 25 条", "1 / 2", "_repoGo(2)"],
        ),
    ],
)
def test_repository_runtime_states(
    scenario: dict[str, Any], expected: list[str], tmp_path: Path
) -> None:
    with TempDb() as db_path:
        client = _client(db_path)
        language = client.post("/api/system/language", json={"language": "zh"})
        assert language.status_code == 200
        assert language.json()["language"] == "zh"
        html = client.get("/repository").text
    result = _runtime_result(html, scenario, tmp_path)
    for marker in expected:
        assert marker in result["content"]
    assert result["treeExpanded"] == "true"
    assert result["treeHidden"] is False
