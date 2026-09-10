"""plans and training_records

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-04

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------- plans 表 ----------
    op.create_table(
        "plans",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False, comment="所属用户 ID"),
        sa.Column("name", sa.String(length=64), nullable=False, comment="计划名称"),
        sa.Column("goal", sa.String(length=16), nullable=False, comment="目标类型"),
        sa.Column("weeks", mysql.JSON(), nullable=False, comment="周训练结构"),
        sa.Column("is_current", sa.SmallInteger(), nullable=False, server_default="0", comment="是否当前计划"),
        sa.Column("days_per_week", sa.SmallInteger(), nullable=False, server_default="3", comment="每周训练天数"),
        sa.Column("equipment", mysql.JSON(), nullable=False, comment="可用器械列表"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="cascade"),
        mysql_character_set="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="用户训练计划",
    )
    op.create_index("ix_plans_user_id", "plans", ["user_id"])
    op.create_index("ix_plans_goal", "plans", ["goal"])

    # ---------- training_records 表 ----------
    op.create_table(
        "training_records",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False, comment="用户 ID"),
        sa.Column("plan_id", sa.BigInteger(), nullable=False, comment="所属计划 ID"),
        sa.Column("exercise_id", sa.String(length=4), nullable=False, comment="动作 ID"),
        sa.Column("plan_week", sa.SmallInteger(), nullable=False, comment="第几周"),
        sa.Column("plan_day", sa.SmallInteger(), nullable=False, comment="第几天"),
        sa.Column("completed_sets", mysql.JSON(), nullable=False, comment="每组完成情况"),
        sa.Column("recorded_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="cascade"),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="cascade"),
        sa.ForeignKeyConstraint(["exercise_id"], ["exercises.id"]),
        mysql_character_set="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="训练打卡记录",
    )
    op.create_index("ix_training_records_user_id", "training_records", ["user_id"])
    op.create_index("ix_training_records_plan_id", "training_records", ["plan_id"])
    op.create_index("ix_training_records_exercise_id", "training_records", ["exercise_id"])


def downgrade() -> None:
    op.drop_index("ix_training_records_exercise_id", table_name="training_records")
    op.drop_index("ix_training_records_plan_id", table_name="training_records")
    op.drop_index("ix_training_records_user_id", table_name="training_records")
    op.drop_table("training_records")

    op.drop_index("ix_plans_goal", table_name="plans")
    op.drop_index("ix_plans_user_id", table_name="plans")
    op.drop_table("plans")