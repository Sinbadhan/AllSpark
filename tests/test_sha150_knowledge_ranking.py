"""SHA-150: natural-language survival Q&A ranking + answer formatting.

Validates: bm25 + title-substring re-rank surfaces the right entry first
(煮沸净水法 for "如何安全净水", 打火石取火法 for "如何生火", not 伤口处理);
answers are 1 main + 2 related links (not full-text concat); a 50+ query
golden set covers the critical survival domains.
"""
import os
import re
import tempfile

import pytest

from allspark.bootstrap import ApplicationBootstrap
from allspark.core.database import Database
from allspark.core.i18n import get_language, set_language
from allspark.infrastructure.hardware import FeatureFlags
from allspark.services.knowledge_engine import KnowledgeEngine
from allspark.services.knowledge_loader import load_all_knowledge
from allspark.services.rule_engine import RuleEngine


def _load_knowledge(db):
    for e in load_all_knowledge("zh"):
        db.save_knowledge(e)


def _entry_titles(resp: str) -> list[str]:
    """Extract `[id] title` lines (main answer + related links) from a response."""
    return re.findall(r"^\[[^\]]+\] (.+)$", resp, re.MULTILINE)


@pytest.fixture(scope="module")
def rule_engine():
    prev_lang = get_language()
    set_language("zh")
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(path)
    _load_knowledge(db)
    container = ApplicationBootstrap(db, flags=FeatureFlags()).bootstrap()
    engine = RuleEngine(container)
    yield engine
    db.close()
    os.unlink(path)
    set_language(prev_lang)


@pytest.fixture
def ke_db():
    prev_lang = get_language()
    set_language("zh")
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(path)
    _load_knowledge(db)
    yield db
    db.close()
    os.unlink(path)
    set_language(prev_lang)


# Critical queries: the main answer (first entry) must contain an expected term.
CRITICAL_TOP1 = [
    ("如何安全净水？", ["煮沸净水法"]),
    ("怎么止血", ["出血止血法"]),
    ("失温怎么办", ["失温症处理"]),
    ("如何生火", ["取火"]),
    ("什么野菜能吃", ["可食用野菜"]),
    ("怎么搭庇护所", ["庇护所", "避难所", "帐篷"]),
]


class TestCriticalRanking:
    @pytest.mark.parametrize("query,expected", CRITICAL_TOP1)
    def test_main_answer_is_relevant(self, rule_engine, query, expected):
        resp = rule_engine.process_input(query)
        titles = _entry_titles(resp)
        assert titles, f"{query}: no knowledge entry in response"
        assert any(term in titles[0] for term in expected), (
            f"{query}: expected one of {expected} in main answer, got '{titles[0]}'"
        )

    def test_water_query_does_not_surface_wound_care(self, rule_engine):
        """Headline SHA-150 case: 净水 must not return 伤口处理 first."""
        resp = rule_engine.process_input("如何安全净水？")
        titles = _entry_titles(resp)
        assert titles
        assert "伤口处理" not in titles[0]
        assert any("净水" in t or "水" in t for t in titles[:3])


# Domain coverage: ~50 phrasings; Top-3 (main + related) must contain a
# domain-relevant entry. (Navigation has no knowledge entries in the base, so
# it is not a golden domain.)
DOMAIN_TERMS = {
    "water": ["净水", "水源", "饮水", "取水", "水分", "煮沸"],
    "fire": ["取火", "火", "燃料", "生火"],
    "food": ["食用", "野菜", "食物", "狩猎", "可食", "觅食"],
    "shelter": ["庇护所", "避难所", "帐篷", "遮蔽", "住所"],
    "medical": ["止血", "伤口", "失温", "急救", "CPR", "烧烫伤", "出血", "骨折", "心肺"],
}

DOMAIN_QUERIES = [
    ("water", "如何安全净水"), ("water", "怎么喝水"), ("water", "哪里找水"),
    ("water", "水源怎么找"), ("water", "饮水净化"), ("water", "缺水怎么办"),
    ("water", "雨水怎么收集"), ("water", "怎么过滤水"), ("water", "地表水怎么取"),
    ("water", "怎么煮沸净水"),
    ("fire", "如何生火"), ("fire", "怎么取火"), ("fire", "点火方法"),
    ("fire", "怎么取暖"), ("fire", "生火工具"), ("fire", "火堆怎么搭"),
    ("fire", "没有打火机怎么生火"), ("fire", "燃料怎么选"), ("fire", "野外生火"),
    ("food", "什么野菜能吃"), ("food", "怎么找食物"), ("food", "可食用植物"),
    ("food", "怎么狩猎"), ("food", "捕鱼方法"), ("food", "哪些植物有毒"),
    ("food", "饥荒吃什么"), ("food", "野外觅食"), ("food", "能吃的野菜"),
    ("food", "怎么辨认毒植物"),
    ("shelter", "怎么搭庇护所"), ("shelter", "避难所怎么建"), ("shelter", "帐篷搭建"),
    ("shelter", "野外过夜住哪"), ("shelter", "怎么建住所"), ("shelter", "简易遮蔽处"),
    ("shelter", "城市废墟怎么住"), ("shelter", "长期住所建造"), ("shelter", "怎么搭帐篷"),
    ("medical", "怎么止血"), ("medical", "伤口怎么处理"), ("medical", "失温怎么办"),
    ("medical", "大出血急救"), ("medical", "心肺复苏"), ("medical", "烧烫伤处理"),
    ("medical", "怎么急救"), ("medical", "骨折怎么办"), ("medical", "CPR怎么做"),
    ("medical", "外伤处理"),
]


class TestGoldenSet:
    @pytest.mark.parametrize("domain,query", DOMAIN_QUERIES)
    def test_top3_contains_domain_entry(self, rule_engine, domain, query):
        resp = rule_engine.process_input(query)
        titles = _entry_titles(resp)
        terms = DOMAIN_TERMS[domain]
        assert titles, f"{query}: no knowledge entry in response"
        assert any(
            any(term in t for term in terms) for t in titles[:3]
        ), f"{query}: no {domain} entry in top-3 {titles[:3]}"

    def test_golden_set_has_at_least_50_queries(self):
        assert len(CRITICAL_TOP1) + len(DOMAIN_QUERIES) >= 50


class TestAnswerFormat:
    def test_one_main_plus_two_related_not_full_concat(self, ke_db):
        ke = KnowledgeEngine(ke_db)
        entries = ke.search_by_language("水 净水 水源 饮水", limit=3)
        assert len(entries) >= 2
        formatted = ke.format_answer(entries)
        # Main entry: id + summary (full detail).
        assert f"[{entries[0].id}]" in formatted
        assert entries[0].summary in formatted
        # Related entries: title link present, full summary absent.
        assert entries[1].title in formatted
        assert entries[1].summary not in formatted
        # Related-knowledge label present.
        assert "相关" in formatted

    def test_empty_entries_shows_no_match(self, ke_db):
        ke = KnowledgeEngine(ke_db)
        out = ke.format_answer([])
        assert out  # non-empty "no match" message
        assert "净水" not in out  # not a fake entry


class TestRankingDirect:
    def test_water_purification_above_wound_care(self, ke_db):
        ke = KnowledgeEngine(ke_db)
        titles = [e.title for e in ke.search_by_language("水 净水 水源 饮水", limit=5)]
        assert "煮沸净水法" in titles[:3]
        assert "伤口处理基础" not in titles[:3]

    def test_fire_method_in_top3(self, ke_db):
        ke = KnowledgeEngine(ke_db)
        titles = [e.title for e in ke.search_by_language("火 生火 点火 取暖 燃料 取火", limit=5)]
        assert any("取火" in t for t in titles[:3]), titles[:3]
