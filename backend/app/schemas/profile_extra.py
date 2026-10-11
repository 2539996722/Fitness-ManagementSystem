"""个人中心扩展 schema。

- WeightLogIn / WeightLogOut / WeightLogList：体重打卡
- MyReviewsListOut：我发过的评论列表
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class WeightLogIn(BaseModel):
    """记一条体重（每次打卡）。"""

    weight_kg: float = Field(..., gt=0, le=500, description="体重 kg")
    recorded_at: Optional[datetime] = Field(None, description="称重时间；空 = 现在")
    note: Optional[str] = Field(None, max_length=64)


class WeightLogOut(BaseModel):
    """单条体重记录。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    weight_kg: float
    recorded_at: datetime
    note: Optional[str] = None
    created_at: datetime


class WeightLogList(BaseModel):
    """体重历史列表（按时间倒序）。"""

    items: list[WeightLogOut]
    total: int


class MyReviewOut(BaseModel):
    """我在动作上的评论（含动作名）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    exercise_id: str
    exercise_name_zh: Optional[str] = None
    rating: int
    content: Optional[str] = None
    status: int
    created_at: datetime
    updated_at: datetime


class MyReviewsList(BaseModel):
    """我发过的评论列表。"""

    items: list[MyReviewOut]
    total: int
    page: int
    page_size: int
    has_more: bool
