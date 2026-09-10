"""种子客服账号（customer_service 角色）。

执行方式：
    python -m app.db.seed_cs

特性：
- 幂等：账号已存在则更新角色 + 重置密码；不存在则创建
- 默认账号：cs1 / cs123（密码重置）
- 同时支持多账号：传参 --users cs1:cs123,cs2:cs456
"""

import asyncio
import sys

from loguru import logger
from sqlalchemy import select

from app.core.security import hash_password
from app.db.models import User
from app.db.session import async_session


DEFAULT_CS = [
    {"username": "cs1", "password": "cs123", "nickname": "客服小张"},
]


async def seed_cs(users: list[dict] | None = None) -> None:
    users = users or DEFAULT_CS
    async with async_session() as session:
        for spec in users:
            username = spec["username"]
            password = spec["password"]
            nickname = spec.get("nickname") or username

            result = await session.execute(select(User).where(User.username == username))
            user = result.scalar_one_or_none()

            if user is None:
                user = User(
                    username=username,
                    password_hash=hash_password(password),
                    nickname=nickname,
                    role="customer_service",
                    status=0,
                )
                session.add(user)
                logger.info("✅ 创建客服账号：{} / {}", username, password)
            else:
                user.role = "customer_service"
                user.password_hash = hash_password(password)
                user.nickname = nickname
                logger.info("🔄 更新客服账号：{}", username)

        try:
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error("写入失败：{}", e)
            sys.exit(1)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--users",
        help="逗号分隔 username:password，例：cs1:cs123,cs2:cs456",
    )
    args = parser.parse_args()

    if args.users:
        parsed = []
        for kv in args.users.split(","):
            u, p = kv.split(":")
            parsed.append({"username": u.strip(), "password": p.strip()})
        asyncio.run(seed_cs(parsed))
    else:
        asyncio.run(seed_cs())
