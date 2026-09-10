"""add is_deleted to users

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-08

为 users 表加 is_deleted 布尔字段，软删除方案：
- 默认 FALSE，正常用户
- DELETE 接口置 TRUE，从 list/get/login 中过滤
- 操作日志 (operation_logs) 完整记录被删用户是谁、什么时候删的
- ponytail: 不硬删，避免破坏 plans.user_id（无 ondelete 默认 RESTRICT）
  及历史会话/评论的 FK 关系
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="软删除标记：0 正常 1 已删除",
        ),
    )
    op.create_index("idx_users_is_deleted", "users", ["is_deleted"])


def downgrade() -> None:
    op.drop_index("idx_users_is_deleted", table_name="users")
    op.drop_column("users", "is_deleted")