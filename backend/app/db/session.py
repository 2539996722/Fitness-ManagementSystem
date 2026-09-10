"""数据库 Session 管理。

使用 SQLAlchemy 2.x 异步引擎。

典型用法：
    from app.db.session import async_session

    async with async_session() as session:
        result = await session.execute(select(Exercise))
        exercises = result.scalars().all()
"""

from collections.abc import AsyncIterator

from loguru import logger
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings


def build_engine() -> AsyncEngine:
    """构造异步引擎。

    注意：DSN 已经包含 charset=utf8mb4（由 config 校验）。
    """
    engine = create_async_engine(
        settings.mysql_dsn,
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        pool_recycle=3600,  # 1 小时回收，避免 MySQL wait_timeout
    )
    logger.info("🗄️ 数据库引擎已创建 | pool_size={}", settings.db_pool_size)
    return engine


# 全局单例
engine: AsyncEngine = build_engine()

# Session 工厂
async_session: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：注入异步 Session。

    使用：
        @router.get("/items")
        async def list_items(session: AsyncSession = Depends(get_session)):
            ...
    """
    async with async_session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()