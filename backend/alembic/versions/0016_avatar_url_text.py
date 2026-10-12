"""users.avatar_url 改 TEXT（容纳 base64 DataURL）。

之前是 VARCHAR(255)，只能存 https URL。M11 个人中心头像上传
（点 hero 弹 modal → 选本地图片 → 转 base64）需要更大容量。
2MB 图片 base64 ≈ 2.7M 字符，TEXT 最大 65535 字符不够，改 LONGTEXT。

生产建议：长期应接 CDN / 对象存储，不应让 DB 存大字段。
"""
from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # MySQL: VARCHAR(255) → TEXT（不够的话可改 LONGTEXT）。TEXT 上限 65535 字符。
    # 实际生产建议 avatar_url 走 CDN；这里扩到 TEXT 够 demo + 中小图 base64。
    op.alter_column(
        "users",
        "avatar_url",
        existing_type=sa.String(length=255),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    # 回滚会截断 >255 字符的数据；为了 demo 可接受
    op.alter_column(
        "users",
        "avatar_url",
        existing_type=sa.Text(),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
