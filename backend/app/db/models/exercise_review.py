"""动作评论表（exercise_reviews）。

一人对一个动作只能有一条评论（UNIQUE(exercise_id, user_id)）。
写操作是 UPSERT：调用方根据主键先查再决定 update/insert。

聚合：avg_rating / review_count 不在评论表上做实时计算，
由调用方写入 / 删除时同步更新 exercises 表的聚合字段。
"""

from sqlalchemy import BigInteger, ForeignKey, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ExerciseReview(Base, TimestampMixin):
    """动作评论记录。"""

    __tablename__ = "exercise_reviews"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="cascade"),
        nullable=False,
        index=True,
        comment="评论者用户 ID",
    )
    exercise_id: Mapped[str] = mapped_column(
        String(4),
        ForeignKey("exercises.id", ondelete="cascade"),
        nullable=False,
        index=True,
        comment="动作 ID（4 位字符串）",
    )

    rating: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, comment="评分 1-5"
    )
    content: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="评论正文（可空）"
    )

    # 0 正常 / 1 已删除（软删；用户"删除"和 admin 强删都用这个标记，
    # 这样 UNIQUE 约束不会被同一用户反复删除又重建占用）
    status: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, comment="0 正常 / 1 已删除"
    )

    def __repr__(self) -> str:
        return f"<ExerciseReview u={self.user_id} e={self.exercise_id} r={self.rating}>"
