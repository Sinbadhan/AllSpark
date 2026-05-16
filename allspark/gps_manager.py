import json
import uuid
from datetime import datetime
from typing import Optional
from math import radians, sin, cos, sqrt, atan2


class GPSManager:
    def __init__(self, db=None, sensor_hub=None):
        self.db = db
        self.sensor_hub = sensor_hub
        self._current_position = None

    def get_position(self) -> Optional[dict]:
        if self.sensor_hub:
            try:
                for dev in self.sensor_hub.get_all_devices():
                    if dev.get("type") == "gps":
                        readings = self.sensor_hub.get_device_readings(dev["name"], last_n=1)
                        if readings:
                            coords = readings[0].get("value", {})
                            if isinstance(coords, dict) and "lat" in coords and "lon" in coords:
                                self._current_position = {
                                    "lat": coords["lat"],
                                    "lon": coords["lon"],
                                    "alt": coords.get("alt", 0),
                                    "accuracy": coords.get("accuracy", 0),
                                    "source": "sensor",
                                    "timestamp": datetime.now().isoformat(),
                                }
                                self._save_position(self._current_position)
                                return self._current_position
            except Exception:
                pass

        if self._current_position:
            return self._current_position

        if self.db:
            return self._load_last_position()

        return None

    def set_manual_position(self, lat: float, lon: float, alt: float = 0.0) -> dict:
        position = {
            "lat": lat,
            "lon": lon,
            "alt": alt,
            "accuracy": 0,
            "source": "manual",
            "timestamp": datetime.now().isoformat(),
        }
        self._current_position = position
        self._save_position(position)
        return position

    def _save_position(self, position: dict):
        if not self.db:
            return
        self.db.save_hardware_profile(
            "last_gps_position", json.dumps(position, ensure_ascii=False)
        )

    def _load_last_position(self) -> Optional[dict]:
        if not self.db:
            return None
        try:
            row = self.db.conn.execute(
                "SELECT value FROM hardware_profile WHERE key='last_gps_position'"
            ).fetchone()
            if row:
                return json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            pass
        return None

    def calculate_distance(self, lat1: float, lon1: float,
                           lat2: float, lon2: float) -> float:
        R = 6371.0
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))
        return R * c

    def calculate_bearing(self, lat1: float, lon1: float,
                          lat2: float, lon2: float) -> float:
        dlon = radians(lon2 - lon1)
        y = sin(dlon) * cos(radians(lat2))
        x = cos(radians(lat1)) * sin(radians(lat2)) - sin(radians(lat1)) * cos(radians(lat2)) * cos(dlon)
        bearing = atan2(y, x)
        bearing = (bearing * 180 / 3.14159265 + 360) % 360
        return bearing

    def bearing_to_direction(self, bearing: float) -> str:
        directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        index = round(bearing / 45) % 8
        return directions[index]

    def annotate_pois_with_distance(self) -> list[dict]:
        position = self.get_position()
        if not position or not self.db:
            return []

        pois = self.db.get_all_pois()
        return [{"id": p.id, "name": p.name, "type": p.type,
                 "distance_km": p.distance_km, "direction": p.direction}
                for p in pois]

    def record_track_point(self, label: str = ""):
        position = self.get_position()
        if not position or not self.db:
            return None

        point_id = f"track-{uuid.uuid4().hex[:8]}"
        self.db.save_hardware_profile(point_id, json.dumps({
            "lat": position["lat"],
            "lon": position["lon"],
            "alt": position.get("alt", 0),
            "label": label,
            "timestamp": position["timestamp"],
        }, ensure_ascii=False))
        return point_id

    def get_track_history(self, limit: int = 50) -> list[dict]:
        if not self.db:
            return []
        rows = self.db.conn.execute(
            "SELECT key, value FROM hardware_profile WHERE key LIKE 'track-%' LIMIT ?",
            (limit,),
        ).fetchall()
        results = []
        for r in rows:
            try:
                data = json.loads(r[1])
                data["id"] = r[0]
                results.append(data)
            except (json.JSONDecodeError, TypeError):
                pass
        return results

    def format_position(self, position: dict = None) -> str:
        if position is None:
            position = self.get_position()

        if not position:
            return "📍 位置未知。使用 'gps set <纬度> <经度>' 设置位置。"

        source = {"sensor": "📡 GPS传感器", "manual": "✋ 手动输入"}.get(
            position.get("source", ""), "❓ 未知"
        )

        lines = [
            "📍 当前位置",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"  纬度：{position['lat']:.6f}°",
            f"  经度：{position['lon']:.6f}°",
            f"  海拔：{position.get('alt', 0):.0f}m",
            f"  精度：{position.get('accuracy', 0):.0f}m",
            f"  来源：{source}",
            f"  时间：{position.get('timestamp', '')}",
        ]
        return "\n".join(lines)

    def format_track(self, limit: int = 20) -> str:
        track = self.get_track_history(limit)
        if not track:
            return "📍 暂无轨迹记录。"

        lines = ["📍 轨迹记录"]
        for pt in track:
            label = f" ({pt['label']})" if pt.get("label") else ""
            ts = pt.get("timestamp", "")[:16]
            lines.append(
                f"  {ts}  "
                f"{pt['lat']:.4f}°, {pt['lon']:.4f}°{label}"
            )
        return "\n".join(lines)
