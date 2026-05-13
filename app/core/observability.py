"""应用观测能力模块."""

from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

from app.core.config import settings
from app.core.logging import logger


def langfuse_init():
    """初始化 Langfuse."""
    if not settings.LANGFUSE_TRACING_ENABLED:
        logger.info("langfuse_tracing_disabled")
        return

    langfuse = Langfuse(
        tracing_enabled=settings.LANGFUSE_TRACING_ENABLED,
        public_key=settings.LANGFUSE_PUBLIC_KEY,
        secret_key=settings.LANGFUSE_SECRET_KEY,
        host=settings.LANGFUSE_HOST,
        environment=settings.ENVIRONMENT.value,
        debug=settings.DEBUG,
    )

    try:
        if langfuse.auth_check():
            logger.debug("langfuse_auth_success")
        else:
            logger.debug("langfuse_auth_failure")
    except Exception as e:
        logger.warning("langfuse_auth_check_failed", error=str(e))


def get_langfuse_callback_handler() -> CallbackHandler:
    """创建用于追踪 LLM 交互的 Langfuse CallbackHandler.

    返回：
        CallbackHandler: Configured Langfuse callback handler.
    """
    return CallbackHandler()


langfuse_callback_handler = get_langfuse_callback_handler()
