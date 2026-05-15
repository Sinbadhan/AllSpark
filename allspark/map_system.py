from allspark.database import Database
from allspark.models import MapPOI
from datetime import datetime


class MapSystem:
    def __init__(self, db: Database):
        self.db = db

    def add_poi(self, name: str, poi_type: str,
                description: str = "", distance_km: float = 0.0,
                direction: str = "", notes: str = "") -> MapPOI:
        now = datetime.now().isoformat()
        poi_id = f"poi-{poi_type}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        poi = MapPOI(
            id=poi_id, name=name, type=poi_type,
            description=description, distance_km=distance_km,
            direction=direction, notes=notes,
            discovered_at=now, verified=False
        )
        self.db.save_poi(poi)
        return poi

    def remove_poi(self, poi_id: str):
        self.db.delete_poi(poi_id)

    def get_all(self) -> list[MapPOI]:
        return self.db.get_all_pois()

    def get_by_type(self, poi_type: str) -> list[MapPOI]:
        return self.db.get_pois_by_type(poi_type)

    def format_map(self) -> str:
        pois = self.get_all()
        if not pois:
            return "🗺️ 地图为空。使用 'map add' 命令添加地点。"

        lines = ["🗺️ 周边地图："]
        by_type: dict[str, list[MapPOI]] = {}
        for p in pois:
            by_type.setdefault(p.type, []).append(p)

        type_icons = {
            "water": "💧", "shelter": "🏠", "food": "🍎",
            "danger": "⚠️", "resource": "📦", "camp": "⛺",
            "medical": "🏥", "other": "📍"
        }

        for poi_type, items in sorted(by_type.items()):
            icon = type_icons.get(poi_type, "📍")
            lines.append(f"\n  {icon} {poi_type.upper()}")
            for p in items:
                verified = "✓" if p.verified else "?"
                dist = f"{p.distance_km:.1f}km" if p.distance_km > 0 else "距离未知"
                direction = f" {p.direction}" if p.direction else ""
                lines.append(f"    [{verified}] {p.name} — {dist}{direction}")
                if p.description:
                    lines.append(f"         {p.description}")
                if p.notes:
                    lines.append(f"         📝 {p.notes}")
        return "\n".join(lines)

    def format_poi_detail(self, poi: MapPOI) -> str:
        lines = [
            f"📍 {poi.name}",
            f"  类型: {poi.type}",
            f"  距离: {poi.distance_km:.1f}km" if poi.distance_km > 0 else "  距离: 未知",
        ]
        if poi.direction:
            lines.append(f"  方向: {poi.direction}")
        if poi.description:
            lines.append(f"  描述: {poi.description}")
        if poi.notes:
            lines.append(f"  备注: {poi.notes}")
        lines.append(f"  发现时间: {poi.discovered_at}")
        lines.append(f"  验证: {'已验证 ✓' if poi.verified else '未验证 ?'}")
        return "\n".join(lines)
