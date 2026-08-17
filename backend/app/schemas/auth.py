"""认证模块请求/响应模型（Pydantic v2）。"""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RegisterRequest(BaseModel):
    username: str = Field(
        min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_\u4e00-\u9fa5]+$",
        description="用户名：3-64 位，字母/数字/下划线/中文",
    )
    phone: str | None = Field(default=None, pattern=r"^1[3-9]\d{9}$", description="手机号（可选）")
    password: str = Field(min_length=8, max_length=128, description="密码：至少 8 位")


class LoginRequest(BaseModel):
    account: str = Field(min_length=1, max_length=64, description="用户名或手机号")
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    phone: str | None
    role: str
    created_at: datetime


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int # access token 有效期（秒）


class LoginResult(BaseModel):
    user: UserOut
    tokens: TokenPair


class RegisterResult(BaseModel):
    user: UserOut
    tokens: TokenPair