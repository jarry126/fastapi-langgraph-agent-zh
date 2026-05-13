"""应用限流配置.

本模块使用 slowapi 配置接口限流，默认限流规则来自应用配置。
限流 key 基于请求来源 IP 生成。

配置 Valkey 后会将其作为分布式限流存储，确保多实例部署时
限流计数仍然一致。
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings
from app.core.logging import logger

# 如果配置了 Valkey，则构建存储 URI
_storage_uri = None
if settings.VALKEY_HOST:
    _password_part = f":{settings.VALKEY_PASSWORD}@" if settings.VALKEY_PASSWORD else ""
    _storage_uri = f"redis://{_password_part}{settings.VALKEY_HOST}:{settings.VALKEY_PORT}/{settings.VALKEY_DB}"
    logger.info("rate_limiter_using_valkey", host=settings.VALKEY_HOST, port=settings.VALKEY_PORT)

# 初始化限流器；未配置 Valkey 时使用内存存储
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=settings.RATE_LIMIT_DEFAULT,  # pyright: ignore[reportArgumentType]
    storage_uri=_storage_uri,
)
