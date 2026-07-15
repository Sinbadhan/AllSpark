import pytest

from allspark.core.database import Database
from allspark.core.models import Resource, ResourceType
from allspark.services.resource_manager import ResourceManager


def test_fire_remaining_uses_daily_consumption(tmp_path):
    db = Database(tmp_path / "fire.db")
    manager = ResourceManager(db)
    manager.init_defaults()

    manager.update_resource(
        ResourceType.FIRE, 10.0, consumption=2.0, intake=0.0
    )

    fire = db.get_resource(ResourceType.FIRE)
    assert fire is not None
    assert fire.estimated_remaining_hours == 120.0
    db.close()


@pytest.mark.parametrize(
    ("amount", "daily_consumption", "expected_hours"),
    [
        (0.5, 0.25, 48.0),
        (1_000_000_000_000.0, 1_000_000_000_000.0, 24.0),
        (10.0, 0.0, ResourceManager.SUSTAINED),
    ],
)
def test_fire_remaining_boundaries(amount, daily_consumption, expected_hours, tmp_path):
    db = Database(tmp_path / "fire-boundary.db")
    manager = ResourceManager(db)
    fire = Resource(
        type=ResourceType.FIRE,
        current_amount=amount,
        unit="uses",
        daily_consumption=daily_consumption,
        daily_intake=0.0,
        amount_known=True,
        consumption_known=True,
        intake_known=True,
    )

    assert manager._estimate_remaining(fire) == expected_hours
    db.close()
