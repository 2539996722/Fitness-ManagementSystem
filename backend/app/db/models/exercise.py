"""动作表（exercises）。

数据来源：wangmuerxiao/exercises-dataset-zh（1,324 条记录）。
媒体文件（image/gif_url）的版权 © Gym visual，必须保留 attribution。
"""

from decimal import Decimal

from sqlalchemy import JSON, Numeric, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Exercise(Base, TimestampMixin):
    """健身动作记录。"""

    __tablename__ = "exercises"

    # 主键：4 位字符串，如 "0001"
    id: Mapped[str] = mapped_column(String(4), primary_key=True, comment="动作 ID（4 位字符串）")

    # 名称
    name_en: Mapped[str] = mapped_column(String(128), nullable=False, index=True, comment="英文名")
    name_zh: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True, comment="中文名")

    # 分类
    category: Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="大分类（如 'waist'）")
    body_part: Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="身体部位")
    equipment: Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="所需器械")
    target: Mapped[str] = mapped_column(String(64), nullable=False, comment="主要目标肌肉")

    # 协同肌肉与说明
    secondary_muscles: Mapped[list] = mapped_column(JSON, nullable=False, default=list, comment="协同肌肉列表")
    instructions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, comment="10 语言步骤说明")

    # 媒体（© Gym visual）
    image: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="180×180 缩略图路径")
    gif_url: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="180×180 动画 GIF 路径")
    attribution: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="版权归属")

    # 评论聚合（M7，异步刷新，不保证实时）
    avg_rating: Mapped[Decimal | None] = mapped_column(
        Numeric(3, 2), nullable=True, comment="平均评分（异步聚合）"
    )
    review_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="评论总数（异步聚合）"
    )

    def __repr__(self) -> str:
        return f"<Exercise {self.id} {self.name_zh or self.name_en}>"