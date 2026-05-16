import pytest

from allspark.governance import GovernanceEngine, PERMISSIONS
from allspark.models import GovernanceRole


@pytest.fixture
def gov(tmp_path):
    from allspark.database import Database
    db = Database(tmp_path / "test.db")
    engine = GovernanceEngine(db=db)
    yield engine
    db.close()


class TestGovernancePermissions:
    def test_commander_permissions(self):
        perms = PERMISSIONS[GovernanceRole.COMMANDER]
        assert "manage_members" in perms
        assert "resolve_conflicts" in perms
        assert "declare_emergency" in perms

    def test_observer_permissions_limited(self):
        perms = PERMISSIONS[GovernanceRole.OBSERVER]
        assert "view_resources" in perms
        assert "manage_members" not in perms

    def test_has_permission(self, gov):
        member = gov.add_member("Alice", role="commander")
        assert gov.has_permission(member.id, "manage_members") is True
        observer = gov.add_member("Bob", role="observer")
        assert gov.has_permission(observer.id, "manage_members") is False


class TestGovernanceMembers:
    def test_add_member(self, gov):
        member = gov.add_member("Alice", role="commander")
        assert member.name == "Alice"
        assert member.role == "commander"
        assert member.is_commander is True

    def test_only_one_commander(self, gov):
        first = gov.add_member("Alice", role="commander")
        second = gov.add_member("Bob", role="commander")
        assert first.is_commander is True
        assert second.is_commander is False

    def test_remove_member(self, gov):
        member = gov.add_member("Alice")
        assert gov.remove_member(member.id) is True
        assert gov.get_member(member.id) is None

    def test_assign_role(self, gov):
        member = gov.add_member("Alice", role="executor")
        gov.assign_role(member.id, "specialist", domains=["medical"])
        got = gov.get_member(member.id)
        assert got.role == "specialist"
        assert "medical" in got.domains

    def test_get_all_members(self, gov):
        gov.add_member("Alice")
        gov.add_member("Bob")
        assert len(gov.get_all_members()) == 2


class TestGovernanceConflicts:
    def test_create_conflict(self, gov):
        m1 = gov.add_member("Alice")
        m2 = gov.add_member("Bob")
        conflict = gov.create_conflict("Food dispute", "Over rations", [m1.id, m2.id])
        assert conflict.title == "Food dispute"
        assert len(conflict.parties) == 2

    def test_mediate_conflict(self, gov):
        m1 = gov.add_member("Alice")
        m2 = gov.add_member("Bob")
        conflict = gov.create_conflict("Water", "Over water", [m1.id, m2.id])
        result = gov.mediate_conflict(conflict.id)
        assert result is not None
        assert "strategies" in result

    def test_resolve_conflict(self, gov):
        m1 = gov.add_member("Alice")
        m2 = gov.add_member("Bob")
        conflict = gov.create_conflict("Test", "Test", [m1.id, m2.id])
        gov.resolve_conflict(conflict.id, "Compromise reached")
        got = gov.get_conflict(conflict.id)
        assert got.status == "resolved"
        assert got.resolution == "Compromise reached"


class TestGovernanceSurvivalValue:
    def test_calculate_survival_value(self, gov):
        member = gov.add_member("Alice", role="specialist",
                                domains=["medical"], skills=["surgery"])
        gov.update_contribution(member.id, 15.0)
        result = gov.calculate_survival_value(member.id)
        assert result is not None
        assert "composite_value" in result
        assert "dimensions" in result
        assert 0 <= result["composite_value"] <= 1.0

    def test_organization_assessment(self, gov):
        gov.add_member("Alice", role="commander")
        result = gov.assess_organization()
        assert result["total_members"] == 1
        assert result["has_commander"] is True
