"""操作日志 schema（M9）。"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class OperationLogOut(BaseModel):
    """单条操作日志返回。"""

    id: int
    operator_id: int | None = None
    operator_name: str | None = None
    operator_role: str | None = None
    action: str
    target_type: str | None = None
    target_id: str | None = None
    summary: str | None = None
    details: dict[str, Any] | None = None
    ip: str | None = None
    created_at: datetime


class OperationLogListOut(BaseModel):
    """操作日志列表（含 total 便于分页）。"""

    items: list[OperationLogOut]
    total: int
    limit: int
    offset: int


class ActionOption(BaseModel):
    """操作动作筛选下拉项（distinct action）。"""

    action: str
    count: int = Field(default=0, description="该动作的日志条数")


class TargetTypeOption(BaseModel):
    """对象类型筛选下拉项。"""

    target_type: str
    count: int = 0