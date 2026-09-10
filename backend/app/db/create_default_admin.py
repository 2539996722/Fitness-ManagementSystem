"""创建默认管理员账号（仅当 users 表为空）。

执行方式：
    python -m app.db.create_default_admin

特性：
- 幂等：仅当 users 表无记录时执行
- 账号密码从 .env 读取 DEFAULT_ADMIN_USERNAME / DEFAULT_ADMIN_PASSWORD
"""

import asyncio
import sys

from loguru import logger
from sqlalchemy import func, select

from app.core.config import settings
from app.core.security import hash_password
from app.db.models import User
from app.db.session import async_session


async def create_admin() -> None:
    async with async_session() as session:
        # 检查是否已有用户
        result = await session.execute(select(func.count()).select_from(User))
        count = result.scalar() or 0

        if count > 0:
            logger.warning("⚠️ users 表已有 {} 条记录，跳过创建", count)
            return

        # 创建默认管理员
        admin = User(
            username=settings.default_admin_username,
            password_hash=hash_password(settings.default_admin_password),
            nickname="系统管理员",
            role="admin",
            status=0,
        )
        session.add(admin)

        try:
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error("创建管理员失败：{}", e)
            sys.exit(1)

        await session.refresh(admin)
        logger.info("✅ 默认管理员已创建")
        logger.info("   用户名: {}", admin.username)
        logger.info("   密码:   {}", settings.default_admin_password)
        logger.warning("   ⚠️ 首次登录后必须修改密码！")


if __name__ == "__main__":
    asyncio.run(create_admin())