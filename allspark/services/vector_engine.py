"""VectorEngine — RAG vector search with graceful degradation.

PRD §4.3 / §5: hybrid search (FTS5 + vector) for knowledge retrieval.

Design:
- sentence-transformers for embeddings when installed
- sqlite-vss or Qdrant can be added as backends; current offline-safe backend stores
  embeddings in a JSON table and computes cosine similarity in Python
- If optional dependencies are missing, gracefully returns unavailable and callers
  fall back to FTS5.
"""

import json
import logging
import math
from functools import lru_cache

from allspark.base_service import BaseService
from allspark.core.database import Database

logger = logging.getLogger(__name__)

EMBED_DIM = 384


class VectorEngine(BaseService):
    SERVICE_NAME = "vector_engine"

    def __init__(self, db: Database, **kwargs):
        super().__init__(db, **kwargs)
        self.flags = kwargs.get("flags")
        self._model = None
        self._available = False
        self._fallback_embedding = kwargs.get("fallback_embedding", False)

    def startup(self) -> None:
        """Initialize embedding model if available."""
        if self._fallback_embedding:
            self._available = True
            return
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer("all-MiniLM-L6-v2")
            self._available = True
        except Exception as e:
            logger.info("VectorEngine unavailable, falling back to FTS5: %s", e)
            self._available = False

    def is_available(self) -> bool:
        return self._available

    def generate_embedding(self, text: str) -> list[float]:
        """Generate embedding for text. Uses fallback hash embedding for tests."""
        if not text:
            return [0.0] * EMBED_DIM
        return list(self._generate_embedding_cached(text))

    @lru_cache(maxsize=1000)
    def _generate_embedding_cached(self, text: str) -> tuple[float, ...]:
        if self._model is not None:
            vec = self._model.encode(text, normalize_embeddings=True)
            return tuple(float(x) for x in vec)
        if self._fallback_embedding:
            return tuple(_hash_embedding(text))
        return tuple([0.0] * EMBED_DIM)

    def index_knowledge(self, entry) -> None:
        """Index a single KnowledgeEntry."""
        if not self.is_available():
            return
        text = _entry_text(entry)
        embedding = self.generate_embedding(text)
        self.db.save_knowledge_vector(entry.id, embedding)

    def reindex_all(self) -> int:
        """Index all knowledge rows. Returns count indexed."""
        if not self.is_available():
            return 0
        rows = self.db.conn.execute("SELECT * FROM knowledge").fetchall()
        count = 0
        for row in rows:
            entry = self.db._row_to_entry(row)
            self.index_knowledge(entry)
            count += 1
        self.db.conn.execute(
            "INSERT OR REPLACE INTO operating_state VALUES (?, ?)",
            ("vector_indexed", "true"),
        )
        self.db.conn.commit()
        return count

    def search(self, query: str, limit: int = 10) -> list[tuple[str, float]]:
        """Vector search. Returns list of (knowledge_id, similarity)."""
        if not self.is_available():
            return []
        qvec = self.generate_embedding(query)
        rows = self.db.get_knowledge_vectors()
        scored = []
        for row in rows:
            vec = json.loads(row["embedding"])
            score = _cosine(qvec, vec)
            scored.append((row["knowledge_id"], score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    def hybrid_search(self, query: str, limit: int = 10) -> list:
        """Hybrid FTS5 + vector search using Reciprocal Rank Fusion."""
        fts_results = self.db.search_knowledge(query, limit=limit)
        vector_ids = self.search(query, limit=limit) if self.is_available() else []

        if not vector_ids:
            return fts_results[:limit]

        # RRF fusion
        scores: dict[str, float] = {}
        K = 60
        for rank, entry in enumerate(fts_results, 1):
            scores[entry.id] = scores.get(entry.id, 0.0) + 1.0 / (K + rank)
        for rank, (kid, _sim) in enumerate(vector_ids, 1):
            scores[kid] = scores.get(kid, 0.0) + 1.0 / (K + rank)

        ids_sorted = sorted(scores, key=scores.get, reverse=True)
        results = []
        for kid in ids_sorted[:limit]:
            entry = self.db.get_knowledge(kid)
            if entry:
                results.append(entry)
        return results


def _entry_text(entry) -> str:
    steps = " ".join(entry.steps or [])
    return f"{entry.title} {entry.summary} {steps} {entry.category} {entry.subcategory}"


def _hash_embedding(text: str) -> list[float]:
    """Deterministic lightweight embedding for tests / fallback.

    This is NOT semantic search quality, but gives stable vectors without optional deps.
    """
    vec = [0.0] * EMBED_DIM
    for token in text.lower().split():
        idx = abs(hash(token)) % EMBED_DIM
        vec[idx] += 1.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(n))
    na = math.sqrt(sum(a[i] * a[i] for i in range(n))) or 1.0
    nb = math.sqrt(sum(b[i] * b[i] for i in range(n))) or 1.0
    return dot / (na * nb)
