"""动作评论 schema。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ReviewCreate(BaseModel):
    """创建/更新一条评论（UPSERT：同 user+exercise 只保留最新一条）。"""

    rating: int = Field(..., ge=1, le=5, description="评分 1-5")
    content: str | None = Field(None, max_length=500, description="评论正文")


class ReviewAuthor(BaseModel):
    """评论里的用户公开信息（昵称 + 头像，不暴露 ID / 手机号）。"""

    model_config = ConfigDict(from_attributes=True)

    nickname: str | None = None
    avatar_url: str | None = None


class ReviewOut(BaseModel):
    """单条评论输出。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    exercise_id: str
    rating: int
    content: str | None = None
    created_at: datetime
    updated_at: datetime
    # 是否为当前请求用户自己的评论（前端用于显示"编辑/删除"按钮）
    is_mine: bool = False
    author: ReviewAuthor | None = None


class ReviewListResponse(BaseModel):
    """评论列表分页响应。"""

    items: list[ReviewOut]
    total: int
    page: int
    page_size: int
    has_more: bool


class ReviewStats(BaseModel):
    """动作评分概览。"""

    avg_rating: float | None = Field(None, description="平均评分；review_count < 5 时为 null")
    review_count: int
