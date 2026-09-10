"""ai_call_logs_extra

Revision ID: 0009
Revises: 1c70c5894a7d
Create Date: 2026-09-08

给 ai_call_logs 加 status / cost_cny / error_message 字段，
让 LLM 服务的 _log_call() 能记录调用结果与成本。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0009"
down_revision: Union[str, None] = "1c70c5894a7d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ai_call_logs",
        sa.Column("status", sa.String(length=16), nullable=False, server_default="success",
                  comment="success / error / timeout"),
    )
    op.add_column(
        "ai_call_logs",
        sa.Column("cost_cny", sa.Numeric(10, 6), nullable=False, server_default="0",
                  comment="本次调用估算成本（元）"),
    )
    op.add_column(
        "ai_call_logs",
        sa.Column("error_message", sa.Text(), nullable=True,
                  comment="失败时的错误信息（success 时为 NULL）"),
    )


def downgrade() -> None:
    op.drop_column("ai_call_logs", "error_message")
    op.drop_column("ai_call_logs", "cost_cny")
    op.drop_column("ai_call_logs", "status")
