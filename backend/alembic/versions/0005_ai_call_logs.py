"""ai_call_logs (LLM 调用审计表)

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_call_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="自增主键"),
        sa.Column("user_id", sa.BigInteger(), nullable=True, comment="调用者用户 ID（可空：系统任务）"),
        sa.Column("conversation_id", sa.BigInteger(), nullable=True, comment="所属会话 ID"),
        sa.Column("intent", sa.String(length=32), nullable=False, comment="调用意图：qa / plan / substitute / diet"),
        sa.Column("model", sa.String(length=64), nullable=False, comment="实际使用的模型名"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0", comment="prompt token 数"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0", comment="completion token 数"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0", comment="总 token 数"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0", comment="端到端耗时 ms"),
        sa.Column("prompt_preview", sa.Text(), nullable=True, comment="prompt 摘要（截断）"),
        sa.Column("response_preview", sa.Text(), nullable=True, comment="响应摘要（截断 200 字）"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False, comment="更新时间"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        mysql_character_set="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="LLM 调用日志（审计 + 费用统计）",
    )
    op.create_index("idx_ai_logs_user_time", "ai_call_logs", ["user_id", "created_at"])
    op.create_index("idx_ai_logs_conv", "ai_call_logs", ["conversation_id"])
    op.create_index("idx_ai_logs_intent_time", "ai_call_logs", ["intent", "created_at"])


def downgrade() -> None:
    op.drop_table("ai_call_logs")