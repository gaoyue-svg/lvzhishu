"""认证与用户资料相关 Schema。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RegisterRequest(BaseModel):
    """用户注册请求体。"""

    username: str = Field(min_length=2, max_length=50)
    email: str = Field(pattern=r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$", max_length=100)
    password: str = Field(min_length=6, max_length=100)


class LoginRequest(BaseModel):
    """用户登录请求体。"""

    username: str = Field(min_length=1, max_length=100, description="Username or email")
    password: str


class TokenResponse(BaseModel):
    """JWT 令牌对响应。"""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserProfileResponse(BaseModel):
    """公开用户资料响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    phone: str | None
    avatar: str | None
    role: str
    status: str
    created_at: datetime


class UserProfileUpdateRequest(BaseModel):
    """更新当前用户资料的请求体。"""

    username: str | None = Field(default=None, min_length=2, max_length=50)
    email: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$",
        max_length=100,
    )
    phone: str | None = Field(default=None, max_length=20)


class PasswordUpdateRequest(BaseModel):
    """修改当前用户密码的请求体。"""

    old_password: str = Field(min_length=6, max_length=100)
    new_password: str = Field(min_length=6, max_length=100)
