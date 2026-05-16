import os
import tempfile
from pathlib import Path

import pytest

from allspark.database import Database
from allspark.models import (
    Resource, ResourceType, Task, KnowledgeEntry,
    ExperienceLog, MapPOI, OperatingState, OperatingMode,
    CommunityMember, ConflictRecord, TradeOffer,
)


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    database = Database(db_path)
    yield database
    database.close()


class TestDatabaseResources:
    def test_upsert_and_get_resource(self, db):
        r = Resource(
            type=ResourceType.POWER,
            current_amount=100.0,
            unit="Wh",
            daily_consumption=50.0,
            daily_intake=0.0,
            estimated_remaining_hours=48.0,
            last_updated="",
        )
        db.upsert_resource(r)
        got = db.get_resource(ResourceType.POWER)
        assert got is not None
        assert got.current_amount == 100.0
        assert got.unit == "Wh"
        assert got.daily_consumption == 50.0

    def test_get_all_resources(self, db):
        for rtype in ResourceType:
            r = Resource(type=rtype, current_amount=10.0, unit="u",
                         daily_consumption=1.0, daily_intake=0.0,
                         estimated_remaining_hours=10.0, last_updated="")
            db.upsert_resource(r)
        all_r = db.get_all_resources()
        assert len(all_r) == len(ResourceType)

    def test_get_nonexistent_resource(self, db):
        assert db.get_resource(ResourceType.WATER) is None

    def test_update_resource(self, db):
        r = Resource(type=ResourceType.FOOD, current_amount=50.0, unit="kcal",
                     daily_consumption=10.0, daily_intake=0.0,
                     estimated_remaining_hours=120.0, last_updated="")
        db.upsert_resource(r)
        r2 = Resource(type=ResourceType.FOOD, current_amount=30.0, unit="kcal",
                      daily_consumption=10.0, daily_intake=0.0,
                      estimated_remaining_hours=72.0, last_updated="")
        db.upsert_resource(r2)
        got = db.get_resource(ResourceType.FOOD)
        assert got.current_amount == 30.0


class TestDatabaseTasks:
    def test_save_and_get_tasks(self, db):
        t = Task(id="t1", phase=1, priority=1, title="Find water",
                 description="Locate water source", status="pending",
                 created_at="2026-01-01T00:00:00", updated_at="2026-01-01T00:00:00")
        db.save_task(t)
        tasks = db.get_tasks_by_phase(1)
        assert len(tasks) == 1
        assert tasks[0].title == "Find water"

    def test_update_task_status(self, db):
        t = Task(id="t2", phase=1, priority=2, title="Build shelter",
                 description="", status="pending",
                 created_at="2026-01-01T00:00:00", updated_at="2026-01-01T00:00:00")
        db.save_task(t)
        db.update_task_status("t2", "in_progress")
        active = db.get_active_tasks()
        assert any(a.id == "t2" and a.status == "in_progress" for a in active)


class TestDatabaseKnowledge:
    def test_save_and_get_knowledge(self, db):
        k = KnowledgeEntry(
            id="k1", category="water", subcategory="purification",
            priority=1, title="Boil Water", summary="Boil water for 3 minutes",
            steps=["Collect water", "Heat to boiling", "Boil 3 min"],
            prerequisites=["Container", "Heat source"],
            warnings=["Do not use contaminated containers"],
            verification="expert_verified", source="pre_collapse",
            version=1, language="zh",
        )
        db.save_knowledge(k)
        got = db.get_knowledge("k1")
        assert got is not None
        assert got.title == "Boil Water"
        assert len(got.steps) == 3

    def test_search_knowledge(self, db):
        k = KnowledgeEntry(
            id="k2", category="fire", subcategory="starting",
            priority=1, title="Fire Starting Methods",
            summary="How to start a fire using friction",
            steps=[], prerequisites=[], warnings=[],
            verification="unverified", source="pre_collapse",
            version=1, language="en",
        )
        db.save_knowledge(k)
        results = db.search_knowledge("fire")
        assert len(results) >= 1
        assert results[0].id == "k2"

    def test_get_knowledge_by_category(self, db):
        for i in range(3):
            k = KnowledgeEntry(
                id=f"water_{i}", category="water", subcategory="test",
                priority=2, title=f"Water Tip {i}", summary="",
                steps=[], prerequisites=[], warnings=[],
                verification="unverified", source="pre_collapse",
                version=1, language="zh",
            )
            db.save_knowledge(k)
        results = db.get_knowledge_by_category("water")
        assert len(results) == 3


class TestDatabaseCommunity:
    def test_community_member_crud(self, db):
        db.upsert_community_member(
            "m1", "Alice", "commander", "[]", "[]",
            "good", 0.8, 10.0, "2026-01-01", "2026-01-02", 1
        )
        members = db.get_community_members()
        assert len(members) == 1
        assert members[0]["name"] == "Alice"

        db.delete_community_member("m1")
        assert len(db.get_community_members()) == 0

    def test_conflict_crud(self, db):
        db.upsert_conflict(
            "c1", "Food dispute", "Disagreement over rations",
            '["Alice","Bob"]', "open", "", "",
            "2026-01-01", ""
        )
        conflicts = db.get_conflicts()
        assert len(conflicts) == 1
        assert conflicts[0]["title"] == "Food dispute"

    def test_trade_offer_crud(self, db):
        db.upsert_trade_offer(
            "tr1", "spark-001", "spark-002",
            '["k1"]', '["k2"]', "proposed",
            "2026-01-01", ""
        )
        offers = db.get_trade_offers()
        assert len(offers) == 1
        assert offers[0]["proposer_id"] == "spark-001"


class TestDatabaseAggregation:
    def test_knowledge_categories(self, db):
        for i in range(3):
            cat = "water" if i < 2 else "fire"
            k = KnowledgeEntry(
                id=f"cat_{cat}_{i}", category=cat, subcategory="",
                priority=1, title=f"{cat} tip {i}", summary="",
                steps=[], prerequisites=[], warnings=[],
                verification="unverified", source="pre_collapse",
                version=1, language="zh",
            )
            db.save_knowledge(k)
        cats = db.get_knowledge_categories()
        cat_map = {c["category"]: c["cnt"] for c in cats}
        assert cat_map.get("water") == 2
        assert cat_map.get("fire") == 1

    def test_knowledge_count(self, db):
        assert db.get_knowledge_count() == 0
        k = KnowledgeEntry(
            id="cnt1", category="food", subcategory="",
            priority=1, title="Test", summary="",
            steps=[], prerequisites=[], warnings=[],
            verification="unverified", source="pre_collapse",
            version=1, language="zh",
        )
        db.save_knowledge(k)
        assert db.get_knowledge_count() == 1

    def test_distinct_categories(self, db):
        for cat in ["water", "fire", "food"]:
            k = KnowledgeEntry(
                id=f"dist_{cat}", category=cat, subcategory="",
                priority=1, title=f"{cat}", summary="",
                steps=[], prerequisites=[], warnings=[],
                verification="unverified", source="pre_collapse",
                version=1, language="zh",
            )
            db.save_knowledge(k)
        cats = db.get_distinct_knowledge_categories()
        assert set(cats) == {"water", "fire", "food"}

    def test_knowledge_ids(self, db):
        for i in range(3):
            k = KnowledgeEntry(
                id=f"id_{i}", category="test", subcategory="",
                priority=1, title=f"Test {i}", summary="",
                steps=[], prerequisites=[], warnings=[],
                verification="unverified", source="pre_collapse",
                version=1, language="zh",
            )
            db.save_knowledge(k)
        ids = db.get_knowledge_ids()
        assert len(ids) == 3


class TestDatabaseIntegrity:
    def test_check_integrity(self, db):
        assert db.check_integrity() is True
