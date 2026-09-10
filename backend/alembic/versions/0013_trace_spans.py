"""trace_spans 表（M10+ 全链路追踪）。

每条 AI 请求的 6 个阶段（query_rewrite / intent / tool / rag / llm / output）各写一行。
按 request_id 聚合可重建一次请求的全链路时间线。
"""
from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "trace_spans",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.String(length=32), nullable=False, index=True),
        sa.Column("conversation_id", sa.BigInteger(), nullable=True, index=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("stage", sa.String(length=32), nullable=False, comment="query_rewrite / intent / tool / rag / llm / output"),
        sa.Column("intent", sa.String(length=16), nullable=True, comment="qa / plan / substitute / diet"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="success"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_preview", sa.Text(), nullable=True, comment="阶段入参（前 200 字）"),
        sa.Column("output_preview", sa.Text(), nullable=True, comment="阶段出参（前 200 字）"),
        sa.Column("meta", sa.JSON(), nullable=True, comment="阶段元数据（chunk_ids/tool_call args 等）"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_trace_req_stage", "trace_spans", ["request_id", "stage"])
    op.create_index("idx_trace_conv_created", "trace_spans", ["conversation_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_trace_conv_created", table_name="trace_spans")
    op.drop_index("idx_trace_req_stage", table_name="trace_spans")
    op.drop_table("trace_spans")