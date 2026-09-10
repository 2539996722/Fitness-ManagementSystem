"""initial schema: exercises, users

Revision ID: 0001
Revises:
Create Date: 2026-09-04

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------- exercises 表 ----------
    op.create_table(
        "exercises",
        sa.Column("id", sa.String(length=4), nullable=False, comment="动作 ID（4 位字符串）"),
        sa.Column("name_en", sa.String(length=128), nullable=False, comment="英文名"),
        sa.Column("name_zh", sa.String(length=64), nullable=True, comment="中文名"),
        sa.Column("category", sa.String(length=32), nullable=False, comment="大分类"),
        sa.Column("body_part", sa.String(length=32), nullable=False, comment="身体部位"),
        sa.Column("equipment", sa.String(length=32), nullable=False, comment="所需器械"),
        sa.Column("target", sa.String(length=64), nullable=False, comment="主要目标肌肉"),
        sa.Column("secondary_muscles", mysql.JSON(), nullable=False, comment="协同肌肉列表"),
        sa.Column("instructions", mysql.JSON(), nullable=False, comment="10 语言步骤说明"),
        sa.Column("image", sa.String(length=255), nullable=True, comment="缩略图路径"),
        sa.Column("gif_url", sa.String(length=255), nullable=True, comment="GIF 路径"),
        sa.Column("attribution", sa.String(length=255), nullable=True, comment="版权归属"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False, comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        mysql_character_set="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="健身动作数据（1,324 条，来自数据集）",
    )
    op.create_index("ix_exercises_name_en", "exercises", ["name_en"])
    op.create_index("ix_exercises_name_zh", "exercises", ["name_zh"])
    op.create_index("ix_exercises_category", "exercises", ["category"])
    op.create_index("ix_exercises_body_part", "exercises", ["body_part"])
    op.create_index("ix_exercises_equipment", "exercises", ["equipment"])
    op.create_index("ix_exercises_target", "exercises", ["target"])

    # ---------- users 表 ----------
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=32), nullable=False, comment="登录名"),
        sa.Column("password_hash", sa.String(length=255), nullable=False, comment="bcrypt 哈希"),
        sa.Column("nickname", sa.String(length=32), nullable=True, comment="昵称"),
        sa.Column("avatar_url", sa.String(length=255), nullable=True, comment="头像 URL"),
        sa.Column("gender", sa.SmallInteger(), nullable=False, comment="0 未知 1 男 2 女", server_default="0"),
        sa.Column("age", sa.SmallInteger(), nullable=True, comment="年龄"),
        sa.Column("height_cm", sa.DECIMAL(precision=5, scale=1), nullable=True, comment="身高 cm"),
        sa.Column("weight_kg", sa.DECIMAL(precision=5, scale=1), nullable=True, comment="体重 kg"),
        sa.Column("role", sa.String(length=16), nullable=False, comment="user/admin/customer_service/trainer", server_default="user"),
        sa.Column("status", sa.SmallInteger(), nullable=False, comment="0 正常 1 封禁", server_default="0"),
        sa.Column("failed_login_count", sa.SmallInteger(), nullable=False, comment="登录失败计数", server_default="0"),
        sa.Column("locked_until", sa.DateTime(), nullable=True, comment="锁定到期时间"),
        sa.Column("remark", sa.String(length=255), nullable=True, comment="管理员备注"),
        sa.Column("last_login_at", sa.DateTime(), nullable=True, server_default=sa.func.now(), comment="最近登录时间"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False, comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", name="uq_users_username"),
        mysql_character_set="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="用户表（含管理员/教练/客服）",
    )
    op.create_index("ix_users_role", "users", ["role"])
    op.create_index("ix_users_status", "users", ["status"])


def downgrade() -> None:
    op.drop_index("ix_users_status", table_name="users")
    op.drop_index("ix_users_role", table_name="users")
    op.drop_table("users")

    op.drop_index("ix_exercises_target", table_name="exercises")
    op.drop_index("ix_exercises_equipment", table_name="exercises")
    op.drop_index("ix_exercises_body_part", table_name="exercises")
    op.drop_index("ix_exercises_category", table_name="exercises")
    op.drop_index("ix_exercises_name_zh", table_name="exercises")
    op.drop_index("ix_exercises_name_en", table_name="exercises")
    op.drop_table("exercises")