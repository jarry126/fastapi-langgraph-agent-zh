"""应用限流配置.

本模块使用 slowapi 配置接口限流，默认限流规则来自应用配置。

## 限流维度说明

当前使用「按用户 ID 限流」：每个登录用户拥有独立的请求配额，互不干扰。
未登录请求降级为按 IP 限流兜底。

适用场景：
- 项目有完整的 JWT 登录体系，用户身份明确
- 避免公司/学校多人共用同一出口 IP 时互相消耗配额

如需切换为「按 IP 限流」（所有用户共享同一 IP 配额），
注释掉 get_user_id 的 key_func，改用 get_remote_address，见下方注释。

## 存储后端说明

- 未配置 Valkey：使用进程内存存储，单实例部署时完全正常
- 配置 Valkey 后：使用分布式存储，多实例/多 Pod 部署时计数共享，限流准确

"""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings
from app.core.logging import logger


def get_user_id(request: Request) -> str:
    """按用户 ID 生成限流 key.

    已登录用户使用 user_id 作为限流维度，每个用户配额独立互不影响。
    未登录请求（无法解析 user_id）降级为按客户端 IP 兜底，
    防止匿名请求绕过限流。

    参数：
        request: FastAPI 请求对象。

    返回：
        str: 限流 key，格式为 "user:{user_id}" 或客户端 IP。
    """
    # user_id 由 LoggingContextMiddleware 在鉴权后写入 request.state
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"user:{user_id}"
    # 未登录请求降级为 IP 限流兜底
    return get_remote_address(request)

# 如果配置了 Valkey，则构建分布式存储 URI
_storage_uri = None
if settings.VALKEY_HOST:
    _password_part = f":{settings.VALKEY_PASSWORD}@" if settings.VALKEY_PASSWORD else ""
    _storage_uri = f"redis://{_password_part}{settings.VALKEY_HOST}:{settings.VALKEY_PORT}/{settings.VALKEY_DB}"
    logger.info("限流存储已连接 Valkey", host=settings.VALKEY_HOST, port=settings.VALKEY_PORT)

# 初始化限流器
# 当前：按用户 ID 限流，每个登录用户独立计数
# 切换为按 IP 限流：将 key_func 改为 get_remote_address
limiter = Limiter(
    key_func=get_user_id,           # 按用户 ID 限流
    # key_func=get_remote_address,  # 按 IP 限流（切换时取消注释，注释上一行）
    default_limits=settings.RATE_LIMIT_DEFAULT,  # pyright: ignore[reportArgumentType]
    storage_uri=_storage_uri,       # None 时自动使用进程内存存储
)
