"""用户表（users）。

四种角色（PRD D2）：
- user：普通 C 端用户
- customer_service：客服
- trainer：教练
- admin：管理员
"""

from datetime import datetime

from sqlalchemy import (
    DECIMAL,
    BigInteger,
    Boolean,
    DateTime,
    SmallInteger,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    """用户（含管理员 / 教练 / 客服）。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # 账号信息
    username: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True, comment="登录名")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, comment="bcrypt 哈希")
    nickname: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="昵称")
    avatar_url: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="头像 URL")

    # 个人信息
    gender: Mapped[int] = mapped_column(SmallInteger, default=0, comment="0 未知 1 男 2 女")
    age: Mapped[int | None] = mapped_column(SmallInteger, nullable=True, comment="年龄")
    height_cm: Mapped[float | None] = mapped_column(DECIMAL(5, 1), nullable=True, comment="身高 cm")
    weight_kg: Mapped[float | None] = mapped_column(DECIMAL(5, 1), nullable=True, comment="体重 kg")

    # 权限
    role: Mapped[str] = mapped_column(
        String(16),
        default="user",
        nullable=False,
        index=True,
        comment="user / admin / customer_service / trainer",
    )

    # 状态
    status: Mapped[int] = mapped_column(
        SmallInteger,
        default=0,
        nullable=False,
        index=True,
        comment="0 正常 1 封禁",
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
        comment="软删除标记：0 正常 1 已删除（M9+）",
    )

    # 登录安全
    failed_login_count: Mapped[int] = mapped_column(SmallInteger, default=0, comment="登录失败计数")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="锁定到期时间")

    # B 端管理
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="管理员备注")
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        server_default=func.now(),
        comment="最近登录时间",
    )

    def __repr__(self) -> str:
        return f"<User {self.id} {self.username} ({self.role})>"

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_trainer(self) -> bool:
        return self.role == "trainer"

    @property
    def is_customer_service(self) -> bool:
        return self.role == "customer_service"

    @property
    def is_banned(self) -> bool:
        return self.status == 1

    @property
    def is_deleted_user(self) -> bool:
        return self.is_deleted

    @property
    def is_locked(self) -> bool:
        if not self.locked_until:
            return False
        return self.locked_until > datetime.utcnow()