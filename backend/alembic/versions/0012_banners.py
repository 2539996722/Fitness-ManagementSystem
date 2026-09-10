"""banners 迁移（M9 公告管理）。"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    op.create_table(
        "banners",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(length=64), nullable=False, comment="Banner 标题"),
        sa.Column("content", sa.Text(), nullable=False, comment="Banner 正文"),
        sa.Column("link_url", sa.String(length=255), nullable=True, comment="可选跳转链接"),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
            comment="是否启用",
        ),
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="排序：越小越靠前",
        ),
        sa.Column("starts_at", sa.DateTime(), nullable=True, comment="生效起始"),
        sa.Column("ends_at", sa.DateTime(), nullable=True, comment="生效结束"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        comment="C 端首页公告 Banner",
    )
    op.create_index("idx_banners_is_active", "banners", ["is_active"])
    op.create_index(
        "idx_banners_active_order", "banners", ["is_active", "sort_order", "id"]
    )


def downgrade() -> None:
    op.drop_index("idx_banners_active_order", table_name="banners")
    op.drop_index("idx_banners_is_active", table_name="banners")
    op.drop_table("banners")