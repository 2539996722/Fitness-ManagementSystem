"""plan_templates（计划模板表）

PRD §8.9：教练创建的预设训练计划，状态机 draft → pending_review → published/offline。
聚合字段 use_count / avg_rating / review_count 异步更新。

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plan_templates",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="自增主键"),
        sa.Column("name", sa.String(length=64), nullable=False, comment="模板名"),
        sa.Column(
            "goal",
            sa.String(length=16),
            nullable=False,
            comment="目标：muscle_gain / fat_loss / body_shape / endurance",
        ),
        sa.Column(
            "level",
            sa.String(length=16),
            nullable=False,
            comment="适用人群：beginner / intermediate / advanced",
        ),
        sa.Column("cover_url", sa.String(length=255), nullable=True, comment="封面图 URL"),
        sa.Column("description", sa.String(length=500), nullable=True, comment="模板简介"),
        sa.Column("weeks", sa.JSON(), nullable=False, comment="周训练结构（同 plans.weeks）"),
        sa.Column(
            "author_id",
            sa.BigInteger(),
            nullable=False,
            comment="创建者（教练）ID",
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="draft",
            comment="draft / pending_review / published / offline",
        ),
        sa.Column(
            "use_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="会员采用次数",
        ),
        sa.Column(
            "avg_rating",
            sa.Numeric(precision=3, scale=2),
            nullable=True,
            comment="会员平均评分 1-5",
        ),
        sa.Column(
            "review_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="评分人数",
        ),
        sa.Column(
            "reject_reason",
            sa.String(length=255),
            nullable=True,
            comment="审核驳回理由",
        ),
        sa.Column("published_at", sa.DateTime(), nullable=True, comment="发布时间"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="cascade"),
        mysql_character_set="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="计划模板（教练创建 → 审核 → C 端采用）",
    )
    op.create_index("idx_templates_author", "plan_templates", ["author_id"])
    op.create_index("idx_templates_status", "plan_templates", ["status"])
    op.create_index("idx_templates_published", "plan_templates", ["status", "use_count"])


def downgrade() -> None:
    op.drop_table("plan_templates")