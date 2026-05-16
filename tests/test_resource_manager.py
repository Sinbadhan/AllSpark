import pytest

from allspark.resource_manager import ResourceManager, _DEFAULT_RESOURCES
from allspark.models import ResourceType, OperatingMode


@pytest.fixture
def rm(tmp_path):
    from allspark.database import Database
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


class TestResourceManagerI18n:
    def test_summary_chinese(self, rm):
        from allspark.i18n import set_language
        set_language("zh", persist=False)
        rm.init_defaults()
        summary = rm.get_resource_summary()
        assert isinstance(summary, str)
        assert len(summary) > 0

    def test_summary_english(self, rm):
        from allspark.i18n import set_language
        set_language("en", persist=False)
        rm.init_defaults()
        summary = rm.get_resource_summary()
        assert isinstance(summary, str)
        assert len(summary) > 0
