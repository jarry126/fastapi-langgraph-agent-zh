"""处理聊天交互的 Chatbot API 接口.

本模块提供普通聊天、流式聊天、消息历史查询和聊天历史清理接口。
"""

import json

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
)
from fastapi.responses import StreamingResponse

from app.api.v1.auth import get_current_user
from app.core.config import settings
from app.core.langgraph.graph import LangGraphAgent
from app.core.limiter import limiter
from app.core.logging import logger
from app.core.metrics import llm_stream_duration_seconds
from app.models.session import Session
from app.models.user import User
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    Message,
    StreamResponse,
)
from app.services.database import database_service
from app.services.session_naming import maybe_name_session

router = APIRouter()
agent = LangGraphAgent()
MAX_LOG_CONTENT_LENGTH = 500


async def get_owned_session(session_id: str, user: User) -> Session:
    """加载聊天会话，并校验它属于当前登录用户."""
    session = await database_service.get_user_session(session_id, user.id)
    if session is None:
        logger.warning("会话访问被拒绝", session_id=session_id, user_id=user.id)
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def get_latest_user_message(messages: list[Message]) -> str:
    """从聊天请求中返回最新的用户消息内容."""
    user_message = next((message.content for message in reversed(messages) if message.role == "user"), None)
    if user_message is None:
        raise HTTPException(status_code=422, detail="At least one user message is required")
    return user_message


def get_latest_assistant_message(messages: list[Message]) -> str:
    """从处理结果中返回最新的助手回复内容."""
    assistant_message = next((message.content for message in reversed(messages) if message.role == "assistant"), None)
    if assistant_message is None:
        raise HTTPException(status_code=500, detail="Assistant response was not generated")
    return assistant_message


def truncate_for_log(value: str, max_length: int = MAX_LOG_CONTENT_LENGTH) -> str:
    """截断日志中的长文本，避免请求内容把日志刷得过长."""
    if len(value) <= max_length:
        return value
    return f"{value[:max_length]}...<truncated:{len(value) - max_length}>"


def build_chat_request_log_payload(chat_request: ChatRequest) -> dict:
    """构建可安全写入日志的聊天请求入参."""
    return {
        "session_id": chat_request.session_id,
        "message_count": len(chat_request.messages),
        "messages": [
            {
                "role": message.role,
                "content": truncate_for_log(message.content),
                "content_length": len(message.content),
            }
            for message in chat_request.messages
        ],
    }


@router.post("/chat", response_model=ChatResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["chat"][0])  # limiter.limit就是装饰器，添加限流限制
async def chat(
    request: Request,
    chat_request: ChatRequest,
    user: User = Depends(get_current_user),
):
    """使用 LangGraph 处理聊天请求.

    参数：
        request: FastAPI 请求对象，用于限流。
        chat_request: 包含消息的聊天请求。
        user: 从登录 token 解析出的当前用户。

    返回：
        ChatResponse: 处理后的聊天响应。

    抛出：
        HTTPException: 处理请求出错时抛出。
    """
    try:
        session = await get_owned_session(chat_request.session_id, user)
        logger.info("收到聊天请求", session_id=session.id, user_id=user.id, message_count=len(chat_request.messages))
        logger.info("收到聊天请求入参", session_id=session.id, user_id=user.id, parameters=build_chat_request_log_payload(chat_request))

        if settings.SESSION_NAMING_ENABLED:
            maybe_name_session(session.id, session.name, chat_request.messages)

        result = await agent.get_response(
            chat_request.messages, session.id, user_id=str(session.user_id), username=session.username
        )
        await database_service.create_chat_message(
            session_id=session.id,
            user_id=user.id,
            question=get_latest_user_message(chat_request.messages),
            answer=get_latest_assistant_message(result),
            metadata={"source": "chat"},
        )

        logger.info("聊天请求处理完成", session_id=session.id, user_id=user.id)

        return ChatResponse(messages=result)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("chat_request_failed", session_id=chat_request.session_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/stream")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["chat_stream"][0])
async def chat_stream(
    request: Request,
    chat_request: ChatRequest,
    user: User = Depends(get_current_user),
):
    """使用 LangGraph 处理流式聊天请求.

    参数：
        request: FastAPI 请求对象，用于限流。
        chat_request: 包含消息的聊天请求。
        user: 从登录 token 解析出的当前用户。

    返回：
        StreamingResponse: 聊天补全的流式响应。

    抛出：
        HTTPException: 处理请求出错时抛出。
    """
    try:
        session = await get_owned_session(chat_request.session_id, user)
        logger.info("收到流式聊天请求", session_id=session.id, user_id=user.id, message_count=len(chat_request.messages))
        logger.info("收到流式聊天请求入参", session_id=session.id, user_id=user.id, parameters=build_chat_request_log_payload(chat_request))

        if settings.SESSION_NAMING_ENABLED:
            maybe_name_session(session.id, session.name, chat_request.messages)

        async def event_generator():
            """生成流式事件.

            产出：
                str: JSON 格式的 SSE 事件。

            抛出：
                Exception: 流式处理出错时抛出。
            """
            chunks: list[str] = []
            try:
                with llm_stream_duration_seconds.labels(model=agent.llm_service.get_llm().get_name()).time():
                    async for chunk in agent.get_stream_response(
                        chat_request.messages, session.id, user_id=str(session.user_id), username=session.username
                    ):
                        chunks.append(chunk)
                        response = StreamResponse(content=chunk, done=False)
                        yield f"data: {json.dumps(response.model_dump(mode='json'))}\n\n"

                await database_service.create_chat_message(
                    session_id=session.id,
                    user_id=user.id,
                    question=get_latest_user_message(chat_request.messages),
                    answer="".join(chunks),
                    metadata={"source": "chat_stream"},
                )

                logger.info("流式聊天请求处理完成", session_id=session.id, user_id=user.id)

                # 发送最终消息，表示流式响应完成
                final_response = StreamResponse(content="", done=True)
                yield f"data: {json.dumps(final_response.model_dump(mode='json'))}\n\n"

            except Exception as e:
                logger.exception(
                    "stream_chat_request_failed",
                    session_id=session.id,
                    error=str(e),
                )
                error_response = StreamResponse(content=str(e), done=True)
                yield f"data: {json.dumps(error_response.model_dump(mode='json'))}\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "stream_chat_request_failed",
            session_id=chat_request.session_id,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/messages", response_model=ChatResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["messages"][0])
async def get_session_messages(
    request: Request,
    session_id: str = Query(..., description="聊天会话 ID"),
    user: User = Depends(get_current_user),
):
    """获取指定会话的所有消息.

    参数：
        request: FastAPI 请求对象，用于限流。
        session_id: 要读取的聊天会话 ID。
        user: 从登录 token 解析出的当前用户。

    返回：
        ChatResponse: 会话中的全部消息。

    抛出：
        HTTPException: 获取消息出错时抛出。
    """
    try:
        session = await get_owned_session(session_id, user)
        chat_messages = await database_service.get_chat_messages(session.id, user.id)
        messages = [
            message
            for chat_message in chat_messages
            for message in [
                Message(role="user", content=chat_message.question),
                Message(role="assistant", content=chat_message.answer),
            ]
        ]
        return ChatResponse(messages=messages)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("get_messages_failed", session_id=session_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/messages")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["messages"][0])
async def clear_chat_history(
    request: Request,
    session_id: str = Query(..., description="聊天会话 ID"),
    user: User = Depends(get_current_user),
):
    """清空指定会话的所有消息.

    参数：
        request: FastAPI 请求对象，用于限流。
        session_id: 要清理的聊天会话 ID。
        user: 从登录 token 解析出的当前用户。

    返回：
        dict: 表示聊天历史已清空的消息。
    """
    try:
        session = await get_owned_session(session_id, user)
        await database_service.delete_chat_messages(session.id, user.id)
        await agent.clear_chat_history(session.id)
        return {"message": "Chat history cleared successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("clear_chat_history_failed", session_id=session_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
