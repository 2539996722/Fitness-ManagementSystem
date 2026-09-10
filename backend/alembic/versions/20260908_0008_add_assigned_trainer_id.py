"""add_assigned_trainer_id

Revision ID: 1c70c5894a7d
Revises: 0007
Create Date: 2026-09-08 00:08:15.450584+08:00

仅给 conversations 加 assigned_trainer_id 列（FK users.id），其他差异忽略。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '1c70c5894a7d'
down_revision: Union[str, None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'conversations',
        sa.Column('assigned_trainer_id', sa.BigInteger(), nullable=True,
                  comment='当前教练 ID'),
    )
    op.create_index(
        op.f('ix_conversations_assigned_trainer_id'),
        'conversations',
        ['assigned_trainer_id'],
        unique=False,
    )
    op.create_foreign_key(
        'fk_conversations_assigned_trainer',
        'conversations', 'users',
        ['assigned_trainer_id'], ['id'],
        ondelete='SET NULL',
    )
    # status 字段 comment 更新（M8 加了 waiting_trainer / trainer_active）
    op.alter_column(
        'conversations', 'status',
        existing_type=sa.String(length=16),
        comment='ai_active / waiting_human / human_active / waiting_trainer / trainer_active / closed',
        existing_comment='ai_active / waiting_human / human_active / closed',
        existing_nullable=False,
    )


def downgrade() -> None:
    op.drop_constraint('fk_conversations_assigned_trainer', 'conversations', type_='foreignkey')
    op.drop_index(op.f('ix_conversations_assigned_trainer_id'), table_name='conversations')
    op.drop_column('conversations', 'assigned_trainer_id')
    op.alter_column(
        'conversations', 'status',
        existing_type=sa.String(length=16),
        comment='ai_active / waiting_human / human_active / closed',
        existing_comment='ai_active / waiting_human / human_active / waiting_trainer / trainer_active / closed',
        existing_nullable=False,
    )
