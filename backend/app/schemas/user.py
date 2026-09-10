"""用户相关 schema。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserBase(BaseModel):
    """用户公共字段。"""

    username: str = Field(..., min_length=3, max_length=32, description="登录名")
    nickname: str | None = Field(None, max_length=32)


class UserCreate(UserBase):
    """创建用户（C 端注册）。"""

    password: str = Field(..., min_length=8, max_length=20, description="密码（8-20 字符）")


class UserOut(BaseModel):
    """用户对外返回（不含密码哈希）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    nickname: str | None = None
    avatar_url: str | None = None
    gender: int = 0
    age: int | None = None
    height_cm: float | None = None
    weight_kg: float | None = None
    role: str
    status: int
    created_at: datetime
    last_login_at: datetime | None = None