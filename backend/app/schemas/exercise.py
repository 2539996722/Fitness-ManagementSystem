"""动作相关 schema。"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ExerciseOut(BaseModel):
    """动作详情。"""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="动作 ID")
    name_en: str
    name_zh: str | None = None
    category: str
    body_part: str
    equipment: str
    target: str
    secondary_muscles: list[str] = []
    instructions: dict[str, str] = Field(default_factory=dict, description="10 语言步骤说明")
    image: str | None = None
    gif_url: str | None = None
    attribution: str | None = None
    # 评论聚合（M7）
    avg_rating: float | None = Field(None, description="平均评分（评论数 < 5 时为 null）")
    review_count: int = Field(0, description="评论总数")
    created_at: datetime
    updated_at: datetime


class ExerciseListResponse(BaseModel):
    """动作列表分页响应。"""

    items: list[ExerciseOut]
    total: int
    page: int
    page_size: int
    has_more: bool


class ExerciseFilterOptions(BaseModel):
    """可筛选项（前端用于填充下拉菜单）。"""

    categories: list[str]
    body_parts: list[str]
    equipment: list[str]
    targets: list[str]