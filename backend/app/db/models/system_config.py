"""系统配置表（system_configs）。

存储 LLM 配置、限流阈值等运行时可调参数。
key: 配置键；value: JSON 值；description: 说明；updated_by: 最后修改人。
"""

from sqlalchemy import JSON, BigInteger, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class SystemConfig(Base, TimestampMixin):
    """运行时系统配置（KV 形式）。"""

    __tablename__ = "system_configs"

    key: Mapped[str] = mapped_column(String(64), primary_key=True, comment="配置键")
    value: Mapped[dict] = mapped_column(JSON, nullable=False, comment="配置值（JSON）")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="配置说明")
    updated_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, comment="最后修改者 ID"
    )

    def __repr__(self) -> str:
        return f"<SystemConfig {self.key}>"