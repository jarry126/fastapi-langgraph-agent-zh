"""所有接口共享的基础响应 schema."""

from uuid import UUID, uuid4

from asgi_correlation_id import correlation_id
from pydantic import BaseModel, Field


def _get_request_id() -> UUID:
    """返回当前请求的 correlation ID；不存在时生成新的 UUID."""
    value = correlation_id.get()
    return UUID(value) if value else uuid4()


class BaseResponse(BaseModel):
    """所有接口响应继承的基础响应模型.

    request_id is auto-populated from the CorrelationIdMiddleware ContextVar —
    no endpoint needs to pass it explicitly.
    """

    request_id: UUID = Field(default_factory=_get_request_id, description="本次请求的唯一标识")
