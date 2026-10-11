"""weight_logs 表：用户体重打卡记录（M11 阶段二）。

- 每天可记多条（早晚各一次）
- 用于个人中心"体重曲线"功能
- 与 User 表的 weight_kg 字段互补：前者是历史，后者是"当前体重"
"""
from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "weight_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="cascade"), nullable=False),
        sa.Column("weight_kg", sa.Numeric(5, 1), nullable=False, comment="体重 kg（0.0 ~ 999.9）"),
        sa.Column("recorded_at", sa.DateTime(), nullable=False, comment="称重时间"),
        sa.Column("note", sa.String(length=64), nullable=True, comment="备注"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    # 复合索引：按用户 + 时间查历史轨迹
    op.create_index("idx_weight_logs_user_time", "weight_logs", ["user_id", "recorded_at"])

    # 修正：created_at 应有 server_default（迁移里写了，但创建表时漏了，
    # 可能是因为 schema 已存在导致 server_default 没生效 —— 此处兜底 ALTER）
    # 安全起见只在没有 server_default 时加
    conn = op.get_bind()
    res = conn.execute(sa.text(
        "SELECT COLUMN_DEFAULT FROM information_schema.columns "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'weight_logs' AND COLUMN_NAME = 'created_at'"
    )).first()
    if res and res[0] is None:
        op.alter_column("weight_logs", "created_at", server_default=sa.func.now())


def downgrade() -> None:
    op.drop_index("idx_weight_logs_user_time", table_name="weight_logs")
    op.drop_table("weight_logs")
