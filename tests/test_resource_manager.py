import pytest

from allspark.core.models import OperatingMode, ResourceType
from allspark.services.resource_manager import (
    _DEFAULT_RESOURCES,
    ResourceManager,
    ResourceValidationError,
)


@pytest.fixture
def rm(tmp_path):
    from allspark.core.database import Database
    db = Database(tmp_path / "test.db")
    mgr = ResourceManager(db)
    yield mgr
    db.close()


class TestDefaultResources:
    def test_all_defaults_zero(self):
        for rtype, resource in _DEFAULT_RESOURCES.items():
            assert resource.current_amount == 0.0, f"{rtype.value} amount should be 0"
            assert resource.daily_consumption == 0.0, f"{rtype.value} consumption should be 0"
            assert resource.daily_intake == 0.0, f"{rtype.value} intake should be 0"

    def test_all_resource_types_present(self):
        for rtype in ResourceType:
            assert rtype in _DEFAULT_RESOURCES


class TestResourceManager:
    def test_init_defaults(self, rm):
        rm.init_defaults()
        for rtype in ResourceType:
            r = rm.db.get_resource(rtype)
            assert r is not None

    def test_set_resource(self, rm):
        rm.init_defaults()
        rm.update_resource(ResourceType.POWER, 200.0, consumption=100.0, intake=50.0)
        r = rm.db.get_resource(ResourceType.POWER)
        assert r.current_amount == 200.0
        assert r.daily_consumption == 100.0
        assert r.daily_intake == 50.0

    def test_get_resource_summary_no_data(self, rm):
        rm.init_defaults()
        summary = rm.get_resource_summary()
        assert "未配置" in summary or "not configured" in summary.lower() or "0" in summary

    def test_get_resource_summary_with_data(self, rm):
        rm.init_defaults()
        rm.update_resource(ResourceType.POWER, 200.0, consumption=100.0, intake=50.0)
        summary = rm.get_resource_summary()
        assert "200" in summary or "power" in summary.lower()

    def test_check_warnings_no_data(self, rm):
        rm.init_defaults()
        warnings = rm.check_warnings()
        assert isinstance(warnings, list)

    def test_update_operating_mode(self, rm):
        rm.init_defaults()
        mode, reason = rm.update_operating_mode()
        assert mode in [OperatingMode.PROACTIVE, OperatingMode.STANDARD,
                        OperatingMode.ECONOMY, OperatingMode.HIBERNATION]

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0, 1_000_000_000_001.0])
    def test_update_rejects_invalid_values_without_writing(self, rm, value):
        rm.init_defaults()
        before = rm.db.get_resource(ResourceType.WATER)
        with pytest.raises(ResourceValidationError):
            rm.update_resource(ResourceType.WATER, value, consumption=2.0)
        after = rm.db.get_resource(ResourceType.WATER)
        assert after == before

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), 0.0, -5.0])
    def test_consume_requires_positive_finite_value_without_writing(self, rm, value):
        rm.init_defaults()
        rm.update_resource(ResourceType.WATER, 10.0, consumption=2.0)
        with pytest.raises(ResourceValidationError):
            rm.consume_resource(ResourceType.WATER, value)
        assert rm.db.get_resource(ResourceType.WATER).current_amount == 10.0


class TestResourceManagerI18n:
    def test_summary_chinese(self, rm):
        from allspark.core.i18n import set_language
        set_language("zh", persist=False)
        rm.init_defaults()
        summary = rm.get_resource_summary()
        assert isinstance(summary, str)
        assert len(summary) > 0

    def test_summary_english(self, rm):
        from allspark.core.i18n import set_language
        set_language("en", persist=False)
        rm.init_defaults()
        summary = rm.get_resource_summary()
        assert isinstance(summary, str)
        assert len(summary) > 0
