"""system_configs (KV-style system configuration)

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "system_configs",
        sa.Column("`key`", sa.String(length=64), nullable=False, comment="配置键"),
        sa.Column("value", mysql.JSON(), nullable=False, comment="配置值（JSON）"),
        sa.Column("description", sa.Text(), nullable=True, comment="配置说明"),
        sa.Column("updated_by", sa.BigInteger(), nullable=True, comment="最后修改者 ID"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False, comment="更新时间"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("`key`"),
        mysql_character_set="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="运行时系统配置（LLM / 限流 / 业务参数等）",
    )
    # 注意：不预置数据行，避免 alembic 写中文到 SQL 时的 GBK 问题
    # 行由 backend 启动时（如不存在）通过 SystemConfig seed 自动创建


def downgrade() -> None:
    op.drop_table("system_configs")
