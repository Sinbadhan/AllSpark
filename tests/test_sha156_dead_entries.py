"""SHA-156: Web global controls must not have dead entries.

"启动操作" must target the task center (/executions), not the dashboard root;
the dead `href="#"` docs link and the redundant settings icon (-> /config, dup
of the nav link) are removed. Mobile nav has a global search entry (desktop parity).
"""
from pathlib import Path


def _read(name: str) -> str:
    return (Path("allspark/templates") / name).read_text(encoding="utf-8")


class TestDeadEntries:
    def test_exec_btn_targets_executions_not_root(self):
        t = _read("base.html")
        # SHA-156: "启动操作" goes to /executions (task center), not /.
        assert "class=\"exec-btn\" onclick=\"location.href='/executions'\"" in t
        assert "class=\"exec-btn\" onclick=\"location.href='/'\"" not in t

    def test_no_dead_docs_link(self):
        t = _read("base.html")
        assert 'href="#"' not in t

    def test_no_redundant_settings_icon(self):
        t = _read("base.html")
        # SHA-156: settings icon (-> /config) removed; /config reached via nav.
        assert "location.href='/config'" not in t

    def test_mobile_global_search_exists(self):
        t = _read("base.html")
        # SHA-156: mobile nav must have a global search entry (desktop topbar parity).
        assert "mobile-global-search" in t
        assert "mobileSearch" in t  # JS binding
