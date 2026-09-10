"""鉴权相关 schema。"""

from pydantic import BaseModel, Field

from app.schemas.user import UserOut


class RegisterIn(BaseModel):
    """注册请求。"""

    username: str = Field(..., min_length=3, max_length=32, description="用户名（中英文/数字/下划线）")
    password: str = Field(..., min_length=8, max_length=20, description="密码（8-20 字符，含字母+数字）")
    nickname: str | None = Field(None, max_length=32)


class LoginIn(BaseModel):
    """登录请求。"""

    username: str
    password: str
    remember_me: bool = Field(default=False, description="是否记住我（影响 Refresh Token 有效期）")


class RefreshIn(BaseModel):
    """刷新 Token 请求。"""

    refresh_token: str


class TokenOut(BaseModel):
    """Token 响应。"""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Access Token 有效期（秒）")
    user: UserOut