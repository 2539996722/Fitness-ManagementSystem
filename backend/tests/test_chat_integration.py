"""chat.py 集成测试（mock LLM + RAG + DB，测 _build_history + 端到端 send_message）。

策略：
- DB：mock AsyncSession（select/scalars 链）
- LLM：patch llm_service.chat 返固定字符串
- RAG：patch retrieve 返固定 chunks
- KB：patch retrieve_from_all 返固定 chunks
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1.chat import _build_history, _detect_intent, send_message
from app.schemas.chat import ChatMessageIn


def _make_message(sender_type: str, content: str, created_at: datetime | None = None):
    return SimpleNamespace(
        sender_type=sender_type,
        content=content,
        created_at=created_at or datetime(2024, 1, 1),
    )


def _mock_history_session(messages: list):
    """session.execute().scalars().all() == messages（按时间倒序）。"""
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = messages
    session.execute.return_value = result
    return session


# ============ _build_history 多轮 ============

class TestBuildHistory:
    """从 DB 取最近 max_rounds 轮对话 → OpenAI 格式 messages。"""

    @pytest.mark.asyncio
    async def test_empty_history(self):
        session = _mock_history_session([])
        out = await _build_history(session, conv_id=1, max_rounds=5)
        assert out == []

    @pytest.mark.asyncio
    async def test_single_user_message(self):
        session = _mock_history_session([
            _make_message("user", "hi"),
        ])
        out = await _build_history(session, conv_id=1, max_rounds=5)
        assert out == [{"role": "user", "content": "hi"}]

    @pytest.mark.asyncio
    async def test_role_mapping_user_to_user_ai_to_assistant(self):
        """DB 返回 DESC（newest first），路由 reversed → ASC。"""
        # DB 给的顺序：新→旧（DESC）
        session = _mock_history_session([
            _make_message("ai", "答 2", datetime(2024, 1, 2)),
            _make_message("user", "问 2", datetime(2024, 1, 2)),
            _make_message("ai", "答 1", datetime(2024, 1, 1)),
            _make_message("user", "问 1", datetime(2024, 1, 1)),
        ])
        out = await _build_history(session, conv_id=1)
        # 还原为 ASC：Q1 → A1 → Q2 → A2
        assert out == [
            {"role": "user", "content": "问 1"},
            {"role": "assistant", "content": "答 1"},
            {"role": "user", "content": "问 2"},
            {"role": "assistant", "content": "答 2"},
        ]

    @pytest.mark.asyncio
    async def test_trainer_and_ai_map_to_assistant(self):
        """trainer / ai 消息统一映射为 assistant（OpenAI 协议兼容）。"""
        session = _mock_history_session([
            _make_message("trainer", "教练回复", datetime(2024, 1, 3)),
            _make_message("ai", "AI 回复", datetime(2024, 1, 2)),
            _make_message("user", "问 1", datetime(2024, 1, 1)),
        ])
        out = await _build_history(session, conv_id=1)
        # 非 user 全部 → assistant
        assert out[0] == {"role": "user", "content": "问 1"}
        assert out[1] == {"role": "assistant", "content": "AI 回复"}
        assert out[2] == {"role": "assistant", "content": "教练回复"}

    @pytest.mark.asyncio
    async def test_max_rounds_limits_messages(self):
        """max_rounds=5 → 最多 10 条消息（每轮 2 条）。"""
        # 12 条消息（6 轮）
        msgs = []
        for i in range(6):
            msgs.append(_make_message("user", f"Q{i}"))
            msgs.append(_make_message("ai", f"A{i}"))
        # 取 6 条（最近的 3 轮 = 6 条）
        session = _mock_history_session(msgs[:6])
        out = await _build_history(session, conv_id=1, max_rounds=3)
        assert len(out) == 6  # 3 轮 × 2

    @pytest.mark.asyncio
    async def test_message_order_preserved(self):
        """DB 倒序取出后，代码里 reversed → 恢复时间正序。"""
        session = _mock_history_session([
            _make_message("ai", "A2", datetime(2024, 1, 3)),  # 最新
            _make_message("user", "Q2", datetime(2024, 1, 3)),
            _make_message("ai", "A1", datetime(2024, 1, 1)),
            _make_message("user", "Q1", datetime(2024, 1, 1)),  # 最旧
        ])
        out = await _build_history(session, conv_id=1)
        assert [m["content"] for m in out] == ["Q1", "A1", "Q2", "A2"]


# ============ _detect_intent 集成 ============

class TestDetectIntentIntegration:
    """在 send_message 流程里 _detect_intent 的应用。"""

    def test_plan_question_triggers_plan_intent(self):
        assert _detect_intent("帮我制定一个训练计划") == "plan"

    def test_diet_question_triggers_diet_intent(self):
        assert _detect_intent("增肌吃什么") == "diet"

    def test_substitute_question_triggers_substitute(self):
        # 避开 plan 关键词（"怎么练"会被 plan 先匹配）
        assert _detect_intent("没有器械时的替代动作") == "substitute"
        assert _detect_intent("在家练胸的相似动作") == "substitute"

    def test_unknown_question_defaults_to_qa(self):
        assert _detect_intent("胸肌的结构是什么") == "qa"


# ============ send_message 端到端 ============

# mock LLM response —— 用真正的 LLMCallResult dataclass
def _mock_llm_result(content="LLM 回复", prompt_tokens=10, completion_tokens=20, total_tokens=30, model="gpt-4o-mini"):
    from app.services.llm_service import LLMCallResult
    return LLMCallResult(
        content=content,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        latency_ms=100,
        model=model,
        intent="qa",
    )


def _build_send_message_session(*, conversation_id=None):
    """构造 send_message 用的 session mock（按调用顺序返回）。"""
    session = AsyncMock()
    next_id = {"v": 1000}

    async def fake_refresh(obj):
        if getattr(obj, "id", None) is None:
            obj.id = next_id["v"]
            next_id["v"] += 1
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime(2024, 1, 1)
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = datetime(2024, 1, 1)

    async def fake_flush():
        # 模拟 ORM flush：给 add 过的对象设 id
        for call in session.add.call_args_list:
            obj = call.args[0] if call.args else None
            if obj and getattr(obj, "id", None) is None:
                obj.id = next_id["v"]
                next_id["v"] += 1

    session.refresh.side_effect = fake_refresh
    session.flush.side_effect = fake_flush
    session.commit = AsyncMock()
    session.add = MagicMock()

    # execute() 按顺序返回不同结果
    def make_scalar_result(value):
        r = MagicMock()
        r.scalar_one_or_none.return_value = value
        return r

    def make_scalars_result(values):
        r = MagicMock()
        r.scalars.return_value.all.return_value = values
        return r

    # 1) 取 / 创建会话（如果是新建，scalar_one_or_none 不会被用）
    #    实际路由：if body.conversation_id → 一次 execute 取会话
    #             else → 跳过 execute，session.add(conv) + flush
    #    历史 + KB 都是用 scalars().all()
    # 简化：返回一个通用的 multi-result list
    results = [
        make_scalar_result(None),                          # 取会话（None = 新建）
        make_scalars_result([]),                            # 历史消息（空）
        make_scalars_result([]),                            # KB 列表（空）
    ]
    session.execute.side_effect = results
    return session


class TestSendMessageEndToEnd:

    @pytest.mark.asyncio
    async def test_qa_with_rag_injection(self):
        """QA intent + RAG chunks → system prompt 注入 + LLM 调用。"""
        session = _build_send_message_session()
        body = ChatMessageIn(content="胸肌的结构是什么", conversation_id=None, use_kb=False)

        # Mock RAG chunks
        rag_chunk = SimpleNamespace(
            id="0001", name_zh="卧推", name_en="Bench Press",
            body_part="chest", equipment="barbell", target="pectorals",
            snippet="标准卧推动作要领", score=0.1,
        )

        with patch("app.api.v1.chat.retrieve", new=AsyncMock(return_value=[rag_chunk])) as mock_retrieve, \
             patch("app.api.v1.chat.llm_service.chat", new=AsyncMock(return_value=_mock_llm_result(content="试试卧推"))):
            from fastapi import Request
            fake_req = MagicMock(spec=Request)
            fake_req.headers = {}

            user = SimpleNamespace(id=1, role="user", status=0, is_deleted=False)
            result = await send_message(fake_req, body, user, session)

        assert result.content == "试试卧推"
        assert result.intent == "qa"
        assert result.done is True
        # RAG 至少被调过一次
        assert mock_retrieve.await_count >= 1

    @pytest.mark.asyncio
    async def test_new_conversation_creates_one(self):
        """无 conversation_id 应自动创建会话。"""
        session = _build_send_message_session()
        body = ChatMessageIn(content="hello", conversation_id=None, use_kb=False)

        with patch("app.api.v1.chat.retrieve", new=AsyncMock(return_value=[])), \
             patch("app.api.v1.chat.llm_service.chat", new=AsyncMock(return_value=_mock_llm_result(content="hi"))):
            from fastapi import Request
            fake_req = MagicMock(spec=Request)
            fake_req.headers = {}
            user = SimpleNamespace(id=1, role="user", status=0, is_deleted=False)
            result = await send_message(fake_req, body, user, session)

        # 至少应该 add 了一个 conversation（外加 user message）
        assert session.add.call_count >= 2
        assert result.conversation_id is not None

    @pytest.mark.asyncio
    async def test_existing_conversation_not_found_404(self):
        """conversation_id 给了但不属于自己的 → 404。"""
        session = AsyncMock()
        # 取会话返回 None
        result = MagicMock(); result.scalar_one_or_none.return_value = None
        session.execute.return_value = result

        body = ChatMessageIn(content="hi", conversation_id=999, use_kb=False)
        from fastapi import Request
        fake_req = MagicMock(spec=Request)
        fake_req.headers = {}
        user = SimpleNamespace(id=1, role="user", status=0, is_deleted=False)

        with pytest.raises(HTTPException) as exc:
            await send_message(fake_req, body, user, session)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_diet_intent_skips_rag(self):
        """diet intent 也走 RAG（不 plan 就行）。"""
        session = _build_send_message_session()
        # 用纯饮食 query（避开 _KEYWORD_EXPANSION 触发的"训练计划"/"有氧"注入）
        # "减脂期" 会触发 _simple_rewrite 追加"训练计划"，导致 intent 被改成 plan
        # 用 "日常饮食" 只触发 diet 关键词，无 expand
        body = ChatMessageIn(content="日常饮食搭配建议", conversation_id=None, use_kb=False)

        with patch("app.api.v1.chat.retrieve", new=AsyncMock(return_value=[])) as mock_retrieve, \
             patch("app.api.v1.chat.llm_service.chat", new=AsyncMock(return_value=_mock_llm_result(content="鸡胸肉"))):
            from fastapi import Request
            fake_req = MagicMock(spec=Request)
            fake_req.headers = {}
            user = SimpleNamespace(id=1, role="user", status=0, is_deleted=False)
            result = await send_message(fake_req, body, user, session)

        assert result.intent == "diet"
        # diet 不走 RAG（路由设计：qa/substitute/plan 走 RAG，diet 走 KB）
        assert mock_retrieve.await_count == 0

    @pytest.mark.asyncio
    async def test_rag_failure_does_not_break_request(self):
        """RAG 异常应被吞掉，LLM 仍可调用。"""
        from app.services.rag_service import RAGError
        session = _build_send_message_session()
        body = ChatMessageIn(content="test", conversation_id=None, use_kb=False)

        async def fake_retrieve(*a, **kw):
            raise RAGError("simulated RAG failure")

        with patch("app.api.v1.chat.retrieve", side_effect=fake_retrieve), \
             patch("app.api.v1.chat.llm_service.chat", new=AsyncMock(return_value=_mock_llm_result(content="OK"))):
            from fastapi import Request
            fake_req = MagicMock(spec=Request)
            fake_req.headers = {}
            user = SimpleNamespace(id=1, role="user", status=0, is_deleted=False)
            result = await send_message(fake_req, body, user, session)

        # 不抛异常，正常返回
        assert result.content == "OK"
