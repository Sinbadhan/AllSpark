"""AS-16: request language and its database must have the same owner."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from allspark.adapters.web_ui import create_app
from allspark.core.database import Database
from allspark.core.i18n import get_language, language_context, set_language
from tests.http_helpers import LocalAPIClient


def test_web_language_is_local_to_instance_in_both_orders_and_concurrently(tmp_path):
    apps = []
    for name in ("a", "b"):
        path = tmp_path / f"{name}.db"
        db = Database(path)
        db.mark_initialized()
        db.close()
        apps.append(create_app(str(path)))
    try:
        with LocalAPIClient(apps[0]) as a, LocalAPIClient(apps[1]) as b:
            assert a.post("/api/system/language", json={"language": "en"}).status_code == 200
            assert apps[0].state.db.conn.execute("SELECT value FROM operating_state WHERE key='language'").fetchone()[0] == "en"
            assert apps[1].state.db.conn.execute("SELECT value FROM operating_state WHERE key='language'").fetchone() is None
            assert b.post("/api/system/language", json={"language": "zh"}).status_code == 200

            def check(client, expected):
                for _ in range(5):
                    assert client.get("/api/system/about").json()["language"] == expected
                    response = client.post("/api/chat", content="{", headers={"Content-Type": "application/json"})
                    assert response.status_code == 400
                    assert ("无效" in response.text) == (expected == "zh")

            with ThreadPoolExecutor(2) as executor:
                futures = [executor.submit(check, a, "en"), executor.submit(check, b, "zh")]
                for future in futures:
                    future.result()
            check(b, "zh")
            check(a, "en")
    finally:
        for app in apps:
            app.state.db.close()


def test_language_context_restores_cli_state_on_exception(tmp_path):
    db = Database(tmp_path / "restore.db")
    previous = get_language()
    try:
        with pytest.raises(RuntimeError, match="failure"):
            with language_context(db):
                set_language("en" if previous == "zh" else "zh", persist=False)
                assert get_language() != previous
                raise RuntimeError("failure")
        assert get_language() == previous
        assert db.conn.execute("SELECT value FROM operating_state WHERE key='language'").fetchone() is None
    finally:
        db.close()
