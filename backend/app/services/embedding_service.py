"""Embedding 服务。

- 复用 llm_service._get_client 的 SSL 修复（Windows OCSP/CRL）
- 走 OpenAI 兼容 /v1/embeddings（默认）
- 适配 MiniMax provider：model=embo-01，用 texts+type=db，响应是 vectors 字段
- embed_query: 单条文本 → list[float]
- embed_documents: 批量文本 → list[list[float]]
- 调用后写 ai_call_logs（call_type=embedding）便于成本/用量分析
"""

from __future__ import annotations

from loguru import logger

from app.services.llm_service import load_llm_config, _get_client


async def embed_query(text: str) -> list[float]:
    """单条文本嵌入。"""
    return (await embed_documents([text]))[0]


async def embed_documents(texts: list[str]) -> list[list[float]]:
    """批量嵌入。"""
    if not texts:
        return []
    cfg = await load_llm_config()
    client = _get_client(cfg["api_base"], cfg["api_key"])
    model = cfg.get("model_embed") or "text-embedding-3-small"

    cleaned = [(t if t and t.strip() else "（无内容）") for t in texts]

    # MiniMax provider 走专用协议
    api_base = cfg.get("api_base", "").lower()
    is_minimax = "minimax" in api_base or model.startswith("embo-")
    if is_minimax:
        return await _embed_minimax(client, model, cleaned, cfg)

    # 标准 OpenAI 协议
    try:
        resp = await client.embeddings.create(model=model, input=cleaned)
    except Exception as e:
        logger.exception("embedding 调用失败：{}", e)
        raise

    await _log_embedding_openai(model, resp, len(cleaned), cfg)
    return [d.embedding for d in resp.data]


async def _embed_minimax(client, model: str, texts: list[str], cfg: dict) -> list[list[float]]:
    """MiniMax embo-01 协议：POST /v1/embeddings body={model, texts, type='db'}，响应={vectors: [[...]]}。"""
    base_url = str(client.base_url).rstrip("/")
    url = f"{base_url}/embeddings"
    headers = {"Authorization": f"Bearer {cfg.get('api_key', '')}", "Content-Type": "application/json"}
    payload = {"model": model, "texts": texts, "type": "db"}

    # 拿到 httpx.AsyncClient（openai SDK 内部）
    http_client = client._client
    resp = await http_client.post(url, json=payload, headers=headers)
    if resp.status_code != 200:
        logger.error(f"MiniMax embedding HTTP {resp.status_code}: {resp.text[:300]}")
        raise RuntimeError(f"MiniMax embedding failed: HTTP {resp.status_code} - {resp.text[:200]}")
    body = resp.json()
    vectors = body.get("vectors") or []
    if not vectors:
        raise RuntimeError(f"MiniMax embedding returned empty vectors: {body}")
    await _log_embedding_minimax(model, len(texts), len(vectors[0]) if vectors else 0, cfg)
    return [list(v) for v in vectors]


async def _log_embedding_openai(model: str, resp, batch_size: int, cfg: dict):
    try:
        from app.services import llm_service
        usage = getattr(resp, "usage", None)
        total_tokens = int(getattr(usage, "total_tokens", 0)) if usage else 0
        prompt_tokens = int(getattr(usage, "prompt_tokens", total_tokens)) if usage else total_tokens
        cost_per_1k = float((cfg.get("pricing") or {}).get(model, 0.0001))
        cost = round((total_tokens / 1000.0) * cost_per_1k, 6)
        await llm_service._log_call(
            user_id=None,
            conversation_id=None,
            intent="embedding",
            result=llm_service.LLMCallResult(
                content="",
                prompt_tokens=prompt_tokens,
                completion_tokens=0,
                total_tokens=total_tokens,
                latency_ms=0,
                model=model,
                intent="embedding",
            ),
            prompt_preview=f"batch_size={batch_size}",
            call_type="embedding",
            extra_cost_cny=cost,
        )
    except Exception as e:
        logger.warning(f"embedding 记账失败：{e}")


async def _log_embedding_minimax(model: str, batch_size: int, dim: int, cfg: dict):
    """MiniMax 路径记账（粗略估算 token 数）。"""
    try:
        from app.services import llm_service
        # MiniMax 不返回 token 数；按字符数 / 4 粗估（中文一般 1.5 字符/token）
        total_tokens = max(1, batch_size * 200)
        cost_per_1k = float((cfg.get("pricing") or {}).get(model, 0.0001))
        cost = round((total_tokens / 1000.0) * cost_per_1k, 6)
        await llm_service._log_call(
            user_id=None,
            conversation_id=None,
            intent="embedding",
            result=llm_service.LLMCallResult(
                content="",
                prompt_tokens=total_tokens,
                completion_tokens=0,
                total_tokens=total_tokens,
                latency_ms=0,
                model=model,
                intent="embedding",
            ),
            prompt_preview=f"batch_size={batch_size} dim={dim}",
            call_type="embedding",
            extra_cost_cny=cost,
        )
    except Exception as e:
        logger.warning(f"embedding 记账失败：{e}")