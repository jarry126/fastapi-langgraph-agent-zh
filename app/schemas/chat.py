"""聊天相关 schema."""

import re
from typing import (
    List,
    Literal,
)

from pydantic import (
    BaseModel,
    Field,
    field_validator,
)

from app.schemas.base import BaseResponse


class Message(BaseModel):
    """聊天接口的消息模型.

    Attributes:
        role: 消息发送方角色。
        content: 消息内容。
    """

    model_config = {"extra": "ignore"}

    role: Literal["user", "assistant", "system"] = Field(..., description="消息发送方角色")
    content: str = Field(..., description="消息内容", min_length=1, max_length=3000)

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        """校验消息内容.

        参数：
            v: 要校验的内容。

        返回：
            str: 校验后的内容。

        抛出：
            ValueError: 内容包含不允许的模式时抛出。
        """
        # 检查潜在恶意内容
        if re.search(r"<script.*?>.*?</script>", v, re.IGNORECASE | re.DOTALL):
            raise ValueError("Content contains potentially harmful script tags")

        # 检查空字节
        if "\0" in v:
            raise ValueError("Content contains null bytes")

        return v


class ChatRequest(BaseModel):
    """聊天接口请求模型.

    Attributes:
        session_id: Chat session ID owned by the authenticated user.
        messages: 会话中的消息列表。
    """

    session_id: str = Field(..., description="聊天会话 ID")
    messages: List[Message] = Field(
        ...,
        description="会话中的消息列表",
        min_length=1,
    )


class ChatResponse(BaseResponse):
    """聊天接口响应模型.

    Attributes:
        messages: 会话中的消息列表。
    """

    messages: List[Message] = Field(..., description="会话中的消息列表")


class StreamResponse(BaseResponse):
    """流式聊天接口响应模型.

    Attributes:
        content: 当前分片内容。
        done: Whether the stream is complete.
    """

    content: str = Field(default="", description="当前分片内容")
    done: bool = Field(default=False, description="流式响应是否完成")


class SessionTitle(BaseModel):
    """会话标题生成的结构化输出 schema."""

    title: str = Field(
        ...,
        min_length=1,
        max_length=60,
    )

    @field_validator("title")
    @classmethod
    def _normalize(cls, v: str) -> str:
        v = " ".join(v.split()).strip(" \"'`.,:;!?-")
        if not v:
            raise ValueError("empty title after normalization")
        return v
