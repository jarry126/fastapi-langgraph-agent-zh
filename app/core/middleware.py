"""用于指标统计和通用横切逻辑的自定义中间件."""

import json
import time
import tracemalloc
from typing import (
    TYPE_CHECKING,
    Callable,
    override,
)

from asgi_correlation_id import correlation_id
from fastapi import Request
from jose import (
    JWTError,
    jwt,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.config import settings
from app.core.logging import (
    bind_context,
    clear_context,
    logger,
)
from app.core.metrics import (
    http_request_duration_seconds,
    http_requests_total,
)

if TYPE_CHECKING:
    from pyinstrument import Profiler  # pyright: ignore[reportMissingImports]
    from pyinstrument.renderers import JSONRenderer  # pyright: ignore[reportMissingImports]

    PYINSTRUMENT_AVAILABLE = True
else:
    try:
        from pyinstrument import Profiler
        from pyinstrument.renderers import JSONRenderer

        PYINSTRUMENT_AVAILABLE = True
    except ImportError:
        Profiler = None
        JSONRenderer = None
        PYINSTRUMENT_AVAILABLE = False


class MetricsMiddleware(BaseHTTPMiddleware):
    """统计 HTTP 请求指标的中间件."""

    @override
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """统计每个请求的指标.

        参数：
            request: 传入的请求。
            call_next: 下一个中间件或路由处理器。

        返回：
            Response: 应用响应。
        """
        start_time = time.time()
        status_code = 500

        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            raise
        finally:
            duration = time.time() - start_time

            # 记录指标
            http_requests_total.labels(method=request.method, endpoint=request.url.path, status=status_code).inc()

            http_request_duration_seconds.labels(method=request.method, endpoint=request.url.path).observe(duration)

        return response


class LoggingContextMiddleware(BaseHTTPMiddleware):
    """将 user_id 和 session_id 添加到日志上下文的中间件."""

    @override
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """从已鉴权请求中提取 user_id/session_id，并添加到日志上下文.

        参数：
            request: 传入的请求。
            call_next: 下一个中间件或路由处理器。

        返回：
            Response: 应用响应。
        """
        start_time   = time.time()
        status_code  = 500
        path         = request.url.path
        method       = request.method

        try:
            # 清理上一次请求残留的上下文
            clear_context()

            # 从 Authorization 请求头提取 token，解出 user_id 并绑定到日志上下文
            auth_header = request.headers.get("authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.split(" ")[1]
                try:
                    payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
                    user_id = payload.get("sub")
                    if user_id:
                        bind_context(user_id=user_id)
                        # 同时写入 request.state，供限流器 get_user_id() 读取
                        request.state.user_id = user_id
                except JWTError:
                    # token 无效时不在中间件失败，交给鉴权依赖处理
                    pass

            if path != "/metrics":
                # 收集请求参数用于日志
                query_params = dict(request.query_params) or None
                body_for_log = None

                # POST/PUT/PATCH 读取 JSON body 并记录（Starlette 会缓存 body，后续 handler 仍可读取）
                if method in ("POST", "PUT", "PATCH"):
                    content_type = request.headers.get("content-type", "")
                    if "application/json" in content_type:
                        try:
                            raw_body = await request.body()
                            if raw_body:
                                body_data = json.loads(raw_body.decode("utf-8"))
                                # 脱敏：密码、token 等敏感字段替换为 ***
                                _SENSITIVE = {"password", "token", "secret", "api_key", "access_token"}
                                if isinstance(body_data, dict):
                                    body_for_log = {
                                        k: "***" if k.lower() in _SENSITIVE else v
                                        for k, v in body_data.items()
                                    }
                                else:
                                    body_for_log = body_data
                        except Exception:
                            pass

                logger.info(
                    "收到请求",
                    parameters={
                        k: v for k, v in {
                            "method": method,
                            "path": path,
                            "query": query_params,
                            "body": body_for_log,
                            "client": request.client.host if request.client else None,
                        }.items() if v is not None
                    },
                )

            # 处理请求
            response = await call_next(request)
            status_code = response.status_code

            if hasattr(request.state, "user_id"):
                bind_context(user_id=request.state.user_id)

            return response

        except Exception:
            status_code = 500
            raise
        finally:
            if path != "/metrics":
                duration_ms = round((time.time() - start_time) * 1000, 2)
                logger.info(
                    "请求完成",
                    parameters={
                        "method": method,
                        "path": path,
                        "status": status_code,
                        "duration_ms": duration_ms,
                    },
                )
            # 请求完成后清理上下文，防止 span_id / user_id 泄漏到下一个请求
            clear_context()


class ProfilingMiddleware(BaseHTTPMiddleware):
    """使用 pyinstrument 的按请求自动性能分析中间件.

    Only active when DEBUG=true. Profiles every request and saves an HTML
    flamegraph to PROFILING_DIR when the request exceeds
    PROFILING_THRESHOLD_SECONDS. Files are named {request_id}.html so they
    can be correlated with logs. /tmp is cleaned up automatically by the OS.
    """

    @override
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """分析每个请求；超过阈值时保存增强 JSON 报告."""
        if not PYINSTRUMENT_AVAILABLE:
            return await call_next(request)

        # 启动性能、CPU 和内存分析
        tracemalloc.start()
        cpu_start = time.process_time()

        profiler = Profiler(async_mode="enabled")
        with profiler:
            response = await call_next(request)

        # 请求完成后立即采集指标
        cpu_ms = round((time.process_time() - cpu_start) * 1000, 2)
        mem_current_kb, mem_peak_kb = (v // 1024 for v in tracemalloc.get_traced_memory())
        snapshot = tracemalloc.take_snapshot()
        tracemalloc.stop()

        wall_ms = round((profiler.last_session.duration if profiler.last_session else 0.0) * 1000, 2)

        if wall_ms / 1000 >= settings.PROFILING_THRESHOLD_SECONDS:
            raw_id = correlation_id.get() or "unknown"
            if len(raw_id) == 32 and "-" not in raw_id:
                raw_id = f"{raw_id[:8]}-{raw_id[8:12]}-{raw_id[12:16]}-{raw_id[16:20]}-{raw_id[20:]}"

            settings.PROFILING_DIR.mkdir(parents=True, exist_ok=True)
            filepath = settings.PROFILING_DIR / f"{raw_id}.json"

            # 内存分配最多的 20 个位置，排除 profiler 和标准库噪声
            _excluded = ("tracemalloc", "pyinstrument", "<frozen", "logging/__init__")
            top_allocs = [
                {
                    "file": str(stat.traceback[0].filename).replace(str(__file__).rsplit("/", 3)[0] + "/", ""),
                    "line": stat.traceback[0].lineno,
                    "size_kb": round(stat.size / 1024, 2),
                    "count": stat.count,
                }
                for stat in snapshot.statistics("lineno")
                if not any(ex in str(stat.traceback[0].filename) for ex in _excluded)
            ]

            call_tree = json.loads(profiler.output(renderer=JSONRenderer()))
            report = {
                "request_id": raw_id,
                "endpoint": f"{request.method} {request.url.path}",
                "wall_time_ms": wall_ms,
                "cpu_time_ms": cpu_ms,
                "io_wait_ms": round(wall_ms - cpu_ms, 2),
                "memory_peak_kb": mem_peak_kb,
                "memory_allocated_kb": mem_current_kb,
                "top_memory_allocators": top_allocs,
                "call_tree": call_tree,
            }
            filepath.write_text(json.dumps(report, indent=2))
            logger.debug(
                "slow_request_profile_saved",
                path=request.url.path,
                method=request.method,
                wall_time_ms=wall_ms,
                cpu_time_ms=cpu_ms,
                memory_peak_kb=mem_peak_kb,
                io_wait_ms=round(wall_ms - cpu_ms, 2),
                profile_file=str(filepath),
            )

        return response
