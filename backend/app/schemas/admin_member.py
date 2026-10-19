"""B 端会员管理 schema（PRD §5.2.1）。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class UserListItem(BaseModel):
    """会员列表行。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    nickname: str | None = None
    role: str
    status: int
    created_at: datetime
    last_login_at: datetime | None = None
    remark: str | None = None
    # 关联统计（来自子查询）
    plan_count: int = 0
    ai_msg_count: int = 0


class UserListResponse(BaseModel):
    items: list[UserListItem]
    total: int
    page: int
    page_size: int
    has_more: bool


class PlanBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    goal: str
    is_current: int
    created_at: datetime


class ConversationBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    status: str
    conversation_type: str
    updated_at: datetime


class UserDetail(BaseModel):
    """会员详情（弹窗/抽屉用）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    nickname: str | None = None
    avatar_url: str | None = None
    gender: int
    age: int | None = None
    height_cm: float | None = None
    weight_kg: float | None = None
    role: str
    status: int
    remark: str | None = None
    created_at: datetime
    last_login_at: datetime | None = None
    # 关联数据
    plan_count: int = 0
    ai_msg_count: int = 0
    recent_plans: list[PlanBrief] = []
    recent_conversations: list[ConversationBrief] = []


class UserStatusUpdate(BaseModel):
    """封禁 / 解封请求体。"""

    status: int = Field(..., ge=0, le=1, description="0=正常 1=封禁")
    reason: str | None = Field(None, max_length=255, description="封禁/解封原因（封禁时必填）")


class UserRemarkUpdate(BaseModel):
    remark: str | None = Field(None, max_length=255)


class UserResetPasswordOut(BaseModel):
    """重置密码返回（一次性显示给管理员）。"""

    user_id: int
    username: str
    new_password: str


class UserCreate(BaseModel):
    """admin 新建用户请求体。"""

    username: str = Field(..., min_length=3, max_length=32, description="3-32 字符，字母数字下划线中文")
    password: str | None = Field(None, min_length=8, max_length=20, description="留空则自动生成 10 位随机密码")
    nickname: str | None = Field(None, max_length=32)
    role: Literal["user", "trainer", "admin"] = Field(
        "user", description="默认 user，可创建任意角色"
    )
    remark: str | None = Field(None, max_length=255, description="初始备注（可选）")


class UserCreateOut(BaseModel):
    """admin 新建用户返回。"""

    user: UserListItem
    initial_password: str = Field(..., description="明文密码，仅返回一次（管理员需告知用户）")
