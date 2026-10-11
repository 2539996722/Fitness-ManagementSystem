"""用户体重打卡表（weight_logs）。

每天可记多条（早晚各一）；曲线只展示用户自己的数据。
与 User 表的 weight_kg 字段互补：User.weight_kg 是"当前体重"，
weight_logs 是"历史轨迹"。
"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WeightLog(Base):
    """用户体重打卡记录。"""

    __tablename__ = "weight_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="cascade"),
        nullable=False,
        index=True,
        comment="所属用户",
    )

    weight_kg: Mapped[float] = mapped_column(
        Numeric(5, 1),  # 0.0 ~ 999.9 kg，足够
        nullable=False,
        comment="体重 kg",
    )

    recorded_at: Mapped[DateTime] = mapped_column(
        DateTime,
        nullable=False,
        index=True,
        comment="称重时间（可未来，但通常 ≤ 当前）",
    )

    note: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="备注（如：早起空腹 / 训练后）",
    )

    # server_default 让 SQLAlchemy 在 INSERT 时不传该字段，由 DB 自动填 NOW()
    created_at: Mapped[DateTime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        comment="记录创建时间",
    )

    def __repr__(self) -> str:
        return f"<WeightLog u={self.user_id} w={self.weight_kg} at={self.recorded_at}>"
