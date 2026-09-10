"""训练记录表（training_records）。

每次打卡写一条记录，记录某个动作在某个周/某天的完成情况。
"""

from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TrainingRecord(Base):
    """训练打卡记录。"""

    __tablename__ = "training_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="cascade"),
        nullable=False,
        index=True,
        comment="用户 ID",
    )
    plan_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("plans.id", ondelete="cascade"),
        nullable=False,
        index=True,
        comment="所属计划 ID",
    )
    exercise_id: Mapped[str] = mapped_column(
        String(4),
        ForeignKey("exercises.id"),
        nullable=False,
        index=True,
        comment="动作 ID",
    )

    # 位置信息：第几周第几天
    plan_week: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="第几周（从1开始）")
    plan_day: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="第几天（从1开始）")

    # 完成情况：每组是否完成（数组，如 [true, true, false, true]）
    completed_sets: Mapped[list] = mapped_column(JSON, nullable=False, default=list, comment="每组完成情况")

    # 时间
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
        comment="打卡时间",
    )

    def __repr__(self) -> str:
        return f"<TrainingRecord u={self.user_id} e={self.exercise_id} w{self.plan_week}d{self.plan_day}>"