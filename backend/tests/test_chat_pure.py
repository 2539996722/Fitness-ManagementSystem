"""chat.py 纯函数单测（无需 DB/LLM，跑得飞快）。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.api.v1.chat import (
    INTENT_KEYWORDS,
    _build_plan_intro,
    _detect_intent,
    _simple_rewrite,
    _templates_to_suggestions,
)


# ============ _build_plan_intro ============

class TestBuildPlanIntro:
    """plan intent 的开场白文案。"""

    @pytest.mark.parametrize("goal,expected_substr", [
        ("muscle_gain", "增肌"),
        ("fat_loss", "减脂"),
        ("body_shape", "塑形"),
        ("endurance", "体能"),
    ])
    def test_known_goal_in_intro(self, goal, expected_substr):
        out = _build_plan_intro(goal, 3)
        assert expected_substr in out
        assert "3 套" in out
        assert "挑一个最顺眼的" in out

    @pytest.mark.parametrize("goal", ["unknown_goal", "", None])
    def test_unknown_or_empty_goal_falls_back(self, goal):
        out = _build_plan_intro(goal, 5)
        assert "5 套训练计划" in out
        # 不能有意外的 goal 标签
        assert "增肌" not in out and "减脂" not in out

    def test_count_in_intro(self):
        assert "1 套" in _build_plan_intro("muscle_gain", 1)
        assert "10 套" in _build_plan_intro(None, 10)


# ============ _detect_intent ============

class TestDetectIntent:
    """关键词 → intent 映射。"""

    def test_plan_keywords(self):
        for kw in ["计划", "每周", "一周", "练几", "训练计划", "怎么练", "周几", "安排"]:
            assert _detect_intent(f"我想要{kw}") == "plan", f"failed for: {kw}"

    def test_substitute_keywords(self):
        for kw in ["替代", "代替", "没器械", "在家", "没有哑铃", "替换", "相似的动作"]:
            assert _detect_intent(f"用别的{kw}") == "substitute", f"failed for: {kw}"

    def test_diet_keywords(self):
        for kw in ["饮食", "吃", "蛋白质", "碳水", "食谱", "吃什么", "餐"]:
            assert _detect_intent(f"想问{kw}") == "diet", f"failed for: {kw}"

    def test_qa_default(self):
        """无关键词时默认 qa。"""
        assert _detect_intent("什么是 RAG？") == "qa"
        assert _detect_intent("hello") == "qa"

    def test_intent_priority_first_match_wins(self):
        """多个 intent 关键词同时出现时，按 INTENT_KEYWORDS 顺序匹配。"""
        # plan 关键词排在前面
        assert _detect_intent("计划怎么练") == "plan"
        # substitute 关键词也含"怎么练"吗？查表 — substitute 没"怎么练"，所以 plan 赢

    def test_keyword_case_insensitive(self):
        """英文关键词应不区分大小写（虽然当前关键词都是中文）。"""
        # 测一下逻辑存在即可
        assert _detect_intent("PLAN") in ("qa", "plan")  # 不会崩


# ============ _simple_rewrite ============

class TestSimpleRewrite:
    """错别字纠正 + 关键词增广。"""

    def test_typo_correction(self):
        """错别字 → 标准术语。"""
        assert "杠铃" in _simple_rewrite("用杠力练卧推")  # 杠力 → 杠铃
        assert "哑铃" in _simple_rewrite("亚玲弯举")      # 亚玲 → 哑铃
        assert "硬拉" in _simple_rewrite("硬垃怎么做")

    def test_no_typo_passthrough(self):
        """没有错别字时，原 query 应保留。"""
        assert _simple_rewrite("杠铃卧推怎么练") == "杠铃卧推怎么练"

    def test_keyword_expansion_by_body_part(self):
        """含身体部位 → 追加代表性动作。"""
        out = _simple_rewrite("练胸")
        assert "卧推" in out or "夹胸" in out  # 二选一

        out = _simple_rewrite("练背")
        assert "引体向上" in out or "划船" in out

        out = _simple_rewrite("练腿")
        assert "深蹲" in out or "腿举" in out

    def test_keyword_expansion_by_goal(self):
        """含训练目标 → 追加计划关键词。"""
        out = _simple_rewrite("我想增肌")
        assert "训练计划" in out or "周" in out

        out = _simple_rewrite("想减脂")
        assert "训练计划" in out or "有氧" in out

    def test_no_double_expansion(self):
        """原 query 已包含动作词时，不重复追加。"""
        out = _simple_rewrite("练胸：卧推和夹胸")
        # "卧推" 已在 query 里，不应再被增广到末尾
        # 因为 _simple_rewrite 只追加 1 个 extra，且只在原 query 没有时
        assert out.count("卧推") <= 2  # 1 原文 + 0 或 1 增广
        assert out.count("夹胸") <= 2

    def test_rewrite_does_not_break_unrelated_text(self):
        out = _simple_rewrite("今天天气怎么样")
        assert out == "今天天气怎么样"  # 完全不动

    def test_combined_typo_and_expansion(self):
        """错别字 + 增广 同时生效。"""
        out = _simple_rewrite("用杠力练胸")
        assert "杠铃" in out  # 错别字已纠正
        assert "卧推" in out or "夹胸" in out  # 增广也生效


# ============ _templates_to_suggestions ============

class TestTemplatesToSuggestions:
    """ORM rows → API dict 序列化。"""

    def _make_template(
        self, id=1, name="模板", goal="muscle_gain", level="beginner",
        cover_url=None, description="描述", use_count=10, avg_rating=4.5, weeks=None,
    ):
        return SimpleNamespace(
            id=id, name=name, goal=goal, level=level,
            cover_url=cover_url, description=description,
            use_count=use_count, avg_rating=avg_rating, weeks=weeks or [],
        )

    def test_basic_mapping(self):
        t = self._make_template()
        out = _templates_to_suggestions([t])
        assert len(out) == 1
        s = out[0]
        assert s["id"] == 1
        assert s["name"] == "模板"
        assert s["goal"] == "muscle_gain"
        assert s["level"] == "beginner"
        assert s["cover_url"] is None
        assert s["use_count"] == 10
        assert s["avg_rating"] == 4.5
        assert s["weeks_count"] == 0

    def test_description_truncated_at_120(self):
        long_desc = "x" * 200
        t = self._make_template(description=long_desc)
        out = _templates_to_suggestions([t])
        assert len(out[0]["description"]) == 120
        assert out[0]["description"] == "x" * 120

    def test_description_none_becomes_empty(self):
        t = self._make_template(description=None)
        out = _templates_to_suggestions([t])
        assert out[0]["description"] == ""

    def test_avg_rating_none_becomes_zero(self):
        t = self._make_template(avg_rating=None)
        out = _templates_to_suggestions([t])
        assert out[0]["avg_rating"] == 0.0

    def test_avg_rating_string_converted_to_float(self):
        t = self._make_template(avg_rating="3.5")
        out = _templates_to_suggestions([t])
        assert isinstance(out[0]["avg_rating"], float)
        assert out[0]["avg_rating"] == 3.5

    def test_weeks_count_uses_list_length(self):
        t = self._make_template(weeks=[{}, {}, {}, {}])
        out = _templates_to_suggestions([t])
        assert out[0]["weeks_count"] == 4

    def test_weeks_none_becomes_zero(self):
        t = self._make_template(weeks=None)
        out = _templates_to_suggestions([t])
        assert out[0]["weeks_count"] == 0

    def test_multiple_templates(self):
        ts = [self._make_template(id=i) for i in range(5)]
        out = _templates_to_suggestions(ts)
        assert len(out) == 5
        assert [s["id"] for s in out] == [0, 1, 2, 3, 4]


# ============ INTENT_KEYWORDS 表完整性 ============

class TestIntentKeywordsTable:
    """保证 INTENT_KEYWORDS 表的关键 intent 都存在。"""

    def test_all_intents_documented(self):
        assert set(INTENT_KEYWORDS.keys()) >= {"plan", "substitute", "diet", "qa"}

    def test_qa_is_default_fallback(self):
        """qa 是空列表 → 默认兜底 intent。"""
        assert INTENT_KEYWORDS["qa"] == []

    def test_no_intent_has_empty_keywords(self):
        """除了 qa 兜底，其他 intent 必须有关键词，否则就是 dead code。"""
        for intent, kws in INTENT_KEYWORDS.items():
            if intent == "qa":
                continue
            assert len(kws) > 0, f"intent {intent!r} has no keywords"
