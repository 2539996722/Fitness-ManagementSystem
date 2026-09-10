"""健康检查接口。"""

import time

from fastapi import APIRouter, status
from sqlalchemy import text

from app.db.session import async_session

router = APIRouter()

_START_TIME = time.time()


@router.get("/", status_code=status.HTTP_200_OK, summary="健康检查")
async def health_check():
    """返回服务状态、运行时间、数据库连通性。

    容器健康检查调用此接口。
    """
    db_ok = False
    db_error = None
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception as e:
        db_error = str(e)

    return {
        "status": "ok" if db_ok else "degraded",
        "uptime_seconds": round(time.time() - _START_TIME, 2),
        "database": {
            "ok": db_ok,
            "error": db_error,
        },
        "version": "0.1.0",
    }