"""Tests for ExternalKBService — Kiwix/Kolibri/ProtoMaps integration."""

import json
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from allspark.core.database import Database
from allspark.services.external_kb import ExternalKBService, _KiwixClient, _KolibriClient, _ProtoMapsClient


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "test.db"))


class TestKiwixClient:
    @patch("urllib.request.urlopen")
    def test_is_available_true(self, mock_urlopen):
        resp = MagicMock()
        resp.status = 200
        mock_urlopen.return_value.__enter__.return_value = resp
        assert _KiwixClient("http://localhost:8081").is_available() is True

    @patch("urllib.request.urlopen", side_effect=OSError("down"))
    def test_is_available_false(self, mock_urlopen):
        assert _KiwixClient("http://localhost:8081").is_available() is False

    @patch("urllib.request.urlopen")
    def test_search_json(self, mock_urlopen):
        resp = MagicMock()
        resp.headers = {"Content-Type": "application/json"}
        resp.read.return_value = json.dumps([{"title": "Water"}]).encode()
        mock_urlopen.return_value.__enter__.return_value = resp
        results = _KiwixClient("http://localhost:8081").search("water")
        assert results[0]["title"] == "Water"

    @patch("urllib.request.urlopen")
    def test_get_article(self, mock_urlopen):
        resp = MagicMock()
        resp.read.return_value = b"<html>Article</html>"
        mock_urlopen.return_value.__enter__.return_value = resp
        result = _KiwixClient("http://localhost:8081").get_article("A/Article")
        assert "Article" in result["content"]


class TestKolibriClient:
    @patch("urllib.request.urlopen")
    def test_list_channels(self, mock_urlopen):
        resp = MagicMock()
        resp.read.return_value = json.dumps([{"name": "Math"}]).encode()
        mock_urlopen.return_value.__enter__.return_value = resp
        channels = _KolibriClient("http://localhost:8082").list_channels()
        assert channels[0]["name"] == "Math"

    @patch("urllib.request.urlopen")
    def test_search_content(self, mock_urlopen):
        resp = MagicMock()
        resp.read.return_value = json.dumps({"results": [{"title": "Algebra"}]}).encode()
        mock_urlopen.return_value.__enter__.return_value = resp
        results = _KolibriClient("http://localhost:8082").search_content("algebra")
        assert results[0]["title"] == "Algebra"


class TestProtoMapsClient:
    def test_unavailable_without_files(self, tmp_path):
        client = _ProtoMapsClient(tmp_path)
        assert client.is_available() is False

    def test_search_metadata(self, tmp_path):
        mb = tmp_path / "map.mbtiles"
        conn = sqlite3.connect(str(mb))
        conn.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
        conn.execute("INSERT INTO metadata VALUES (?, ?)", ("name", "Water source map"))
        conn.commit()
        conn.close()

        client = _ProtoMapsClient(tmp_path)
        assert client.is_available() is True
        results = client.search_poi("water")
        assert results[0]["file"] == "map.mbtiles"


class TestExternalKBService:
    def test_search_all_no_services(self, db, tmp_path):
        svc = ExternalKBService(db, maps_dir=tmp_path)
        assert svc.search_all("water") == {}

    @patch.object(_KiwixClient, "is_available", return_value=True)
    @patch.object(_KiwixClient, "search", return_value=[{"title": "Water"}])
    def test_search_all_with_kiwix(self, mock_search, mock_available, db, tmp_path):
        svc = ExternalKBService(db, maps_dir=tmp_path)
        results = svc.search_all("water")
        assert "kiwix" in results
        assert results["kiwix"][0]["title"] == "Water"
