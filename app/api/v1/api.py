"""API v1 路由配置.

This module sets up the main API router and includes all sub-routers for different
endpoints like authentication and chatbot functionality.
"""

from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.chatbot import router as chatbot_router
from app.api.v1.debug import router as debug_router
from app.core.logging import logger

api_router = APIRouter()

# 挂载路由
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(chatbot_router, prefix="/chatbot", tags=["chatbot"])
# 调试接口：仅开发 / 测试环境返回数据，生产环境返回 403
api_router.include_router(debug_router, prefix="/debug", tags=["debug"])


@api_router.get("/health")
async def health_check():
    """健康检查接口.

    返回：
        dict: 健康状态信息。
    """
    logger.info("health_check_called")
    return {"status": "healthy", "version": "1.0.0"}
