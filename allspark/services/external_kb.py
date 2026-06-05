"""ExternalKBService — external offline knowledge base integration.

PRD §5.2: Kiwix/ZIM, Kolibri, ProtoMaps.
All integrations are optional and offline/local-network only.
"""

import json
import logging
import sqlite3
import urllib.parse
import urllib.request
from pathlib import Path

from allspark.base_service import BaseService
from allspark.core.database import Database

logger = logging.getLogger(__name__)


class ExternalKBService(BaseService):
    SERVICE_NAME = "external_kb"

    def __init__(self, db: Database, **kwargs):
        super().__init__(db, **kwargs)
        self.kiwix = _KiwixClient(kwargs.get("kiwix_url", "http://localhost:8081"))
        self.kolibri = _KolibriClient(kwargs.get("kolibri_url", "http://localhost:8082"))
        self.protomaps = _ProtoMapsClient(kwargs.get("maps_dir"))

    def is_available(self) -> bool:
        return self.kiwix.is_available() or self.kolibri.is_available() or self.protomaps.is_available()

    def search_all(self, query: str, limit: int = 10) -> dict:
        """Search all available external KBs."""
        results = {}
        if self.kiwix.is_available():
            results["kiwix"] = self.kiwix.search(query, limit)
        if self.kolibri.is_available():
            results["kolibri"] = self.kolibri.search_content(query, limit)
        if self.protomaps.is_available():
            results["protomaps"] = self.protomaps.search_poi(query, limit)
        return results


class _KiwixClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(self.base_url, method="HEAD")
            with urllib.request.urlopen(req, timeout=2) as resp:
                return 200 <= resp.status < 500
        except Exception:
            return False

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Search Kiwix server. Supports JSON API if available, otherwise returns URL."""
        q = urllib.parse.quote(query)
        # Kiwix serves search at /search?pattern=...
        url = f"{self.base_url}/search?pattern={q}"
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                content_type = resp.headers.get("Content-Type", "")
                data = resp.read().decode("utf-8", errors="ignore")
                if "application/json" in content_type:
                    parsed = json.loads(data)
                    return parsed[:limit] if isinstance(parsed, list) else parsed.get("results", [])[:limit]
                return [{"source": "kiwix", "title": query, "url": url, "snippet": data[:500]}]
        except Exception as e:
            logger.debug("Kiwix search failed: %s", e)
            return []

    def get_article(self, path: str) -> dict:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = resp.read().decode("utf-8", errors="ignore")
                return {"source": "kiwix", "url": url, "content": data}
        except Exception as e:
            return {"source": "kiwix", "url": url, "error": str(e)}


class _KolibriClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.base_url}/api/content/channel/", method="HEAD")
            with urllib.request.urlopen(req, timeout=2) as resp:
                return 200 <= resp.status < 500
        except Exception:
            return False

    def list_channels(self) -> list[dict]:
        try:
            with urllib.request.urlopen(f"{self.base_url}/api/content/channel/", timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data if isinstance(data, list) else data.get("results", [])
        except Exception:
            return []

    def search_content(self, query: str, limit: int = 10) -> list[dict]:
        q = urllib.parse.quote(query)
        try:
            url = f"{self.base_url}/api/content/node/?search={q}"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                results = data if isinstance(data, list) else data.get("results", [])
                return results[:limit]
        except Exception:
            return []


class _ProtoMapsClient:
    def __init__(self, maps_dir: str | Path | None = None):
        self.maps_dir = Path(maps_dir) if maps_dir else Path.home() / ".allspark" / "maps"

    def is_available(self) -> bool:
        return self.maps_dir.exists() and any(self.maps_dir.glob("*.mbtiles"))

    def search_poi(self, query: str, limit: int = 10) -> list[dict]:
        """Best-effort POI search in MBTiles metadata/tiles tables."""
        if not self.is_available():
            return []
        results = []
        for path in self.maps_dir.glob("*.mbtiles"):
            try:
                conn = sqlite3.connect(str(path))
                rows = conn.execute(
                    "SELECT name, value FROM metadata WHERE lower(value) LIKE ? LIMIT ?",
                    (f"%{query.lower()}%", limit),
                ).fetchall()
                for name, value in rows:
                    results.append({"source": "protomaps", "file": path.name, "name": name, "value": value})
                conn.close()
            except Exception:
                continue
            if len(results) >= limit:
                break
        return results[:limit]

    def get_tile(self, z: int, x: int, y: int) -> bytes | None:
        if not self.is_available():
            return None
        for path in self.maps_dir.glob("*.mbtiles"):
            try:
                conn = sqlite3.connect(str(path))
                row = conn.execute(
                    "SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=? LIMIT 1",
                    (z, x, y),
                ).fetchone()
                conn.close()
                if row:
                    return row[0]
            except Exception:
                continue
        return None
