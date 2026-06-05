import logging
from datetime import datetime

from allspark.core.database import Database
from allspark.core.i18n import t
from allspark.core.models import MapPOI

logger = logging.getLogger(__name__)


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
            return t("map_empty")

        lines = [t("map_header")]
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
                dist = t("map_distance_km", km=p.distance_km) if p.distance_km > 0 else t("map_distance_unknown")
                direction = f" {p.direction}" if p.direction else ""
                lines.append(f"    [{verified}] {p.name} — {dist}{direction}")
                if p.description:
                    lines.append(f"         {p.description}")
                if p.notes:
                    lines.append(f"         📝 {p.notes}")
        return "\n".join(lines)

    def format_poi_detail(self, poi: MapPOI) -> str:
        lines = [
            t("map_poi_name", name=poi.name),
            t("map_poi_type", type=poi.type),
            t("map_poi_distance_km", km=poi.distance_km) if poi.distance_km > 0 else t("map_poi_distance_unknown"),
        ]
        if poi.direction:
            lines.append(t("map_poi_direction", dir=poi.direction))
        if poi.description:
            lines.append(t("map_poi_description", desc=poi.description))
        if poi.notes:
            lines.append(t("map_poi_notes", notes=poi.notes))
        lines.append(t("map_poi_discovered", time=poi.discovered_at))
        lines.append(t("map_poi_verified_yes") if poi.verified else t("map_poi_verified_no"))
        return "\n".join(lines)
