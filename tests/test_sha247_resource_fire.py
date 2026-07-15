from allspark.core.database import Database
from allspark.core.models import ResourceType
from allspark.services.resource_manager import ResourceManager


def test_fire_remaining_uses_daily_consumption(tmp_path):
    db = Database(tmp_path / "fire.db")
    manager = ResourceManager(db)
    manager.init_defaults()

    manager.update_resource(ResourceType.FIRE, 10.0, consumption=2.0)

    fire = db.get_resource(ResourceType.FIRE)
    assert fire is not None
    assert fire.estimated_remaining_hours == 120.0
    db.close()
