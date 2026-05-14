"""应用主入口."""

from contextlib import asynccontextmanager
from datetime import datetime

from dotenv import load_dotenv
from fastapi import (
    FastAPI,
    Request,
    status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from asgi_correlation_id import CorrelationIdMiddleware

from app.api.v1.api import api_router
from app.api.v1.chatbot import agent
from app.core.cache import cache_service
from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import logger
from app.core.metrics import setup_metrics
from app.core.middleware import (
    LoggingContextMiddleware,
    MetricsMiddleware,
    ProfilingMiddleware,
)
from app.core.observability import langfuse_init
from app.services.database import database_service
from app.services.memory import memory_service

# 加载环境变量
load_dotenv()
langfuse_init()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """处理应用启动和关闭事件."""
    logger.info(
        "application_startup",
        project_name=settings.PROJECT_NAME,
        version=settings.VERSION,
        api_prefix=settings.API_V1_STR,
    )

    # 初始化缓存服务；如果配置了 Valkey，则连接 Valkey
    try:
        await cache_service.initialize()
    except Exception as e:
        logger.exception("cache_initialization_failed", error=str(e))

    # 预热 LangGraph 智能体：启动时创建图和连接池，避免第一次请求承担冷启动延迟
    try:
        await agent.create_graph()
        logger.info("graph_pre_warmed")
    except Exception as e:
        logger.exception("graph_pre_warm_failed", error=str(e))

    # 预热 mem0 AsyncMemory：初始化 pgvector 连接并检查 schema，避免首次检索或写入承担冷启动成本
    try:
        await memory_service.initialize()
    except Exception as e:
        logger.exception("memory_service_pre_warm_failed", error=str(e))

    yield

    # 应用关闭时清理资源
    await cache_service.close()
    if agent._connection_pool:
        await agent._connection_pool.close()
        logger.info("connection_pool_closed")
    logger.info("application_shutdown")


"""
    项目说明：
    这个项目是一个生产化 AI Agent 后端模板。API 层使用 FastAPI，Agent 工作流使用 LangGraph，LLM 和工具调用抽象使用 LangChain。用户、session 等业务数据使用 PostgreSQL/SQLModel 存储。
短期会话状态由 LangGraph checkpoint 管理，底层通过 AsyncPostgresSaver 存入 PostgreSQL。长期记忆由 mem0 管理，mem0 负责从对话中抽取、更新和检索长期记忆，底层使用 PostgreSQL + pgvector 保存 memory 文本、metadata 和 embedding 向量。
配置通过 .env / 环境变量管理，真实 .env 不应提交，.env.example 作为模板。部署层目前提供 Dockerfile 和 docker-compose，可启动 API、PostgreSQL、Valkey、Prometheus、Grafana 等服务；生产可以扩展到 K8s。观测层包括 structlog 日志、Prometheus/Grafana 指标监控，以及 Langfuse 的 LLM 调用追踪。

"""

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=settings.DESCRIPTION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan, # 生命时周期
)

# 配置 Prometheus 指标
setup_metrics(app)

# 中间件的执行顺序与 add_middleware 的调用顺序相反（LIFO）：
# 实际请求处理顺序：CorrelationId → Profiling → Metrics → LoggingContext → 路由处理
# 因此 CorrelationId 必须最后 add，才能最先执行，保证 request_id 在所有后续中间件中可用

# 统计接口请求数据，上报给 Prometheus。
app.add_middleware(LoggingContextMiddleware)
# 把 session_id / user_id 注入到日志上下文，让这次请求的所有日志都自动带上这两个字段。
app.add_middleware(MetricsMiddleware)

# 仅在 DEBUG 模式下启用性能分析，慢请求会将 HTML 报告写入 /tmp
if settings.DEBUG:
    app.add_middleware(ProfilingMiddleware)

app.add_middleware(CorrelationIdMiddleware)

# slowapi 限流器需要通过 app.state.limiter 挂载，@limiter.limit() 装饰器在请求时会从这里读取配置
app.state.limiter = limiter


async def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """限流超限时返回友好提示，并通过 structlog 记录结构化日志.

    替换 slowapi 内置的 _rate_limit_exceeded_handler，解决两个问题：
    1. 内置 handler 直接 print 到 stdout，绕过 structlog，格式与其他日志不一致。
    2. 内置返回体只有英文技术信息，对用户不友好。
    """
    limit_str = str(exc.detail) if exc.detail else "未知限额"
    path = request.url.path
    user_id = getattr(request.state, "user_id", None)
    client_ip = request.client.host if request.client else "unknown"
    rate_limit_key = f"user:{user_id}" if user_id else client_ip

    logger.warning(
        "请求频率超出限制",
        path=path,
        rate_limit_key=rate_limit_key,
        limit=limit_str,
        client_ip=client_ip,
    )

    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "detail": "请求过于频繁，请稍后再试",
            "limit": limit_str,
            "hint": "如持续受限，请联系管理员",
        },
    )


# 请求超出限流阈值时 slowapi 抛出 RateLimitExceeded，注册自定义处理器统一转为友好的 429 响应
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # pyright: ignore[reportArgumentType]


# 添加请求参数校验异常处理器
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """处理请求数据校验错误.

    参数：
        request: 触发校验错误的请求。
        exc: 校验错误对象。

    返回：
        JSONResponse: A formatted error response
    """
    # 记录校验错误
    logger.error(
        "validation_error",
        client_host=request.client.host if request.client else "unknown",
        path=request.url.path,
        errors=str(exc.errors()),
    )

    # 将错误格式化为更适合用户阅读的内容
    formatted_errors = []
    for error in exc.errors():
        loc = " -> ".join([str(loc_part) for loc_part in error["loc"] if loc_part != "body"])
        formatted_errors.append({"field": loc, "message": error["msg"]})

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": "Validation error", "errors": formatted_errors},
    )


# 配置 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载 API 路由
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["root"][0])
async def root(request: Request):
    """根接口，返回基础 API 信息."""
    logger.info("root_endpoint_called")
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "healthy",
        "environment": settings.ENVIRONMENT.value,
        "swagger_url": "/docs",
        "redoc_url": "/redoc",
    }


@app.get("/health")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["health"][0])
async def health_check(request: Request) -> JSONResponse:
    """健康检查接口，返回当前环境相关信息.

    返回：
        JSONResponse: Health status payload, with HTTP 503 when the
        database is unreachable so load balancers can drop the instance.
    """
    logger.info("health_check_called")

    # 检查数据库连接状态
    db_healthy = await database_service.health_check()

    response = {
        "status": "healthy" if db_healthy else "degraded",
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT.value,
        "components": {"api": "healthy", "database": "healthy" if db_healthy else "unhealthy"},
        "timestamp": datetime.now().isoformat(),
    }

    # 如果数据库不可用，设置对应状态码
    status_code = status.HTTP_200_OK if db_healthy else status.HTTP_503_SERVICE_UNAVAILABLE

    return JSONResponse(content=response, status_code=status_code)
