"""回填 ai_call_logs 老日志的 cost_cny（用当前 LLM 配置的 pricing 计算）。

背景：迁移 0009 给 cost_cny 加列时 server_default='0'，迁移前写入的记录是 0。
跑完不影响新调用（新调用 _log_call 已经自己算 cost）。

用法：python -m app.db.backfill_ai_cost
"""

import asyncio

from loguru import logger
from sqlalchemy import select, update

from app.db.models import AiCallLog
from app.db.session import async_session
from app.services.llm_service import _cost_per_1k


async def backfill() -> None:
    async with async_session() as s:
        rows = (await s.execute(
            select(AiCallLog.id, AiCallLog.model, AiCallLog.total_tokens, AiCallLog.cost_cny)
            .where(AiCallLog.cost_cny == 0, AiCallLog.total_tokens > 0)
        )).all()

        if not rows:
            logger.info("没有需要回填的记录")
            return

        logger.info("准备回填 {} 条历史日志", len(rows))
        updated = 0
        cache: dict[str, float] = {}

        for rid, model, toks, _old_cost in rows:
            if model not in cache:
                cache[model] = await _cost_per_1k(model)
            per_1k = cache[model]
            new_cost = round((toks / 1000.0) * per_1k, 6)

            await s.execute(
                update(AiCallLog).where(AiCallLog.id == rid).values(cost_cny=new_cost)
            )
            updated += 1

        await s.commit()
        logger.success("回填完成：{} 条 (model price 缓存: {})", updated, cache)


if __name__ == "__main__":
    asyncio.run(backfill())