"""操作日志服务（M9）。

提供 `record()` 异步写入助手：失败仅 loguru.warning，不抛异常，
避免审计日志的写入故障阻塞主流程。
"""

from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OperationLog, User
from app.db.session import async_session


async def record(
    *,
    session: AsyncSession | None = None,
    operator: User | None,
    action: str,
    target_type: str | None = None,
    target_id: str | int | None = None,
    summary: str | None = None,
    details: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    """写入一条操作日志。

    - 若调用方已持有 session（如在事务内），传 `session` 直接 add；提交由调用方负责。
    - 若调用方没有 session（最常见：从 endpoint 异步调），内部新开一个 session，独立 commit。

    写入失败 → loguru.warning，**不抛异常**。
    """
    target_id_str = str(target_id) if target_id is not None else None
    operator_name = None
    if operator is not None:
        operator_name = operator.nickname or operator.username

    log = OperationLog(
        operator_id=operator.id if operator else None,
        operator_role=operator.role if operator else "system",
        operator_name=operator_name,
        action=action,
        target_type=target_type,
        target_id=target_id_str,
        summary=(summary or "")[:255],
        details=details,
        ip=ip,
    )

    if session is not None:
        # 复用外层 session：add + commit（独立提交，不影响调用方之前的写入）。
        # ponytail: 如果调用方已在事务中且不愿被打断，请不要传 session，
        # 让 record() 自己开 session。
        try:
            session.add(log)
            await session.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "操作日志写入失败（复用 session）：action={} operator={} err={}",
                action,
                operator.id if operator else None,
                e,
            )
            try:
                await session.rollback()
            except Exception:
                pass
        return

    # 独立 session：写失败不影响主流程
    try:
        async with async_session() as s:
            s.add(log)
            await s.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning("操作日志写入失败：action={} operator={} err={}", action, operator.id if operator else None, e)


def get_client_ip(request) -> str | None:
    """从 Request 提取客户端 IP，X-Forwarded-For 优先。"""
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    if request.client and request.client.host:
        return request.client.host
    return None