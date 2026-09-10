"""知识库（KB）+ KB 文档（M10+ RAG 文档问答）。

- knowledge_bases：一个 KB = 一个 Chroma collection（命名 kb_{id}）
- knowledge_documents：KB 内上传的文档
- ai_call_logs 加 call_type 字段（chat / embedding）
"""
from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # knowledge_bases
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=64), nullable=False, unique=True),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("chunk_size", sa.Integer(), nullable=False, server_default="500"),
        sa.Column("chunk_overlap", sa.Integer(), nullable=False, server_default="80"),
        sa.Column("top_k", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("similarity_threshold", sa.Numeric(4, 3), nullable=False, server_default="0.000"),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="set null"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_kb_enabled", "knowledge_bases", ["enabled"])

    # knowledge_documents
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("kb_id", sa.BigInteger(), sa.ForeignKey("knowledge_bases.id", ondelete="cascade"), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("storage_path", sa.String(length=512), nullable=False),
        sa.Column("ext", sa.String(length=8), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="processing"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("uploaded_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="set null"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_kbdoc_kb_id", "knowledge_documents", ["kb_id"])
    op.create_index("idx_kbdoc_status", "knowledge_documents", ["status"])

    # ai_call_logs 加 call_type
    op.add_column(
        "ai_call_logs",
        sa.Column("call_type", sa.String(length=16), nullable=False, server_default="chat", comment="chat / embedding"),
    )
    op.create_index("idx_ai_call_logs_type", "ai_call_logs", ["call_type", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_ai_call_logs_type", table_name="ai_call_logs")
    op.drop_column("ai_call_logs", "call_type")
    op.drop_index("idx_kbdoc_status", table_name="knowledge_documents")
    op.drop_index("idx_kbdoc_kb_id", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
    op.drop_index("idx_kb_enabled", table_name="knowledge_bases")
    op.drop_table("knowledge_bases")