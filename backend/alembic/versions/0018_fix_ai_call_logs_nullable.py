"""修 ai_call_logs 与 model 的 schema drift（#129）。

差异：
- DB: intent VARCHAR(32) NOT NULL       /  model: String(16) nullable=True
- DB: model VARCHAR(64) NOT NULL        /  model: String(64) nullable=True
- DB: prompt_tokens / completion_tokens / total_tokens / cost_cny / latency_ms NOT NULL DEFAULT 0
                                          /  model: nullable=True（没显式标 nullable，所以默认 True）
- DB: response_preview / call_type 索引差异

实测现状（2026-10-19，dev 本机 MySQL）：
- 129 行 ai_call_logs，intent max length = 9（最长 'embedding'），String(16) 容纳
- intent / model 全部非空（无 NULL 行），改 NOT NULL → NULL 安全
- error_message / prompt_preview / response_preview 本来就 NULLABLE，无需改

范围：仅修 ai_call_logs，122 条 drift 其它表暂缓（按工作量拆批）
"""
from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    """让 ai_call_logs 的 schema 与 model 对齐。"""
    # 1. intent: VARCHAR(32) NOT NULL → VARCHAR(16) NULL
    op.alter_column(
        "ai_call_logs", "intent",
        existing_type=sa.String(length=32),
        type_=sa.String(length=16),
        existing_nullable=False,
        nullable=True,
    )

    # 2. model: NOT NULL → NULL
    op.alter_column(
        "ai_call_logs", "model",
        existing_type=sa.String(length=64),
        existing_nullable=False,
        nullable=True,
    )

    # 3. tokens / cost / latency: NOT NULL DEFAULT 0 → NULL（去掉 default）
    for col in ("prompt_tokens", "completion_tokens", "total_tokens", "cost_cny", "latency_ms"):
        col_type = sa.Numeric(10, 6) if col == "cost_cny" else sa.Integer()
        op.alter_column(
            "ai_call_logs", col,
            existing_type=col_type,
            existing_nullable=False,
            nullable=True,
        )


def downgrade() -> None:
    """回滚：把 nullable 列改回 NOT NULL（保持兼容迁移前的现有数据）。"""
    # 注意：若回滚时已有 NULL 行，会失败。
    # 这是 0018 升上去后再回滚的场景——少量 NULL 数据需要先清理。
    for col in ("prompt_tokens", "completion_tokens", "total_tokens", "cost_cny", "latency_ms"):
        col_type = sa.Numeric(10, 6) if col == "cost_cny" else sa.Integer()
        op.alter_column(
            "ai_call_logs", col,
            existing_type=col_type,
            existing_nullable=True,
            nullable=False,
        )
    op.alter_column(
        "ai_call_logs", "model",
        existing_type=sa.String(length=64),
        existing_nullable=True,
        nullable=False,
    )
    op.alter_column(
        "ai_call_logs", "intent",
        existing_type=sa.String(length=16),
        type_=sa.String(length=32),
        existing_nullable=True,
        nullable=False,
    )
