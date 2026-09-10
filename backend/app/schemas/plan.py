"""训练计划相关 schema。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

GoalType = Literal["muscle_gain", "fat_loss", "body_shape", "endurance"]


class PlanExerciseItem(BaseModel):
    """计划中的一个动作安排。"""

    exercise_id: str = Field(..., description="动作 ID（4 位字符串）")
    sets: int = Field(3, ge=1, le=20, description="组数")
    reps: int = Field(10, ge=1, le=100, description="次数")
    weight_kg: float | None = Field(None, ge=0, description="建议重量（kg）")
    rest_sec: int = Field(60, ge=0, le=600, description="组间休息（秒）")


class PlanDay(BaseModel):
    """一天的训练安排。"""

    day: int = Field(..., ge=1, le=7, description="第几天（周几，1-7）")
    name: str | None = Field(None, max_length=32, description="训练日名称（如'推'/'腿'）")
    exercises: list[PlanExerciseItem] = Field(default_factory=list)


class PlanWeek(BaseModel):
    """一周的训练安排。"""

    week: int = Field(..., ge=1, le=52)
    days: list[PlanDay] = Field(default_factory=list)


class PlanBase(BaseModel):
    """计划公共字段。"""

    name: str = Field(..., min_length=1, max_length=64)
    goal: GoalType
    weeks: list[PlanWeek]
    days_per_week: int = Field(3, ge=1, le=7)
    equipment: list[str] = Field(default_factory=list)


class PlanCreate(PlanBase):
    """创建计划的请求体。"""


class PlanUpdate(BaseModel):
    """更新计划的请求体（所有字段可选）。"""

    name: str | None = None
    goal: GoalType | None = None
    weeks: list[PlanWeek] | None = None
    is_current: bool | None = None
    days_per_week: int | None = None
    equipment: list[str] | None = None


class PlanOut(PlanBase):
    """计划对外返回。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    is_current: int
    created_at: datetime
    updated_at: datetime


class PlanListItem(BaseModel):
    """计划列表项（含统计信息）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: str
    goal: GoalType
    is_current: int
    days_per_week: int
    created_at: datetime
    updated_at: datetime
    # 统计字段
    total_days: int = Field(0, description="计划总训练天数")
    completed_days: int = Field(0, description="已打卡天数")
    progress_pct: float = Field(0.0, description="完成进度（百分比）")
    # 周训练结构（用于卡片渲染动作缩略图）
    weeks: list = Field(default_factory=list, description="周训练结构（含动作 id）")
    # 缩略图（首周前 6 个动作的媒体 URL）
    thumbnails: list = Field(default_factory=list, description="首周前 6 个动作缩略图")


class TrainingRecordIn(BaseModel):
    """提交打卡请求。"""

    plan_id: int
    exercise_id: str
    plan_week: int = Field(..., ge=1)
    plan_day: int = Field(..., ge=1)
    completed_sets: list[bool] = Field(..., description="每组完成情况（true=完成）")


class TrainingRecordOut(BaseModel):
    """打卡记录返回。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    plan_id: int
    exercise_id: str
    plan_week: int
    plan_day: int
    completed_sets: list[bool]
    recorded_at: datetime