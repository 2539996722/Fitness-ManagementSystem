"""把 exercises 表里的 1,324 个动作 embed 后写入 Chroma。

执行方式：
    python -m app.db.seed_rag

前置：
- 已经 python -m app.db.seed_exercises 把动作写进 MySQL
- 已经配置好 system_configs('llm').api_base / api_key / model_embed

特性：
- 幂等（Chroma upsert by id）
- 批量（默认 64 条 / 批，调 embed_documents 一次）
- 单批失败整体重试一次
"""

import asyncio
import sys

from loguru import logger

from app.services.rag_service import index_all, is_indexed


async def seed() -> None:
    start = asyncio.get_event_loop().time()

    if is_indexed():
        logger.info("⚠️ Chroma 集合已有数据，仍会覆盖式写入（upsert）。")
    else:
        logger.info("📭 Chroma 集合为空，开始首次索引。")

    try:
        written = await index_all(batch_size=64)
    except Exception as e:
        logger.exception("RAG 索引失败：{}", e)
        sys.exit(1)

    elapsed = asyncio.get_event_loop().time() - start
    logger.info("🎉 RAG 索引完成：写入 {} 条，耗时 {:.1f}s", written, elapsed)


if __name__ == "__main__":
    asyncio.run(seed())
