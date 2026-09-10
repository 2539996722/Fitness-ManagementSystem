"""exercise_reviews（动作评论 + 评分）

PRD §8.7：一个用户对同一个动作只能有一条评论（UPSERT）。
聚合字段 avg_rating / review_count 冗余存到 exercises 表，异步刷新。

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 评论表
    op.create_table(
        "exercise_reviews",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="自增主键"),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            nullable=False,
            comment="评论者用户 ID",
        ),
        sa.Column(
            "exercise_id",
            sa.String(length=4),
            nullable=False,
            comment="动作 ID（4 位字符串）",
        ),
        sa.Column(
            "rating",
            sa.SmallInteger(),
            nullable=False,
            comment="评分 1-5",
        ),
        sa.Column(
            "content",
            sa.String(length=500),
            nullable=True,
            comment="评论正文（可空：纯打分）",
        ),
        sa.Column(
            "status",
            sa.SmallInteger(),
            nullable=False,
            server_default="0",
            comment="0 正常 / 1 已删除",
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False, comment="更新时间"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="cascade"),
        sa.ForeignKeyConstraint(["exercise_id"], ["exercises.id"], ondelete="cascade"),
        sa.UniqueConstraint("exercise_id", "user_id", name="uq_review_exercise_user"),
        mysql_character_set="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="动作评论（一人一条，UPSERT）",
    )
    op.create_index("idx_reviews_exercise_time", "exercise_reviews", ["exercise_id", "created_at"])
    op.create_index("idx_reviews_user", "exercise_reviews", ["user_id"])

    # 2. exercises 表增加聚合字段
    op.add_column(
        "exercises",
        sa.Column(
            "avg_rating",
            sa.Numeric(precision=3, scale=2),
            nullable=True,
            comment="平均评分（异步聚合）",
        ),
    )
    op.add_column(
        "exercises",
        sa.Column(
            "review_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="评论总数（异步聚合）",
        ),
    )


def downgrade() -> None:
    op.drop_column("exercises", "review_count")
    op.drop_column("exercises", "avg_rating")
    op.drop_table("exercise_reviews")
