"""Tests for VectorEngine — RAG vector search."""

import pytest

from allspark.core.database import Database
from allspark.core.models import KnowledgeEntry
from allspark.services.knowledge_engine import KnowledgeEngine
from allspark.services.vector_engine import VectorEngine


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "test.db"))


@pytest.fixture
def entries(db):
    items = [
        KnowledgeEntry(
            id="water/boil", category="survival", subcategory="water", priority=0,
            title="Boil water", summary="Purify water by boiling", steps=["filter", "boil"], language="en",
        ),
        KnowledgeEntry(
            id="food/forage", category="survival", subcategory="food", priority=0,
            title="Forage food", summary="Find edible plants", steps=["identify", "test"], language="en",
        ),
    ]
    for item in items:
        db.save_knowledge(item)
    return items


class TestVectorEngine:
    def test_unavailable_without_deps(self, db):
        ve = VectorEngine(db)
        ve.startup()
        # In CI/dev without sentence-transformers, this should degrade cleanly.
        assert isinstance(ve.is_available(), bool)

    def test_fallback_embedding_available(self, db):
        ve = VectorEngine(db, fallback_embedding=True)
        ve.startup()
        assert ve.is_available() is True
        emb = ve.generate_embedding("water purification")
        assert len(emb) == 384

    def test_index_and_search(self, db, entries):
        ve = VectorEngine(db, fallback_embedding=True)
        ve.startup()
        for entry in entries:
            ve.index_knowledge(entry)
        results = ve.search("water boil", limit=2)
        assert len(results) > 0
        assert results[0][0] in {"water/boil", "food/forage"}

    def test_reindex_all(self, db, entries):
        ve = VectorEngine(db, fallback_embedding=True)
        ve.startup()
        count = ve.reindex_all()
        assert count == 2
        rows = db.get_knowledge_vectors()
        assert len(rows) == 2

    def test_hybrid_search_falls_back_to_fts(self, db, entries):
        ve = VectorEngine(db)
        # Not started / unavailable; hybrid should return FTS results.
        results = ve.hybrid_search("water", limit=5)
        assert len(results) > 0

    def test_knowledge_engine_uses_vector_when_available(self, db, entries):
        ve = VectorEngine(db, fallback_embedding=True)
        ve.startup()
        ve.reindex_all()
        ke = KnowledgeEngine(db, vector_engine=ve)
        results = ke.search("water", limit=5)
        assert len(results) > 0
