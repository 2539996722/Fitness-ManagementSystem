"""conversations and messages

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False, comment="所属用户"),
        sa.Column("title", sa.String(length=64), nullable=True, comment="会话标题"),
        sa.Column("conversation_type", sa.String(length=16), nullable=True, comment="ai / customer_service / trainer"),
        sa.Column("status", sa.String(length=16), nullable=True, comment="ai_active / waiting_human / human_active / closed"),
        sa.Column("assigned_cs_id", sa.BigInteger(), nullable=True, comment="当前客服 ID"),
        sa.Column("rag_sources", mysql.JSON(), nullable=True, comment="RAG 命中的源文档 chunk IDs"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False, comment="更新时间"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        mysql_character_set="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="用户会话",
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
    op.create_index("ix_conversations_status", "conversations", ["status"])

    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False, comment="所属会话"),
        sa.Column("sender_type", sa.String(length=16), nullable=False, comment="user / ai / customer_service / trainer"),
        sa.Column("sender_id", sa.BigInteger(), nullable=True, comment="发送者 ID"),
        sa.Column("content", sa.Text(), nullable=False, comment="消息正文"),
        sa.Column("intent", sa.String(length=16), nullable=True, comment="意图：qa/plan/substitute/diet"),
        sa.Column("extra", mysql.JSON(), nullable=True, comment="RAG sources、动作引用 等"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False, comment="更新时间"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        mysql_character_set="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="会话消息",
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index("ix_messages_sender_type", "messages", ["sender_type"])


def downgrade() -> None:
    op.drop_index("ix_messages_sender_type", table_name="messages")
    op.drop_index("ix_messages_conversation_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_status", table_name="conversations")
    op.drop_index("ix_conversations_user_id", table_name="conversations")
    op.drop_table("conversations")