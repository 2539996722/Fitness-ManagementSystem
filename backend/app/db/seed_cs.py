"""种子教练账号（兼容旧名 seed_cs；M4 合并后 cs1 实际签 trainer 角色）。

执行方式：
    python -m app.db.seed_cs

特性：
- 兼容：账号已存在（任何角色）则保留并升级为 trainer
- 幂等：不存在则创建为 trainer
- ponytail: 历史 CS 角色已彻底清理（M12 #122）；跑这个脚本只会保留/创建 trainer 账号
"""

import asyncio
import sys

from loguru import logger
from sqlalchemy import select

from app.core.security import hash_password
from app.db.models import User
from app.db.session import async_session


DEFAULT_CS = [
    {"username": "cs1", "password": "cs123", "nickname": "教练小张"},
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
                    role="trainer",  # ponytail: 合并后直接签 trainer
                    status=0,
                )
                session.add(user)
                logger.info("✅ 创建教练账号（兼原客服）：{} / {}", username, password)
            else:
                old_role = user.role
                user.role = "trainer"  # 历史 customer_service 一并升级
                user.password_hash = hash_password(password)
                user.nickname = nickname
                logger.info("🔄 升级账号：{} {} → trainer", username, old_role)

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
