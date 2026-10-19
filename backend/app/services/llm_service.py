"""LLM 服务封装。

- 读取 SystemConfig('llm') 行的运行时配置
- 缺省字段回退到 .env 中的 LLM_API_BASE / LLM_API_KEY / ...
- 所有调用走 OpenAI 兼容协议（/v1/chat/completions）
- 自动写入 ai_call_logs（PRD §3.3）
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger
import json
from sqlalchemy import select

from app.core.config import settings
from app.db.models import AiCallLog, Message, SystemConfig
from app.db.session import async_session

if TYPE_CHECKING:
    from openai import AsyncOpenAI


DEFAULT_SYSTEM_PROMPT = (
    "你是 FitHub 的 AI 健身教练 FitCoach，专业、友好、循证。"
    "请用简洁的中文回答，必要时给出可执行的训练建议。"
)


@dataclass
class LLMCallResult:
    """LLM 调用结果（含计量）。"""

    content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int
    model: str
    intent: str = "qa"
    tool_calls: list[dict] | None = None  # OpenAI function-calling 工具调用请求


# 缓存客户端实例（按 api_base+api_key 区分）
_client_cache: dict[tuple[str, str], "AsyncOpenAI"] = {}


def _get_client(api_base: str, api_key: str) -> "AsyncOpenAI":
    """懒加载 OpenAI 客户端。

    关键修复：使用自定义 httpx 客户端，关闭 Windows OCSP/CRL 检查。
    部分国产 LLM 域名（如 minimax）的证书 OCSP 服务器在国内访问不稳定，
    Windows 默认会触发 OCSP 校验并报 CRYPT_E_REVOCATION_OFFLINE。
    """
    from openai import AsyncOpenAI

    key = (api_base, api_key)
    if key not in _client_cache:
        try:
            import httpx
            import ssl

            # 自定义 SSL context：禁用 CRL/OCSP 检查
            ssl_ctx = ssl.create_default_context()
            # 关键：禁用 X509 严格模式（Windows 默认行为）
            if hasattr(ssl_ctx, "verify_flags"):
                # Python 3.10+ 支持
                ssl_ctx.verify_flags &= ~ssl.VERIFY_CRL_CHECK_CHAIN
                ssl_ctx.verify_flags &= ~ssl.VERIFY_CRL_CHECK_LEAF
                ssl_ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT

            http_client = httpx.AsyncClient(
                verify=ssl_ctx,
                http2=False,
                timeout=settings.llm_timeout,
            )
            _client_cache[key] = AsyncOpenAI(
                base_url=api_base,
                api_key=api_key,
                timeout=settings.llm_timeout,
                max_retries=settings.llm_max_retries,
                http_client=http_client,
            )
        except Exception as e:
            logger.warning("创建自定义 httpx 客户端失败，回退默认：{}", e)
            _client_cache[key] = AsyncOpenAI(
                base_url=api_base,
                api_key=api_key,
                timeout=settings.llm_timeout,
                max_retries=settings.llm_max_retries,
            )
    return _client_cache[key]


async def close_http_client(api_base: str, api_key: str) -> None:
    """关闭并移除指定 (api_base, api_key) 对应的 httpx 客户端。

    用途：SSE 客户端断连时，强制关闭上游 LLM 的 HTTP 连接，避免 token 继续扣费。
    下次调用 _get_client() 会重新创建。
    """
    import httpx

    key = (api_base, api_key)
    client = _client_cache.pop(key, None)
    if client is None:
        return
    # 自定义 httpx client 路径：client._client 是 AsyncClient 实例
    http_client = getattr(client, "_client", None) or getattr(client, "http_client", None)
    if http_client is not None and isinstance(http_client, httpx.AsyncClient):
        try:
            await http_client.aclose()
        except Exception as e:
            logger.warning("关闭 LLM httpx client 失败：{}", e)


async def load_llm_config() -> dict[str, Any]:
    """从 DB 加载 LLM 配置，缺省回退 .env。

    首次访问时自动 seed 默认行（避免空表导致 schema 校验失败）。
    """
    async with async_session() as session:
        result = await session.execute(
            select(SystemConfig).where(SystemConfig.key == "llm")
        )
        cfg = result.scalar_one_or_none()
        if cfg is None:
            cfg = SystemConfig(
                key="llm",
                value={
                    "api_base": "",
                    "api_key": "",
                    "model_chat": settings.llm_model_chat,
                    "model_embed": settings.llm_model_embed,
                    "temperature": 0.7,
                    "max_tokens": 2048,
                    "timeout": settings.llm_timeout,
                    "system_prompt": DEFAULT_SYSTEM_PROMPT,
                },
                description="LLM 模型配置（OpenAI 兼容协议）",
            )
            session.add(cfg)
            await session.commit()
            await session.refresh(cfg)

    base: dict[str, Any] = {
        "api_base": settings.llm_api_base,
        "api_key": settings.llm_api_key,
        "model_chat": settings.llm_model_chat,
        "model_embed": settings.llm_model_embed,
        "temperature": 0.7,
        "max_tokens": 2048,
        "timeout": settings.llm_timeout,
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
        "pricing": {"gpt-4o-mini": 0.001, "gpt-4o": 0.05, "text-embedding-3-small": 0.0001},
    }
    if cfg and isinstance(cfg.value, dict):
        # DB 字段非空时覆盖默认值（注意：空字符串视为"用户主动清空"，不回退）
        for k in base:
            v = cfg.value.get(k)
            if v not in (None, ""):
                base[k] = v
    return base


async def _cost_per_1k(model: str) -> float:
    """按模型名取每 1k token 人民币成本，未匹配回退 0.001。"""
    try:
        cfg = await load_llm_config()
        pricing = cfg.get("pricing") or {}
        return float(pricing.get(model) or 0.001)
    except Exception:
        return 0.001


async def save_llm_config(updates: dict[str, Any], updated_by: int | None = None) -> dict[str, Any]:
    """更新 LLM 配置。"""
    async with async_session() as session:
        result = await session.execute(
            select(SystemConfig).where(SystemConfig.key == "llm")
        )
        cfg = result.scalar_one_or_none()

        if cfg is None:
            cfg = SystemConfig(
                key="llm",
                value={},
                description="LLM 模型配置（OpenAI 兼容协议）",
            )
            session.add(cfg)

        # 合并更新
        current = dict(cfg.value or {})
        for k, v in updates.items():
            if v is None:
                continue
            current[k] = v
        cfg.value = current
        if updated_by is not None:
            cfg.updated_by = updated_by

        await session.commit()
        await session.refresh(cfg)

        # 清掉客户端缓存（下次调用按新配置重建）
        _client_cache.clear()
        return dict(cfg.value)


async def chat(
    messages: list[dict[str, str]],
    *,
    user_id: int | None = None,
    conversation_id: int | None = None,
    intent: str = "qa",
    temperature: float | None = None,
    max_tokens: int | None = None,
    tools: list[dict] | None = None,
    tool_choice: str | dict | None = None,
) -> LLMCallResult:
    """调用对话模型。

    messages: [{"role": "system"|"user"|"assistant", "content": "..."}]
    tools:     可选 OpenAI function-calling 工具定义列表
    tool_choice: "auto" / "none" / {"type":"function","function":{"name":"..."}}
                None 表示不传（部分 LLM 不支持 tools 时静默忽略）
    """
    cfg = await load_llm_config()
    client = _get_client(cfg["api_base"], cfg["api_key"])

    sys_msg = cfg.get("system_prompt") or "你是 FitHub 的 AI 健身教练 FitCoach。"
    final_messages = [{"role": "system", "content": sys_msg}] + messages

    model = cfg["model_chat"]
    temp = temperature if temperature is not None else float(cfg.get("temperature", 0.7))
    mx = max_tokens if max_tokens is not None else int(cfg.get("max_tokens", 2048))
    prompt_preview = final_messages[-1]["content"][:200] if final_messages else ""

    create_kwargs: dict = {
        "model": model,
        "messages": final_messages,  # type: ignore[arg-type]
        "temperature": temp,
        "max_tokens": mx,
    }
    if tools:
        create_kwargs["tools"] = tools
        if tool_choice is not None:
            create_kwargs["tool_choice"] = tool_choice

    start = time.monotonic()
    try:
        resp = await client.chat.completions.create(**create_kwargs)
    except Exception as e:
        logger.exception("LLM 调用失败：{}", e)
        err_result = LLMCallResult(
            content="",
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            latency_ms=int((time.monotonic() - start) * 1000),
            model=model,
            intent=intent,
        )
        asyncio.create_task(
            _log_call(
                user_id=user_id,
                conversation_id=conversation_id,
                intent=intent,
                result=err_result,
                prompt_preview=prompt_preview,
                status="error",
                error_message=str(e)[:500],
            )
        )
        raise

    latency_ms = int((time.monotonic() - start) * 1000)
    msg = resp.choices[0].message
    content = msg.content or ""

    # 工具调用抽取（OpenAI 标准 function-calling 格式）
    tool_calls: list[dict] = []
    if getattr(msg, "tool_calls", None):
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            tool_calls.append(
                {
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": args,
                }
            )

    usage = resp.usage
    result = LLMCallResult(
        content=content,
        prompt_tokens=usage.prompt_tokens if usage else 0,
        completion_tokens=usage.completion_tokens if usage else 0,
        total_tokens=usage.total_tokens if usage else 0,
        latency_ms=latency_ms,
        model=model,
        intent=intent,
        tool_calls=tool_calls or None,
    )

    # 异步记账
    asyncio.create_task(
        _log_call(
            user_id=user_id,
            conversation_id=conversation_id,
            intent=intent,
            result=result,
            prompt_preview=prompt_preview,
        )
    )
    return result


async def stream_chat(
    messages: list[dict[str, str]],
    *,
    user_id: int | None = None,
    conversation_id: int | None = None,
    intent: str = "qa",
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> Any:
    """流式调用对话模型。

    返回异步生成器：yield 增量文本字符串 + 最后 yield 一个 dict（含 usage / latency / model）。

    ponytail: 不在这里记账（usage 不一定能在 stream 末尾拿到），由调用方在流结束后读 final dict 再写 ai_call_logs。
    """
    cfg = await load_llm_config()
    client = _get_client(cfg["api_base"], cfg["api_key"])

    sys_msg = cfg.get("system_prompt") or "你是 FitHub 的 AI 健身教练 FitCoach。"
    final_messages = [{"role": "system", "content": sys_msg}] + messages

    model = cfg["model_chat"]
    temp = temperature if temperature is not None else float(cfg.get("temperature", 0.7))
    mx = max_tokens if max_tokens is not None else int(cfg.get("max_tokens", 2048))
    prompt_preview = final_messages[-1]["content"][:200] if final_messages else ""

    start = time.monotonic()
    try:
        stream = await client.chat.completions.create(
            model=model,
            messages=final_messages,  # type: ignore[arg-type]
            temperature=temp,
            max_tokens=mx,
            stream=True,
            stream_options={"include_usage": True},
        )
    except Exception as e:
        logger.exception("LLM 流式调用失败：{}", e)
        err_result = LLMCallResult(
            content="",
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            latency_ms=int((time.monotonic() - start) * 1000),
            model=model,
            intent=intent,
        )
        asyncio.create_task(
            _log_call(
                user_id=user_id,
                conversation_id=conversation_id,
                intent=intent,
                result=err_result,
                prompt_preview=prompt_preview,
                status="error",
                error_message=str(e)[:500],
            )
        )
        raise

    full_content = ""
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    async for chunk in stream:
        # 文本增量
        if chunk.choices:
            delta = chunk.choices[0].delta.content
            if delta:
                full_content += delta
                yield {"type": "delta", "text": delta}
        # usage 在最后一个 chunk（OpenAI stream_options.include_usage=True）
        if getattr(chunk, "usage", None):
            prompt_tokens = chunk.usage.prompt_tokens or 0
            completion_tokens = chunk.usage.completion_tokens or 0
            total_tokens = chunk.usage.total_tokens or 0

    latency_ms = int((time.monotonic() - start) * 1000)
    yield {
        "type": "done",
        "content": full_content,
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "latency_ms": latency_ms,
    }

    # 异步记账（仅当拿到 usage 时）
    if total_tokens > 0:
        asyncio.create_task(
            _log_call(
                user_id=user_id,
                conversation_id=conversation_id,
                intent=intent,
                result=LLMCallResult(
                    content=full_content,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    latency_ms=latency_ms,
                    model=model,
                    intent=intent,
                ),
                prompt_preview=final_messages[-1]["content"][:200] if final_messages else "",
            )
        )


async def test_connection(cfg_override: dict[str, Any] | None = None) -> dict[str, Any]:
    """测试 LLM 连通性。

    cfg_override: 临时覆盖配置（用表单里尚未保存的值测试）。
    """
    cfg = cfg_override or await load_llm_config()
    api_base = cfg.get("api_base") or settings.llm_api_base
    api_key = cfg.get("api_key") or settings.llm_api_key
    model = cfg.get("model_chat") or settings.llm_model_chat

    if not api_key:
        return {"ok": False, "message": "API Key 未配置", "model": model}

    client = _get_client(api_base, api_key)
    start = time.monotonic()
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=8,
            temperature=0,
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        return {
            "ok": True,
            "message": "连接成功",
            "latency_ms": latency_ms,
            "model": resp.model,
        }
    except Exception as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        logger.warning("LLM 测试连接失败：{}", e)
        return {
            "ok": False,
            "message": str(e)[:200] or "连接失败",
            "latency_ms": latency_ms,
            "model": model,
        }


async def _log_call(
    *,
    user_id: int | None,
    conversation_id: int | None,
    intent: str,
    result: LLMCallResult,
    prompt_preview: str,
    status: str = "success",
    error_message: str | None = None,
    call_type: str = "chat",
    extra_cost_cny: float | None = None,
) -> None:
    """异步写入 ai_call_logs（ORM）。落库失败不影响主流程。

    call_type: "chat" / "embedding"
    extra_cost_cny: 调用方已算好的成本（embedding 路径用；chat 路径让本函数算）
    """
    try:
        cost = extra_cost_cny if extra_cost_cny is not None else (
            (result.total_tokens / 1000.0) * await _cost_per_1k(result.model)
        )
        async with async_session() as session:
            session.add(
                AiCallLog(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    intent=intent,
                    model=result.model,
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                    total_tokens=result.total_tokens,
                    cost_cny=cost,
                    latency_ms=result.latency_ms,
                    status=status,
                    error_message=error_message,
                    prompt_preview=prompt_preview,
                    response_preview=(result.content or "")[:200],
                    call_type=call_type,
                )
            )
            await session.commit()
    except Exception as e:
        # ponytail: 日志落库失败不影响主流程；上层 catch 已处理业务异常
        logger.warning("ai_call_logs 写入失败（可忽略）：{}", e)
