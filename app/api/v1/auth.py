"""API 鉴权和授权接口.

This module provides endpoints for user registration, login, session management,
and token verification.
"""

import uuid
from typing import List

from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    Request,
)
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)

from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import (
    bind_context,
    logger,
)
from app.models.user import User
from app.schemas.auth import (
    SessionResponse,
    TokenResponse,
    UserCreate,
    UserResponse,
)
from app.services.database import DatabaseService
from app.utils.auth import (
    create_access_token,
    verify_token,
)
from app.utils.sanitization import (
    sanitize_email,
    sanitize_string,
    validate_password_strength,
)

router = APIRouter()
# 这是 FastAPI 提供的认证依赖工具。它的作用是：从请求头里读取 Bearer Token。
security = HTTPBearer()
# 这是创建数据库服务对象。（作者自己创建）所以这里先创建一个 DatabaseService 实例，后面的函数复用它。 负责操作数据库里的用户和 session。
db_service = DatabaseService()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> User:
    """从 token 中获取当前用户.

    参数：
        credentials: 包含 JWT token 的 HTTP 鉴权凭证。

    返回：
        User: 从 token 解析出的用户。

    抛出：
        HTTPException: token 无效或缺失时抛出。
    """
    try:
        # 清理 token 输入
        token = sanitize_string(credentials.credentials)

        user_id = verify_token(token)
        if user_id is None:
            logger.error("invalid_token", token_part=token[:10] + "...")
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 校验用户是否存在
        user_id_int = int(user_id)
        user = await db_service.get_user(user_id_int)
        if user is None:
            logger.error("user_not_found", user_id=user_id_int)
            raise HTTPException(
                status_code=404,
                detail="User not found",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 将 user_id 绑定到日志上下文，供本次请求后续日志使用
        bind_context(user_id=user_id_int)

        return user
    except ValueError as ve:
        logger.exception("token_validation_failed", error=str(ve))
        raise HTTPException(
            status_code=422,
            detail="Invalid token format",
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.post("/register", response_model=UserResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["register"][0])
async def register_user(request: Request, user_data: UserCreate):
    """注册新用户.

    参数：
        request: FastAPI 请求对象，用于限流。
        user_data: 用户注册数据。

    返回：
        UserResponse: 创建后的用户信息。
    """
    try:
        # 清理邮箱输入
        sanitized_email = sanitize_email(user_data.email)

        # 提取并校验密码
        password = user_data.password.get_secret_value()
        validate_password_strength(password)

        # 检查用户是否已存在
        if await db_service.get_user_by_email(sanitized_email):
            raise HTTPException(status_code=400, detail="Email already registered")

        # 清理可选用户名
        sanitized_username = sanitize_string(user_data.username) if user_data.username else None

        # 创建用户
        user = await db_service.create_user(
            email=sanitized_email,
            password=User.hash_password(password),
            username=sanitized_username,
        )

        # 创建访问 token
        token = create_access_token(str(user.id))

        return UserResponse(id=user.id, email=user.email, username=user.username, token=token)
    except ValueError as ve:
        logger.exception("user_registration_validation_failed", error=str(ve))
        raise HTTPException(status_code=422, detail=str(ve))


@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["login"][0])
async def login(
    request: Request, email: str = Form(...), password: str = Form(...), grant_type: str = Form(default="password")
):
    """用户登录.

    参数：
        request: FastAPI 请求对象，用于限流。
        email: 用户邮箱。
        password: 用户密码。
        grant_type: 必须为 "password"。

    返回：
        TokenResponse: 访问 token 信息。

    抛出：
        HTTPException: 凭证无效时抛出。
    """
    try:
        # 清理输入
        email = sanitize_string(email)
        password = sanitize_string(password)
        grant_type = sanitize_string(grant_type)

        # 校验授权类型
        if grant_type != "password":
            raise HTTPException(
                status_code=400,
                detail="Unsupported grant type. Must be 'password'",
            )

        user = await db_service.get_user_by_email(email)
        if not user or not user.verify_password(password):
            raise HTTPException(
                status_code=401,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = create_access_token(str(user.id))
        return TokenResponse(access_token=token.access_token, token_type="bearer", expires_at=token.expires_at)
    except ValueError as ve:
        logger.exception("login_validation_failed", error=str(ve))
        raise HTTPException(status_code=422, detail=str(ve))


@router.post("/session", response_model=SessionResponse)
async def create_session(user: User = Depends(get_current_user)):
    """为当前登录用户创建新的聊天会话.

    参数：
        user: 当前登录用户。

    返回：
        SessionResponse: 会话 ID 和会话名称。
    """
    try:
        # 生成唯一会话 ID
        session_id = str(uuid.uuid4())

        # 在数据库中创建会话，并复制用户名用于 LLM 个性化
        session = await db_service.create_session(session_id, user.id, username=user.username)

        logger.info(
            "session_created",
            session_id=session_id,
            user_id=user.id,
            name=session.name,
        )

        return SessionResponse(session_id=session_id, name=session.name)
    except ValueError as ve:
        logger.exception("session_creation_validation_failed", error=str(ve), user_id=user.id)
        raise HTTPException(status_code=422, detail=str(ve))


@router.patch("/session/{session_id}/name", response_model=SessionResponse)
async def update_session_name(session_id: str, name: str = Form(...), user: User = Depends(get_current_user)):
    """更新会话名称.

    参数：
        session_id: 要更新的会话 ID。
        name: 新会话名称。
        user: 当前登录用户。

    返回：
        SessionResponse: 更新后的会话信息。
    """
    try:
        # 清理输入
        sanitized_session_id = sanitize_string(session_id)
        sanitized_name = sanitize_string(name)
        # 校验会话属于当前登录用户
        if await db_service.get_user_session(sanitized_session_id, user.id) is None:
            raise HTTPException(status_code=403, detail="Cannot modify other sessions")

        # 更新会话名称
        session = await db_service.update_session_name(sanitized_session_id, sanitized_name)

        return SessionResponse(session_id=sanitized_session_id, name=session.name)
    except ValueError as ve:
        logger.exception("session_update_validation_failed", error=str(ve), session_id=session_id)
        raise HTTPException(status_code=422, detail=str(ve))


@router.delete("/session/{session_id}")
async def delete_session(session_id: str, user: User = Depends(get_current_user)):
    """删除当前登录用户的会话.

    参数：
        session_id: 要删除的会话 ID。
        user: 当前登录用户。

    返回：
        None
    """
    try:
        # 清理输入
        sanitized_session_id = sanitize_string(session_id)
        # 校验会话属于当前登录用户
        if await db_service.get_user_session(sanitized_session_id, user.id) is None:
            raise HTTPException(status_code=403, detail="Cannot delete other sessions")

        # 删除会话
        await db_service.delete_session(sanitized_session_id)

        logger.info("session_deleted", session_id=session_id, user_id=user.id)
    except ValueError as ve:
        logger.exception("session_deletion_validation_failed", error=str(ve), session_id=session_id)
        raise HTTPException(status_code=422, detail=str(ve))


@router.get("/sessions", response_model=List[SessionResponse])
async def get_user_sessions(user: User = Depends(get_current_user)):
    """获取当前登录用户的所有会话.

    参数：
        user: 当前登录用户。

    返回：
        List[SessionResponse]: 会话列表。
    """
    try:
        sessions = await db_service.get_user_sessions(user.id)
        return [
            SessionResponse(
                session_id=sanitize_string(session.id),
                name=sanitize_string(session.name),
            )
            for session in sessions
        ]
    except ValueError as ve:
        logger.exception("get_sessions_validation_failed", user_id=user.id, error=str(ve))
        raise HTTPException(status_code=422, detail=str(ve))
