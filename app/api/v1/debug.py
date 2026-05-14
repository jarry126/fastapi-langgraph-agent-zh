"""限流调试接口（仅开发 / 测试环境可用）.

用于查看 slowapi 当前的限流计数和存储结构，帮助理解内存存储与 Redis 存储的数据格式。
生产环境访问该接口会返回 403。
"""

import time
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from app.core.config import Environment, settings
from app.core.limiter import limiter
from app.core.logging import logger

router = APIRouter()


def _guard_non_prod() -> None:
    """非开发 / 测试环境直接拒绝，防止内部信息泄露."""
    if settings.ENVIRONMENT not in (Environment.DEVELOPMENT, Environment.TEST):
        raise HTTPException(status_code=403, detail="此接口仅在开发 / 测试环境可用")


def _get_limiter_storage() -> Any:
    """兼容不同版本 slowapi / limits 的存储对象获取方式.

    slowapi 内部结构：
      limiter（SlowAPI）
        ._limiter（FixedWindowRateLimiter / MovingWindowRateLimiter）
          .storage  ← 实际存储对象（MemoryStorage / RedisStorage）

    注意：`.storage` 是公开属性，`._storage` 在部分版本中不存在。
    """
    rate_limiter = limiter._limiter  # FixedWindowRateLimiter
    # 优先取公开属性 .storage，兜底取私有属性 ._storage（旧版本兼容）
    storage = getattr(rate_limiter, "storage", None) or getattr(rate_limiter, "_storage", None)
    if storage is None:
        raise AttributeError(f"无法从 {type(rate_limiter).__name__} 中获取 storage 对象")
    return storage


def _get_raw_storage_dict(storage: Any) -> Dict[str, Any]:
    """从内存存储对象中读取原始计数字典.

    不同版本 limits 库的内存存储类内部字典属性名不同，按优先级依次尝试。
    """
    for attr in ("_storage", "storage", "_data", "data"):
        candidate = getattr(storage, attr, None)
        if isinstance(candidate, dict):
            return dict(candidate)
    return {}


@router.get("/rate-limit/ping")
@limiter.limit("10/minute")
async def rate_limit_ping(request: Request) -> Dict[str, Any]:
    """专用限流压测接口：极轻量，无 DB / LLM 调用，直接触发 slowapi 计数.

    **适用场景**：用 JMeter / wrk / ab 等工具做并发测试，验证 slowapi 是否正确
    按用户 ID（或 IP）计数并在超限时返回 429。

    **限额**：10次 / 分钟（固定，不走 settings.RATE_LIMIT_ENDPOINTS）。

    **测试步骤**：
    1. 登录拿到 token，在 JMeter 的 HTTP Header Manager 中加 `Authorization: Bearer <token>`
    2. 线程数设为 15，循环 1 次，Ramp-Up 设为 0（瞬间并发）
    3. 前 10 个请求返回 200，后续请求返回 429

    **返回示例**：
    ```json
    {
        "ok": true,
        "server_time_ms": 1715652305123,
        "rate_limit_key": "user:42",
        "message": "此接口限额 10次/分钟，超限返回 429"
    }
    ```
    """
    _guard_non_prod()

    key = getattr(request.state, "user_id", None)
    rate_limit_key = f"user:{key}" if key else request.client.host if request.client else "unknown"

    logger.info("限流压测 ping", rate_limit_key=rate_limit_key)

    return {
        "ok": True,
        "server_time_ms": int(time.time() * 1000),
        "rate_limit_key": rate_limit_key,
        "message": "此接口限额 10次/分钟，超限返回 429",
    }


@router.get("/rate-limit/storage-info")
async def rate_limit_storage_info() -> Dict[str, Any]:
    """查看当前限流存储的类型和所有计数数据.

    返回：
        存储类型、存储后端信息、所有 key 的当前计数。

    ---
    ## 内存存储时的返回示例

    ```json
    {
        "storage_backend": "memory",
        "storage_class": "MemoryStorage",
        "description": "数据存储在当前进程内存中，服务重启后清零，多实例部署时各自独立计数",
        "items": {
            "LIMITER/user:42/10/1/minute": {
                "count": 3,
                "ttl_seconds": 47,
                "key_解读": {
                    "维度": "user:42（用户ID=42）",
                    "限制": "10次 / 1分钟",
                    "当前计数": 3,
                    "距离重置还剩": "47秒"
                }
            }
        }
    }
    ```

    ## Redis 存储时的返回示例

    ```json
    {
        "storage_backend": "redis",
        "storage_class": "RedisStorage",
        "redis_url": "redis://:***@r-xxx.redis.rds.aliyuncs.com:6379",
        "description": "数据存储在 Redis 中，多实例共享计数，服务重启后计数保留直到 TTL 过期",
        "note": "Redis 存储无法直接枚举所有 key，请使用 /rate-limit/check?key=xxx 查询指定 key"
    }
    ```
    """
    _guard_non_prod()

    try:
        storage = _get_limiter_storage()
        storage_class = type(storage).__name__
        storage_module = type(storage).__module__

        # 判断是内存存储还是 Redis 存储
        is_memory = "memory" in storage_class.lower() or "memory" in storage_module.lower()

        if is_memory:
            # 内存存储：直接读取内部字典
            raw_storage: Dict[str, Any] = _get_raw_storage_dict(storage)

            # 解析每个 key 的含义
            parsed_items: Dict[str, Any] = {}
            for key, value in raw_storage.items():
                count = value if isinstance(value, int) else getattr(value, "count", str(value))
                parsed_items[key] = {
                    "raw_value": str(value),
                    "key_解读": _parse_limiter_key(key, count),
                }

            logger.info("限流内存存储数据已查询", item_count=len(parsed_items))
            return {
                "storage_backend": "memory",
                "storage_class": storage_class,
                "description": "数据存储在进程内存中，服务重启清零，多实例各自独立计数",
                "total_keys": len(parsed_items),
                "items": parsed_items,
                "key_格式说明": "LIMITER/{限流key}/{接口路径}/{限制次数}/{窗口数}/{窗口单位}",
            }
        else:
            # Redis 存储：不能直接枚举所有 key（生产环境 KEYS * 命令有风险）
            redis_url = ""
            if hasattr(storage, "_uri"):
                redis_url = _mask_password(str(storage._uri))
            elif hasattr(storage, "uri"):
                redis_url = _mask_password(str(storage.uri))

            logger.info("限流 Redis 存储信息已查询")
            return {
                "storage_backend": "redis",
                "storage_class": storage_class,
                "redis_url": redis_url,
                "description": "数据存储在 Redis 中，多实例共享计数，TTL 过期前计数保留",
                "redis_key_格式": "LIMITER/{限流key}/{接口路径}/{限制次数}/{窗口数}/{窗口单位}",
                "redis_key_示例": "LIMITER/user:42//api/v1/chatbot/chat/10/1/minute",
                "note": "Redis 存储不枚举全量 key，请使用 /debug/rate-limit/check 查询指定用户",
            }

    except Exception as e:
        logger.exception("查询限流存储失败", error=str(e))
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


@router.get("/rate-limit/check")
async def rate_limit_check(user_id: str) -> Dict[str, Any]:
    """查询指定用户的当前限流计数.

    参数：
        user_id: 要查询的用户 ID（不含 user: 前缀）。

    返回：
        该用户在各接口的当前计数和剩余配额。

    ---
    ## 请求示例

    ```
    GET /debug/rate-limit/check?user_id=42
    ```

    ## 返回示例

    ```json
    {
        "query_key": "user:42",
        "storage_backend": "memory",
        "matched_keys": {
            "LIMITER/user:42/10/1/minute": {
                "count": 3,
                "limit": 10,
                "window": "1/minute",
                "remaining": 7
            }
        }
    }
    ```
    """
    _guard_non_prod()

    try:
        storage = _get_limiter_storage()
        storage_class = type(storage).__name__
        is_memory = "memory" in storage_class.lower() or "memory" in type(storage).__module__.lower()

        query_key = f"user:{user_id}"

        if is_memory:
            raw_storage: Dict[str, Any] = _get_raw_storage_dict(storage)

            matched: Dict[str, Any] = {}
            for key, value in raw_storage.items():
                if query_key in key:
                    count = value if isinstance(value, int) else getattr(value, "count", 0)
                    parsed = _parse_limiter_key(key, count)
                    matched[key] = parsed

            return {
                "query_key": query_key,
                "storage_backend": "memory",
                "matched_count": len(matched),
                "matched_keys": matched,
            }
        else:
            # Redis 存储：尝试直接用 GET 查询特定 key
            return {
                "query_key": query_key,
                "storage_backend": "redis",
                "note": "Redis 存储请直接用 redis-cli 查询：GET 'LIMITER/user:{user_id}/...'",
                "redis_cli_示例": f"redis-cli GET 'LIMITER/{query_key}/10/1/minute'",
            }

    except Exception as e:
        logger.exception("查询用户限流计数失败", user_id=user_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


def _parse_limiter_key(key: str, count: Any) -> Dict[str, Any]:
    """把 slowapi 的内部 key 解析成可读格式.

    slowapi 实际 key 格式（含接口路径）：
        LIMITER/{限流维度}/{endpoint_path}/{limit}/{period}/{granularity}
    示例：
        LIMITER/user:42//api/v1/chatbot/chat/30/1/minute

    末尾三段固定为 limit / period / granularity，其余中间段拼回路径。
    """
    try:
        parts = key.split("/")
        # 至少需要：LIMITER + 限流维度 + limit + period + granularity = 5 段
        if len(parts) >= 5:
            granularity = parts[-1]          # minute / hour / day
            period      = parts[-2]          # 1 / 60 ...
            limit_str   = parts[-3]          # 10 / 30 ...
            dimension   = parts[1]           # user:42 / 127.0.0.1
            # 中间段（去掉首尾已知字段）拼回路径，过滤空串（双斜杠产生的空段）
            path_parts  = parts[2:-3]
            endpoint    = "/" + "/".join(p for p in path_parts if p)

            limit   = int(limit_str)
            current = int(count) if str(count).isdigit() else count
            return {
                "限流维度": dimension,
                "接口路径": endpoint,
                "限制次数": limit,
                "时间窗口": f"{period}/{granularity}",
                "当前计数": current,
                "剩余次数": max(0, limit - int(current)) if str(current).isdigit() else "未知",
            }
    except Exception:
        pass
    return {"raw_key": key, "count": str(count)}


def _mask_password(url: str) -> str:
    """脱敏 Redis URL 中的密码."""
    import re
    return re.sub(r":([^@]+)@", ":***@", url)
