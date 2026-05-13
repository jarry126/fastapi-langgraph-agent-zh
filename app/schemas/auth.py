"""鉴权相关 schema."""

import re
from datetime import datetime

from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    SecretStr,
    field_validator,
)

from app.schemas.base import BaseResponse


class Token(BaseModel):
    """鉴权 token 模型.

    Attributes:
        access_token: JWT 访问 token。
        token_type: token 类型，固定为 bearer。
        expires_at: token 过期时间。
    """

    access_token: str = Field(..., description="JWT 访问 token")
    token_type: str = Field(default="bearer", description="token 类型")
    expires_at: datetime = Field(..., description="token 过期时间")


class TokenResponse(BaseResponse):
    """登录接口响应模型.

    Attributes:
        access_token: JWT 访问 token
        token_type: token 类型（固定为 "bearer"）
        expires_at: token 过期时间。
    """

    access_token: str = Field(..., description="JWT 访问 token")
    token_type: str = Field(default="bearer", description="token 类型")
    expires_at: datetime = Field(..., description="token 过期时间")


class UserCreate(BaseModel):
    """用户注册请求模型.

    Attributes:
        email: 用户邮箱。 address
        password: 用户密码。
        username: 可选显示名称。
    """

    email: EmailStr = Field(..., description="用户邮箱地址")
    password: SecretStr = Field(..., description="用户密码", min_length=8, max_length=64)
    username: str | None = Field(default=None, description="可选显示名称", max_length=50)

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: SecretStr) -> SecretStr:
        """校验密码强度.

        参数：
            v: 要校验的密码。

        返回：
            SecretStr: 校验后的密码。

        抛出：
            ValueError: 密码强度不足时抛出。
        """
        password = v.get_secret_value()

        # 检查常见密码强度要求
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters long")

        if not re.search(r"[A-Z]", password):
            raise ValueError("Password must contain at least one uppercase letter")

        if not re.search(r"[a-z]", password):
            raise ValueError("Password must contain at least one lowercase letter")

        if not re.search(r"[0-9]", password):
            raise ValueError("Password must contain at least one number")

        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            raise ValueError("Password must contain at least one special character")

        return v


class UserResponse(BaseResponse):
    """用户操作响应模型.

    Attributes:
        id: User's ID
        email: 用户邮箱。 address
        username: 可选显示名称。
        token: Authentication token
    """

    id: int = Field(..., description="用户 ID")
    email: str = Field(..., description="用户邮箱地址")
    username: str | None = Field(default=None, description="可选显示名称")
    token: Token = Field(..., description="鉴权 token")


class SessionResponse(BaseResponse):
    """会话创建响应模型.

    Attributes:
        session_id: 聊天会话唯一标识。
        name: Name of the session (defaults to empty string)
    """

    session_id: str = Field(..., description="聊天会话唯一标识")
    name: str = Field(default="", description="会话名称", max_length=100)

    @field_validator("name")
    @classmethod
    def sanitize_name(cls, v: str) -> str:
        """清理会话名称.

        参数：
            v: 要清理的名称。

        返回：
            str: 清理后的名称。
        """
        # 移除潜在有害字符
        sanitized = re.sub(r'[<>{}[\]()\'"`]', "", v)
        return sanitized
