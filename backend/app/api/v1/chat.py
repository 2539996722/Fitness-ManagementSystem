"""AI 助手路由（chat）。

Step 1：会话/消息 CRUD + Echo 占位（已完成）
Step 2：接入 LLM（OpenAI 兼容协议）—— 当前
Step 3：Chroma RAG + 企业文档知识库（下一步）
"""

import json
from typing import Annotated, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from loguru import logger
from slowapi import Limiter
from sse_starlette.sse import EventSourceResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, user_id_key_func
from app.core.config import settings
from app.db.models import Conversation, Message, User
from app.db.session import async_session, get_session
from app.schemas.chat import (
    ChatMessageIn,
    ChatMessageOut,
    ConversationCreateIn,
    ConversationListItem,
    ConversationOut,
    MessageOut,
)
from app.services import llm_service
from app.services.rag_service import RagChunk, RAGError, retrieve, to_prompt_context
from app.services.tracing import span

router = APIRouter()

# AI 调用限流：每用户每天 50 次、每分钟 5 次（PRD §6.4）。
# ponytail: 阈值从 settings 读（.env / 环境变量），后续上 SystemConfig 动态配置时再替换为 async callable。
limiter = Limiter(key_func=user_id_key_func)


# ============ 会话 CRUD ============

@router.post("/conversations", response_model=ConversationOut, summary="新建会话")
async def create_conversation(
    body: ConversationCreateIn | None = None,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    session: Annotated[AsyncSession, Depends(get_session)] = None,
) -> ConversationOut:
    """创建新会话（默认标题可后续自动生成）。"""
    title = body.title if body else None
    conv = Conversation(
        user_id=current_user.id,
        title=title or "新会话",
    )
    session.add(conv)
    await session.commit()
    await session.refresh(conv)
    return ConversationOut.model_validate(conv)


@router.get("/conversations", response_model=list[ConversationListItem], summary="会话列表")
async def list_conversations(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = 50,
) -> list[ConversationListItem]:
    """列出当前用户的会话（按更新时间倒序）。"""
    result = await session.execute(
        select(Conversation)
        .where(Conversation.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
    )
    convs = result.scalars().all()

    items = []
    for c in convs:
        # 取最近一条消息
        msg_result = await session.execute(
            select(Message)
            .where(Message.conversation_id == c.id)
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        last_msg = msg_result.scalar_one_or_none()
        items.append(
            ConversationListItem(
                id=c.id,
                user_id=c.user_id,
                title=c.title,
                status=c.status,
                conversation_type=c.conversation_type,
                created_at=c.created_at,
                updated_at=c.updated_at,
                last_message=last_msg.content[:80] if last_msg else None,
            )
        )
    return items


@router.get("/conversations/{conv_id}", response_model=ConversationOut, summary="会话详情")
async def get_conversation(
    conv_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConversationOut:
    result = await session.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.user_id == current_user.id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    return ConversationOut.model_validate(conv)


@router.get("/conversations/{conv_id}/messages", response_model=list[MessageOut], summary="消息历史")
async def list_messages(
    conv_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[MessageOut]:
    # 先确认会话归属
    conv_result = await session.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.user_id == current_user.id,
        )
    )
    if not conv_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")

    msgs = await session.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.asc())
    )
    return [MessageOut.model_validate(m) for m in msgs.scalars().all()]


@router.post(
    "/conversations/{conv_id}/messages",
    response_model=MessageOut,
    summary="C 端用户发消息（仅在 human_active 状态下）",
)
async def send_user_message(
    conv_id: int,
    body: dict,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MessageOut:
    """人工事态下，用户的消息只入库，不调 LLM，由客服侧 SSE 推送给客服。"""
    content = (body.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="内容不能为空")
    if len(content) > 4000:
        raise HTTPException(status_code=400, detail="内容过长")

    conv = await session.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.user_id == current_user.id,
        )
    )
    conv = conv.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")
    if conv.status != "human_active":
        raise HTTPException(status_code=400, detail="当前会话由 AI 服务，请直接发送")

    msg = Message(
        conversation_id=conv.id,
        sender_type="user",
        sender_id=current_user.id,
        content=content,
    )
    session.add(msg)
    conv.updated_at = func.now()
    await session.commit()
    await session.refresh(msg)
    return MessageOut.model_validate(msg)


@router.post("/conversations/{conv_id}/transfer", summary="转人工（用户主动触发）")
async def transfer_to_human(
    conv_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """把会话状态切到 waiting_human，等待客服接入。

    幂等：已经是 waiting_human / human_active 时直接返回。
    """
    conv = await session.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.user_id == current_user.id,
        )
    )
    conv = conv.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")

    if conv.status in ("waiting_human", "human_active"):
        return {
            "conversation_id": conv.id,
            "status": conv.status,
            "conversation_type": conv.conversation_type,
            "assigned_cs_id": conv.assigned_cs_id,
            "message": "已在排队中" if conv.status == "waiting_human" else "客服已接入",
        }

    if conv.status == "closed":
        raise HTTPException(status_code=400, detail="会话已关闭，无法转人工")

    conv.status = "waiting_human"
    conv.conversation_type = "customer_service"
    await session.commit()
    return {
        "conversation_id": conv.id,
        "status": conv.status,
        "conversation_type": conv.conversation_type,
        "assigned_cs_id": None,
        "message": "已提交，等待客服接入",
    }


@router.get("/conversations/{conv_id}/status", summary="查询会话当前状态（前端轮询/SSE 备用）")
async def get_conversation_status(
    conv_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    conv = await session.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.user_id == current_user.id,
        )
    )
    conv = conv.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    return {
        "conversation_id": conv.id,
        "status": conv.status,
        "conversation_type": conv.conversation_type,
        "assigned_cs_id": conv.assigned_cs_id,
    }


@router.get("/conversations/{conv_id}/stream", summary="C 端 SSE：监听自己会话的新消息")
async def user_stream(
    conv_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """和 CS 端 stream 同结构，但要求会话归属当前用户。"""
    conv = await session.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.user_id == current_user.id,
        )
    )
    if not conv.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="会话不存在")
    from app.api.v1.cs import stream_messages as cs_stream  # 复用实现
    return await cs_stream(conv_id=conv_id, current_user=current_user, session=session)


@router.delete("/conversations/{conv_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除会话")
async def delete_conversation(
    conv_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    conv = await session.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.user_id == current_user.id,
        )
    )
    conv = conv.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    await session.delete(conv)
    await session.commit()
    return None


# ============ 发送消息（Step 2: 接入 LLM）============

INTENT_KEYWORDS: dict[str, list[str]] = {
    "plan": ["计划", "安排", "每周", "练几", "训练计划", "怎么练", "周几", "一周"],
    "substitute": ["替代", "代替", "没有哑铃", "在家", "没器械", "替换", "相似的动作"],
    "diet": ["饮食", "吃", "增肌", "减脂", "蛋白质", "碳水", "食谱", "吃什么", "餐"],
    "qa": [],  # 默认
}


# ============ LLM function-calling 工具定义 ============

RECOMMEND_TEMPLATES_TOOL: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "recommend_templates",
            "description": (
                "从 FitHub 训练计划模板市场检索已发布（published）的训练计划。"
                "用户说『有没有推荐的训练计划』『给我个增肌计划』之类，必须先调用本工具。"
                "返回的模板 ID/名称/目标/水平/周数 都是真实数据，可以直接呈现给用户。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "enum": ["muscle_gain", "fat_loss", "body_shape", "endurance"],
                        "description": "训练目标，根据用户意图推断",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回模板数量（1-5）",
                        "default": 3,
                    },
                },
                "required": ["goal"],
            },
        },
    },
]


def _build_plan_intro(goal: str | None, n: int) -> str:
    """生成 plan-intent 的 AI 文案导语。"""
    goal_label = {
        "muscle_gain": "增肌",
        "fat_loss": "减脂",
        "body_shape": "塑形",
        "endurance": "体能",
    }.get(goal or "", "")
    if not goal_label:
        return f"为你精选了 {n} 套训练计划，挑一个最顺眼的："
    return f"为你精选了 {n} 套{goal_label}训练计划，挑一个最顺眼的："


def _detect_intent(text: str) -> str:
    """粗粒度意图识别。Step 3 接入 LLM 分类器。"""
    t = text.lower()
    for intent, kws in INTENT_KEYWORDS.items():
        if any(kw in text or kw.lower() in t for kw in kws):
            return intent
    return "qa"


# 常见错别字 / 同义词 → 标准健身术语（轻量纠错，提升 RAG 召回）
_REWRITE_MAP: dict[str, str] = {
    "杠铃": "杠铃",
    "哑铃": "哑铃",
    "杠力": "杠铃",
    "亚玲": "哑铃",
    "深蹲架": "深蹲",
    "卧推架": "杠铃卧推",
    "硬垃": "硬拉",
    "划船": "划船",
    "引体向上": "引体向上",
    "臂屈伸": "臂屈伸",
}


def _simple_rewrite(text: str) -> str:
    """轻量 query 改写：错别字 → 标准术语 + 关键词增广（提升 RAG 召回）。

    当前 MVP：
    - 错别字替换（_REWRITE_MAP）
    - 关键词增广（_KEYWORD_EXPANSION）：用户只说身体部位 / 目标时，
      自动加代表性动作关键词，帮 RAG 召回更具体的动作
    - 不调 LLM；后续可接小 LLM 做更智能改写
    """
    out = text
    for wrong, correct in _REWRITE_MAP.items():
        if wrong != correct and wrong in out:
            out = out.replace(wrong, correct)

    # 关键词增广：只在原 query 没出现这些动作词时才追加
    for keyword, extras in _KEYWORD_EXPANSION.items():
        if keyword in out:
            for extra in extras:
                if extra not in out:
                    out += " " + extra
                    break  # 每个规则只加一个 extra，避免太长
            break  # 只匹配第一条规则

    return out


# 关键词增广：原 query 含某关键词时，追加 1 个代表性动作词
_KEYWORD_EXPANSION: dict[str, list[str]] = {
    # 身体部位 → 代表性动作
    "胸": ["卧推", "夹胸"],
    "背": ["引体向上", "划船"],
    "腿": ["深蹲", "腿举"],
    "肩": ["推举", "侧平举"],
    "臂": ["弯举", "臂屈伸"],
    "核心": ["平板支撑", "卷腹"],
    # 目标 → 训练计划关键词
    "增肌": ["训练计划", "周"],
    "减脂": ["训练计划", "有氧"],
    "塑形": ["训练计划", "全身"],
    "体能": ["训练计划", "耐力"],
}


async def _build_history(
    session: AsyncSession, conv_id: int, max_rounds: int = 5
) -> list[dict[str, str]]:
    """取最近 max_rounds 轮对话（user/assistant）拼成 messages。

    注意：DB 里 sender_type 是 "user" / "ai" / "customer_service" / "trainer"，
    但 OpenAI 兼容协议只接受 "user" / "assistant" / "system"。
    这里把非 user 的消息统一映射为 "assistant"。
    """
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conv_id, Message.sender_type.in_(["user", "ai"]))
        .order_by(Message.created_at.desc())
        .limit(max_rounds * 2)
    )
    rows = list(reversed(result.scalars().all()))
    out: list[dict[str, str]] = []
    for r in rows:
        role = "assistant" if r.sender_type == "ai" else r.sender_type
        out.append({"role": role, "content": r.content})
    return out


@router.post("/chat/send", response_model=ChatMessageOut, summary="发送消息并获取 AI 回复")
@limiter.limit(settings.ai_user_minute_limit)
@limiter.limit(settings.ai_user_daily_limit)
async def send_message(
    request: Request,
    body: ChatMessageIn,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChatMessageOut:
    """发送一条消息，调用 LLM 生成回复。

    Step 2：调用 OpenAI 兼容协议 LLM，使用 system_prompt 来自 system_configs('llm')。
    Step 3：在 system_prompt 后追加 Chroma RAG 命中的相关动作/文档片段。
    """
    # 1. 取或创建会话
    if body.conversation_id:
        conv = await session.execute(
            select(Conversation).where(
                Conversation.id == body.conversation_id,
                Conversation.user_id == current_user.id,
            )
        )
        conv = conv.scalar_one_or_none()
        if not conv:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    else:
        # 自动从首条消息截取标题
        title = body.content.strip().splitlines()[0][:30] if body.content.strip() else "新会话"
        conv = Conversation(user_id=current_user.id, title=title)
        session.add(conv)
        await session.flush()

    # 2. 存用户消息
    user_msg = Message(
        conversation_id=conv.id,
        sender_type="user",
        sender_id=current_user.id,
        content=body.content,
    )
    session.add(user_msg)
    await session.flush()

    # ============ M10+ 6 阶段埋点 ============

    # 3. 阶段 1: Query 改写（轻量纠错 + 关键词扩展）
    with span("query_rewrite", conversation_id=conv.id, user_id=current_user.id) as s_qr:
        s_qr.input_preview = body.content
        rewritten = _simple_rewrite(body.content)
        s_qr.output_preview = rewritten
        s_qr.meta["rewritten"] = rewritten != body.content
        s_qr.intent = None  # 改写时尚不知意图

    # 4. 阶段 2: 意图识别
    with span("intent", conversation_id=conv.id, user_id=current_user.id) as s_intent:
        s_intent.input_preview = rewritten
        intent = _detect_intent(rewritten)
        s_intent.output_preview = intent
        s_intent.intent = intent

    # 5. 阶段 4: RAG 检索（仅 qa / substitute / plan）
    rag_chunks: list[RagChunk] = []
    if intent in ("qa", "substitute", "plan"):
        with span("rag", intent=intent, conversation_id=conv.id, user_id=current_user.id) as s_rag:
            s_rag.input_preview = rewritten
            try:
                rag_chunks = await retrieve(rewritten, top_k=3)
            except RAGError as e:
                logger.warning("RAG 检索失败，降级跳过：{}", e)
                s_rag.meta["error"] = str(e)[:200]
                rag_chunks = []
            s_rag.output_preview = f"{len(rag_chunks)} chunks"
            s_rag.meta["chunk_ids"] = [c.id for c in rag_chunks]

    # 5.5 阶段 3.5: KB 检索（独立 KB 集合，plan 不走 KB）
    kb_chunks = []
    if getattr(body, "use_kb", True) and intent in ("qa", "substitute", "diet"):
        try:
            from app.db.models import KnowledgeBase
            from app.services.kb_service import retrieve_from_all
            kbs = (await session.execute(
                select(KnowledgeBase).where(KnowledgeBase.enabled == True)
            )).scalars().all()
            kb_chunks = await retrieve_from_all(rewritten, kbs)
        except Exception as e:
            logger.warning(f"KB 检索失败（不影响主流程）：{e}")

    # 6. 拼历史上下文（最近 5 轮，不含本条）
    history = await _build_history(session, conv.id, max_rounds=5)
    # 移除刚刚加入的 user_msg（已在 flush，但 _build_history 用 desc+limit 抓的是历史）
    if history and history[-1]["role"] == "user" and history[-1]["content"] == body.content:
        history = history[:-1]

    # RAG context + KB context 注入到 system 段
    if rag_chunks:
        ctx = to_prompt_context(rag_chunks)
        # 放在历史最前面当 system 角色
        history.insert(0, {"role": "system", "content": ctx})
    if kb_chunks:
        from app.services.kb_service import format_kb_context
        kb_ctx = format_kb_context(kb_chunks)
        history.insert(0, {"role": "system", "content": kb_ctx})

    messages = history + [{"role": "user", "content": body.content}]

    # 7. 阶段 5: LLM 生成（plan-intent 时挂工具）
    tools = RECOMMEND_TEMPLATES_TOOL if intent == "plan" else None
    result = None
    with span("llm", intent=intent, conversation_id=conv.id, user_id=current_user.id) as s_llm:
        s_llm.input_preview = (messages[-1]["content"] if messages else "")[:200]
        s_llm.meta["model"] = (settings.llm_model_chat if False else None)  # 实际值由 result 填
        s_llm.meta["tools_count"] = len(tools) if tools else 0
        try:
            result = await llm_service.chat(
                messages,
                user_id=current_user.id,
                conversation_id=conv.id,
                intent=intent,
                tools=tools,
                tool_choice="auto" if tools else None,
            )
            s_llm.tokens = {
                "prompt": result.prompt_tokens,
                "completion": result.completion_tokens,
                "total": result.total_tokens,
            }
            s_llm.output_preview = (result.content or "")[:200]
            s_llm.meta["model"] = result.model
            s_llm.meta["tool_calls"] = result.tool_calls
        except Exception as e:
            logger.exception("LLM 调用失败：{}", e)
            s_llm.meta["error"] = str(e)[:200]
            # 失败兜底：让对话还能继续
            result_content = (
                f"⚠️ AI 服务暂时不可用：{str(e)[:100]}\n\n"
                "请稍后重试，或联系管理员检查后台【系统配置 → LLM 设置】。"
            )
            ai_msg = Message(
                conversation_id=conv.id,
                sender_type="ai",
                content=result_content,
                intent=intent,
                extra={"error": str(e)[:200]},
            )
            session.add(ai_msg)
            await session.commit()
            await session.refresh(ai_msg)
            # 阶段 6: output span
            with span("output", intent=intent, conversation_id=conv.id, user_id=current_user.id) as s_out:
                s_out.input_preview = "error_fallback"
                s_out.output_preview = "saved"
                s_out.meta["message_id"] = ai_msg.id
            return ChatMessageOut(
                conversation_id=conv.id,
                message_id=ai_msg.id,
                sender_type="ai",
                content=result_content,
                intent=intent,
                done=True,
                sources=[],
            )

    # 8. 阶段 3: Tool 调用（plan-intent 才执行；包在 tool span 里）
    template_suggestions: list[dict] = []
    if intent == "plan":
        with span("tool", intent=intent, conversation_id=conv.id, user_id=current_user.id) as s_tool:
            tool_goal: str | None = None
            if result.tool_calls:
                for tc in result.tool_calls:
                    if tc.get("name") == "recommend_templates":
                        args = tc.get("arguments") or {}
                        if isinstance(args.get("goal"), str):
                            tool_goal = args["goal"]
                        break
            s_tool.input_preview = "recommend_templates(goal=?)"
            s_tool.meta["tool_call_count"] = len(result.tool_calls or [])
            s_tool.meta["tool_goal"] = tool_goal

            if tool_goal:
                template_suggestions = await _fetch_template_suggestions_by_goal(
                    session, goal=tool_goal, limit=3
                )
            if not template_suggestions:
                template_suggestions = await _fetch_template_suggestions(session, body.content)

            s_tool.output_preview = f"{len(template_suggestions)} suggestions"
            s_tool.meta["suggestion_count"] = len(template_suggestions)

    # 9. LLM 调工具时可能没返回文本（content 为空），统一替换为导语，避免 LLM 幻觉模板名
    if template_suggestions:
        ai_intro = _build_plan_intro(tool_goal if intent == "plan" else None, len(template_suggestions))
        # 注意：result.content 在 tool span 之前已经写入 llm span.output_preview
        # 这里只更新 ai_msg 文本
    else:
        ai_intro = result.content

    # 10. 阶段 6: Output（持久化 AI 消息）
    ai_msg = Message(
        conversation_id=conv.id,
        sender_type="ai",
        content=ai_intro,
        intent=intent,
        extra={
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "total_tokens": result.total_tokens,
            "latency_ms": result.latency_ms,
            "model": result.model,
            "rag_sources": [
                {
                    "id": c.id,
                    "name_zh": c.name_zh,
                    "name_en": c.name_en,
                    "body_part": c.body_part,
                    "equipment": c.equipment,
                    "score": round(c.score, 4),
                }
                for c in rag_chunks
            ],
            "kb_sources": [
                {
                    "doc_id": c.doc_id,
                    "filename": c.filename,
                    "chunk_index": c.chunk_index,
                    "score": round(c.score, 4),
                }
                for c in kb_chunks
            ],
            # template_suggestions 下方填充
        },
    )
    session.add(ai_msg)

    # 11. 自动更新会话标题（首条消息）
    if conv.title in (None, "", "新会话") and intent:
        conv.title = body.content.strip().splitlines()[0][:30]

    if template_suggestions:
        ai_msg.extra["template_suggestions"] = template_suggestions
        await session.flush()

    with span("output", intent=intent, conversation_id=conv.id, user_id=current_user.id) as s_out:
        s_out.input_preview = f"intent={intent} llm_tokens={result.total_tokens}"
        await session.commit()
        await session.refresh(ai_msg)
        s_out.output_preview = "saved"
        s_out.meta["message_id"] = ai_msg.id
        s_out.meta["template_suggestions_count"] = len(template_suggestions)

    return ChatMessageOut(
        conversation_id=conv.id,
        message_id=ai_msg.id,
        sender_type="ai",
        content=ai_intro,
        intent=intent,
        done=True,
        sources=[
            {
                "id": c.id,
                "name_zh": c.name_zh,
                "name_en": c.name_en,
                "body_part": c.body_part,
                "equipment": c.equipment,
            }
            for c in rag_chunks
        ],
        extra={
            "template_suggestions": template_suggestions,
            "kb_sources": [
                {
                    "doc_id": c.doc_id,
                    "filename": c.filename,
                    "chunk_index": c.chunk_index,
                    "score": round(c.score, 4),
                }
                for c in kb_chunks
            ],
        },
    )


async def _fetch_template_suggestions_by_goal(
    session: AsyncSession, goal: str, limit: int = 3
) -> list[dict]:
    """LLM 工具调用路径：按显式 goal 查 published 模板。

    与 _fetch_template_suggestions 区别：传入的 goal 来自 LLM 的工具参数（已经过 LLM 推断），
    不再走关键词匹配，直接 DB 查询。
    """
    from app.db.models import PlanTemplate

    if goal not in {"muscle_gain", "fat_loss", "body_shape", "endurance"}:
        return []

    rows = (await session.execute(
        select(PlanTemplate)
        .where(PlanTemplate.status == "published", PlanTemplate.goal == goal)
        .order_by(PlanTemplate.use_count.desc(), PlanTemplate.id.desc())
        .limit(limit)
    )).scalars().all()

    return _templates_to_suggestions(rows)


def _templates_to_suggestions(rows) -> list[dict]:
    return [
        {
            "id": t.id,
            "name": t.name,
            "goal": t.goal,
            "level": t.level,
            "cover_url": t.cover_url,
            "description": (t.description or "")[:120],
            "use_count": t.use_count,
            "avg_rating": float(t.avg_rating or 0),
            "weeks_count": len(t.weeks or []),
        }
        for t in rows
    ]


async def _fetch_template_suggestions(
    session: AsyncSession, user_text: str, limit: int = 3
) -> list[dict]:
    """从 published 模板市场筛 3 条与用户目标相关的模板。

    优先级：goal 匹配 > 全部 published 中 use_count 最高。
    模板市场走的是另一只读 router（plan_templates.py），这里内联实现避免跨 router 复用。
    """
    from app.db.models import PlanTemplate  # 局部 import 防止循环

    # 关键词 → goal 枚举（与 INTENT_KEYWORDS 共用思路）
    text = user_text.lower()
    goal_hint: str | None = None
    if any(kw in text or kw.lower() in text for kw in ["增肌", "肌", "力量", "肌肉"]):
        goal_hint = "muscle_gain"
    elif any(kw in text or kw.lower() in text for kw in ["减脂", "瘦身", "燃脂", "减肥"]):
        goal_hint = "fat_loss"
    elif any(kw in text or kw.lower() in text for kw in ["塑形", "线条", "体态"]):
        goal_hint = "body_shape"
    elif any(kw in text or kw.lower() in text for kw in ["体能", "耐力", "心肺", "跑步"]):
        goal_hint = "endurance"

    q = select(PlanTemplate).where(PlanTemplate.status == "published")
    if goal_hint:
        q = q.where(PlanTemplate.goal == goal_hint)
    q = q.order_by(PlanTemplate.use_count.desc(), PlanTemplate.id.desc()).limit(limit)
    rows = (await session.execute(q)).scalars().all()

    # 如果按 goal 没匹配到，放宽到全部 published
    if not rows:
        rows = (await session.execute(
            select(PlanTemplate)
            .where(PlanTemplate.status == "published")
            .order_by(PlanTemplate.use_count.desc(), PlanTemplate.id.desc())
            .limit(limit)
        )).scalars().all()

    return _templates_to_suggestions(rows)


# ============ 流式发送（SSE）============

def _sse(payload: dict) -> dict:
    """统一 SSE 事件格式。

    ponytail: 必须 json.dumps —— sse-starlette 拿到 dict 时会 str() 化（Python repr，单引号），
    前端 JSON.parse 直接挂，UI 不更新。
    """
    return {"event": "message", "data": json.dumps(payload, ensure_ascii=False)}


@router.post("/chat/send/stream", summary="发送消息并以 SSE 流式获取 AI 回复")
@limiter.limit(settings.ai_user_minute_limit)
@limiter.limit(settings.ai_user_daily_limit)
async def send_message_stream(
    request: Request,
    body: ChatMessageIn,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EventSourceResponse:
    """流式端点：先用一段 metadata 告诉前端 conversation_id，然后逐 chunk 推 delta，最后推 done。

    ponytail: 复用 send_message 的逻辑太多，单独走一份精简流程；后续可重构共享 helper。
    """
    # 1. 取或创建会话
    if body.conversation_id:
        conv = await session.execute(
            select(Conversation).where(
                Conversation.id == body.conversation_id,
                Conversation.user_id == current_user.id,
            )
        )
        conv = conv.scalar_one_or_none()
        if not conv:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    else:
        title = body.content.strip().splitlines()[0][:30] if body.content.strip() else "新会话"
        conv = Conversation(user_id=current_user.id, title=title)
        session.add(conv)
        await session.flush()

    # 2. 存用户消息
    user_msg = Message(
        conversation_id=conv.id,
        sender_type="user",
        sender_id=current_user.id,
        content=body.content,
    )
    session.add(user_msg)
    await session.commit()  # 先把用户消息落库

    # ============ M10+ 6 阶段埋点（流式）============

    # 阶段 1: Query 改写
    with span("query_rewrite", conversation_id=conv.id, user_id=current_user.id) as s_qr:
        s_qr.input_preview = body.content
        rewritten = _simple_rewrite(body.content)
        s_qr.output_preview = rewritten
        s_qr.meta["rewritten"] = rewritten != body.content

    # 阶段 2: 意图识别
    with span("intent", conversation_id=conv.id, user_id=current_user.id) as s_intent:
        s_intent.input_preview = rewritten
        intent = _detect_intent(rewritten)
        s_intent.output_preview = intent
        s_intent.intent = intent

    # 阶段 4: RAG 检索
    rag_chunks: list[RagChunk] = []
    if intent in ("qa", "substitute", "plan"):
        with span("rag", intent=intent, conversation_id=conv.id, user_id=current_user.id) as s_rag:
            s_rag.input_preview = rewritten
            try:
                rag_chunks = await retrieve(rewritten, top_k=3)
            except RAGError as e:
                logger.warning("RAG 检索失败，降级跳过：{}", e)
                s_rag.meta["error"] = str(e)[:200]
            s_rag.output_preview = f"{len(rag_chunks)} chunks"
            s_rag.meta["chunk_ids"] = [c.id for c in rag_chunks]

    # 阶段 3.5: KB 检索（流式路径）
    kb_chunks = []
    if getattr(body, "use_kb", True) and intent in ("qa", "substitute", "diet"):
        try:
            from app.db.models import KnowledgeBase
            from app.services.kb_service import retrieve_from_all
            kbs = (await session.execute(
                select(KnowledgeBase).where(KnowledgeBase.enabled == True)
            )).scalars().all()
            kb_chunks = await retrieve_from_all(rewritten, kbs)
        except Exception as e:
            logger.warning(f"KB 检索失败（不影响主流程）：{e}")

    # 4. 历史 + RAG context + KB context
    history = await _build_history(session, conv.id, max_rounds=5)
    if history and history[-1]["role"] == "user" and history[-1]["content"] == body.content:
        history = history[:-1]
    if rag_chunks:
        history.insert(0, {"role": "system", "content": to_prompt_context(rag_chunks)})
    if kb_chunks:
        from app.services.kb_service import format_kb_context
        history.insert(0, {"role": "system", "content": format_kb_context(kb_chunks)})
    messages = history + [{"role": "user", "content": rewritten if rewritten else body.content}]

    conv_id = conv.id
    sources_payload = [
        {
            "id": c.id,
            "name_zh": c.name_zh,
            "name_en": c.name_en,
            "body_part": c.body_part,
            "equipment": c.equipment,
        }
        for c in rag_chunks
    ]

    # 计划意图：查真实模板建议（非流式路径走 LLM 工具，流式走关键词兜底——见 SSE done 段）
    template_suggestions: list[dict] = []

    async def event_gen() -> AsyncIterator[dict]:
        # 先告诉前端 conversation_id（用户消息已存库）
        yield _sse({"type": "meta", "conversation_id": conv_id, "intent": intent, "sources": sources_payload})

        # ============ M10+ 6 阶段埋点（流式）============
        # 阶段 5: LLM 流式生成 — 包裹整段 stream
        full = ""
        try:
            with span("llm", intent=intent, conversation_id=conv_id, user_id=current_user.id) as s_llm:
                s_llm.input_preview = (messages[-1]["content"] if messages else "")[:200]
                async for ev in llm_service.stream_chat(
                    messages,
                    user_id=current_user.id,
                    conversation_id=conv_id,
                    intent=intent,
                ):
                    if ev["type"] == "delta":
                        full += ev["text"]
                        s_llm.meta["delta_count"] = s_llm.meta.get("delta_count", 0) + 1
                        yield _sse({"type": "delta", "text": ev["text"]})
                    elif ev["type"] == "done":
                        s_llm.tokens = {
                            "prompt": ev["prompt_tokens"],
                            "completion": ev["completion_tokens"],
                            "total": ev["total_tokens"],
                        }
                        s_llm.output_preview = (ev["content"] or "")[:200]
                        s_llm.meta["model"] = ev["model"]
                        s_llm.meta["latency_ms"] = ev["latency_ms"]

                        # 阶段 3: Tool（流式不走 LLM 工具，关键词查）
                        ts: list[dict] = []
                        if intent == "plan":
                            with span("tool", intent=intent, conversation_id=conv_id, user_id=current_user.id) as s_tool:
                                async with async_session() as ts_sess:
                                    ts = await _fetch_template_suggestions(ts_sess, body.content)
                                s_tool.meta["suggestion_count"] = len(ts)
                                s_tool.output_preview = f"{len(ts)} suggestions"

                        # 阶段 6: Output（持久化 AI 消息）
                        with span("output", intent=intent, conversation_id=conv_id, user_id=current_user.id) as s_out:
                            async with async_session() as s:
                                ai_msg = Message(
                                    conversation_id=conv_id,
                                    sender_type="ai",
                                    content=ev["content"],
                                    intent=intent,
                                    extra={
                                        "prompt_tokens": ev["prompt_tokens"],
                                        "completion_tokens": ev["completion_tokens"],
                                        "total_tokens": ev["total_tokens"],
                                        "latency_ms": ev["latency_ms"],
                                        "model": ev["model"],
                                        "rag_sources": sources_payload,
                                        "streamed": True,
                                        "template_suggestions": ts,
                                        "kb_sources": [
                                            {"doc_id": c.doc_id, "filename": c.filename,
                                             "chunk_index": c.chunk_index, "score": round(c.score, 4)}
                                            for c in kb_chunks
                                        ],
                                    },
                                )
                                s.add(ai_msg)
                                await s.commit()
                                await s.refresh(ai_msg)
                                ai_msg_id = ai_msg.id
                            s_out.meta["message_id"] = ai_msg_id
                            s_out.meta["template_suggestions_count"] = len(ts)
                            s_out.output_preview = f"saved msg#{ai_msg_id}"
                        template_suggestions = ts

                        # 自动更新标题
                        if conv.title in (None, "", "新会话"):
                            async with async_session() as s:
                                cv = await s.get(Conversation, conv_id)
                                if cv:
                                    cv.title = body.content.strip().splitlines()[0][:30]
                                    await s.commit()

                        yield _sse({
                            "type": "done",
                            "conversation_id": conv_id,
                            "message_id": ai_msg_id,
                            "content": ev["content"],
                            "intent": intent,
                            "sources": sources_payload,
                            "template_suggestions": template_suggestions,
                            "kb_sources": [
                                {"doc_id": c.doc_id, "filename": c.filename,
                                 "chunk_index": c.chunk_index, "score": round(c.score, 4)}
                                for c in kb_chunks
                            ],
                        })
        except Exception as e:
            logger.exception("流式 LLM 调用失败：{}", e)
            # 把已收到的部分存下来作为 ai 消息
            err_text = full + f"\n\n⚠️ AI 服务中断：{str(e)[:120]}"
            async with async_session() as s:
                ai_msg = Message(
                    conversation_id=conv_id,
                    sender_type="ai",
                    content=err_text,
                    intent=intent,
                    extra={"error": str(e)[:200], "partial": True, "streamed": True},
                )
                s.add(ai_msg)
                await s.commit()
                await s.refresh(ai_msg)
                ai_msg_id = ai_msg.id

            yield _sse({
                "type": "error",
                "conversation_id": conv_id,
                "message_id": ai_msg_id,
                "content": err_text,
                "error": str(e)[:200],
            })

    return EventSourceResponse(event_gen())


# ============ 转教练（M8）============

@router.post(
    "/conversations/{conv_id}/transfer-to-trainer",
    summary="C 端：转教练（用户主动触发）",
)
async def user_transfer_to_trainer(
    conv_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """把会话状态切到 waiting_trainer，等待教练接入。幂等。"""
    conv = await session.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.user_id == current_user.id,
        )
    )
    conv = conv.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    if conv.status in ("waiting_trainer", "trainer_active"):
        return {
            "conversation_id": conv.id,
            "status": conv.status,
            "message": "已在排队中" if conv.status == "waiting_trainer" else "教练已接入",
        }

    conv.status = "waiting_trainer"
    conv.conversation_type = "trainer"
    await session.commit()
    logger.info("用户 {} 把会话 {} 转教练", current_user.id, conv_id)
    return {
        "conversation_id": conv.id,
        "status": conv.status,
        "conversation_type": conv.conversation_type,
        "assigned_trainer_id": None,
        "message": "已提交，等待教练接入",
    }
