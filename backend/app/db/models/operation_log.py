"""operation_logs（B 端操作审计表，M9）。

记录 admin / trainer 所有写动作（修改配置、CRUD 用户/模板/评论、接入会话等）。
写入失败不影响主流程（见 app.services.operation_log.record）。
"""

from typing import Any

from sqlalchemy import JSON, BigInteger, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class OperationLog(Base, TimestampMixin):
    """B 端操作日志（异步写入；落库失败不影响主流程）。"""

    __tablename__ = "operation_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    operator_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="set null"),
        nullable=True, index=True, comment="操作人用户 ID（系统任务为 NULL）",
    )
    operator_role: Mapped[str | None] = mapped_column(
        String(16), comment="admin / trainer / system",
    )
    operator_name: Mapped[str | None] = mapped_column(
        String(64), comment="操作人昵称（冗余，删账号后仍能展示）",
    )
    action: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="动作编码：update_llm_config / ban_user / ...",
    )
    target_type: Mapped[str | None] = mapped_column(
        String(32), comment="对象类型：config / user / template / review / conversation / conv",
    )
    target_id: Mapped[str | None] = mapped_column(
        String(64), comment="对象 ID（字符串，兼容 'llm' / 'ai_limits' 等配置 key）",
    )
    summary: Mapped[str | None] = mapped_column(
        String(255), comment="一句话摘要",
    )
    details: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, comment="详情 JSON（变更字段、备注等）",
    )
    ip: Mapped[str | None] = mapped_column(
        String(45), comment="操作人 IP（X-Forwarded-For 优先）",
    )