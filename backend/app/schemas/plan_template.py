"""计划模板 schema。"""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 复用 plans 的训练结构
from app.schemas.plan import PlanWeek

GoalType = Literal["muscle_gain", "fat_loss", "body_shape", "endurance"]
LevelType = Literal["beginner", "intermediate", "advanced"]
StatusType = Literal["draft", "pending_review", "published", "offline"]


class PlanTemplateBase(BaseModel):
    """模板公共字段。"""

    name: str = Field(..., min_length=1, max_length=64)
    goal: GoalType
    level: LevelType
    cover_url: str | None = Field(None, max_length=255)
    description: str | None = Field(None, max_length=500)
    weeks: list[PlanWeek] = Field(default_factory=list)
    days_per_week: int = Field(3, ge=1, le=7)


class PlanTemplateCreate(PlanTemplateBase):
    """新建模板（admin 可指定 status，trainer 忽略，默认 draft）。"""

    status: StatusType | None = None


class PlanTemplateUpdate(BaseModel):
    """教练编辑模板（所有字段可选；只在 draft / offline 可改）。"""

    name: str | None = Field(None, min_length=1, max_length=64)
    goal: GoalType | None = None
    level: LevelType | None = None
    cover_url: str | None = None
    description: str | None = None
    weeks: list[PlanWeek] | None = None
    days_per_week: int | None = Field(None, ge=1, le=7)


class PlanTemplateOut(PlanTemplateBase):
    """模板对外返回（统一字段，C 端 / B 端共用）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    author_id: int
    status: StatusType
    use_count: int
    avg_rating: float | None = None
    review_count: int
    reject_reason: str | None = None
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    # 教练视图可读：作者昵称
    author_nickname: str | None = None


class PlanTemplateListResponse(BaseModel):
    items: list[PlanTemplateOut]
    total: int
    page: int
    page_size: int
    has_more: bool


class PlanTemplateReviewUpdate(BaseModel):
    """管理员审核动作。"""

    reason: str | None = Field(None, max_length=255, description="驳回 / 下架理由")


class PlanTemplateAdoptResponse(BaseModel):
    """采用模板为我的计划。"""

    plan_id: int = Field(..., description="新生成的 plans.id")
    template_id: int