"""应用鉴权工具."""

import re
from datetime import (
    UTC,
    datetime,
    timedelta,
)
from typing import Optional

from jose import (
    JWTError,
    jwt,
)

from app.core.config import settings
from app.core.logging import logger
from app.schemas.auth import Token
from app.utils.sanitization import sanitize_string


def create_access_token(thread_id: str, expires_delta: Optional[timedelta] = None) -> Token:
    """创建新的访问 token.

    参数：
        thread_id: 会话线程唯一 ID。
        expires_delta: 可选过期时间间隔。

    返回：
        Token: 生成的访问 token。
    """
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(days=settings.JWT_ACCESS_TOKEN_EXPIRE_DAYS)

    to_encode = {
        "sub": thread_id,
        "exp": expire,
        "iat": datetime.now(UTC),
        "jti": sanitize_string(f"{thread_id}-{datetime.now(UTC).timestamp()}"),  # Add unique token identifier
    }

    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    logger.info("token_created", thread_id=thread_id, expires_at=expire.isoformat())

    return Token(access_token=encoded_jwt, expires_at=expire)


def verify_token(token: str) -> Optional[str]:
    """校验 JWT token 并返回其中的 subject.

    参数：
        token: 要校验的 JWT token。

    返回：
        Optional[str]: token 有效时返回 subject，否则返回 None。

    抛出：
        ValueError: token 格式无效时抛出。
    """
    if not token or not isinstance(token, str):
        logger.warning("token_invalid_format")
        raise ValueError("Token must be a non-empty string")

    # 解码前进行基础格式校验
    # JWT token 由 3 段 base64url 编码内容组成，并用点号分隔
    if not re.match(r"^[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+$", token):
        logger.warning("token_suspicious_format")
        raise ValueError("Token format is invalid - expected JWT format")

    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        thread_id: str | None = payload.get("sub")
        if thread_id is None:
            logger.warning("token_missing_thread_id")
            return None

        logger.info("token_verified", thread_id=thread_id)
        return thread_id

    except JWTError as e:
        logger.error("token_verification_failed", error=str(e))
        return None
