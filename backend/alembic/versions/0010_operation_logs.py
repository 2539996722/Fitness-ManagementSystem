"""operation_logs (B 端操作审计表)

Revision ID: 0010
Revises: 1c70c5894a7d
Create Date: 2026-09-08

M9 操作日志：记录 admin / trainer 所有写动作（修改配置、CRUD 用户/模板/评论、
接入会话等）。仅落库，不影响主流程（写入失败 → loguru.warning）。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import JSON as MYSQL_JSON


# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "operation_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="自增主键"),
        sa.Column("operator_id", sa.BigInteger(), nullable=True, comment="操作人用户 ID（系统任务为 NULL）"),
        sa.Column("operator_role", sa.String(length=16), nullable=True, comment="操作人角色：admin / trainer / system"),
        sa.Column("operator_name", sa.String(length=64), nullable=True, comment="操作人昵称（冗余，方便查询展示）"),
        sa.Column("action", sa.String(length=64), nullable=False, comment="动作编码，如 update_llm_config / ban_user"),
        sa.Column("target_type", sa.String(length=32), nullable=True, comment="对象类型：config / user / template / review / conversation"),
        sa.Column("target_id", sa.String(length=64), nullable=True, comment="对象 ID（字符串，兼容 'llm' / 'ai_limits' 等配置 key）"),
        sa.Column("summary", sa.String(length=255), nullable=True, comment="一句话摘要"),
        sa.Column("details", MYSQL_JSON(), nullable=True, comment="详情 JSON（变更字段、备注等）"),
        sa.Column("ip", sa.String(length=45), nullable=True, comment="操作人 IP（X-Forwarded-For 优先）"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False, comment="更新时间"),
        sa.ForeignKeyConstraint(["operator_id"], ["users.id"], ondelete="SET NULL"),
        mysql_character_set="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="B 端操作日志（admin / trainer 写动作审计）",
    )
    # 索引：时间倒序 + 动作筛选 + 操作人筛选 + 对象反查
    op.create_index("idx_oplogs_time", "operation_logs", ["created_at"])
    op.create_index("idx_oplogs_action_time", "operation_logs", ["action", "created_at"])
    op.create_index("idx_oplogs_operator_time", "operation_logs", ["operator_id", "created_at"])
    op.create_index("idx_oplogs_target", "operation_logs", ["target_type", "target_id"])


def downgrade() -> None:
    op.drop_index("idx_oplogs_target", table_name="operation_logs")
    op.drop_index("idx_oplogs_operator_time", table_name="operation_logs")
    op.drop_index("idx_oplogs_action_time", table_name="operation_logs")
    op.drop_index("idx_oplogs_time", table_name="operation_logs")
    op.drop_table("operation_logs")