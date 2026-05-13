"""应用输入清理工具."""

import html
import re
from typing import (
    Any,
    Dict,
    List,
)


def sanitize_string(value: str) -> str:
    """清理字符串，防止 XSS 和其他注入攻击.

    参数：
        value: 要清理的字符串。

    返回：
        str: 清理后的字符串。
    """
    # 如果不是字符串，则先转换为字符串
    if not isinstance(value, str):
        value = str(value)

    # HTML 转义，防止 XSS
    value = html.escape(value)

    # 移除可能被转义过的 script 标签
    value = re.sub(r"&lt;script.*?&gt;.*?&lt;/script&gt;", "", value, flags=re.DOTALL)

    # 移除空字节
    value = value.replace("\0", "")

    return value


def sanitize_email(email: str) -> str:
    """清理邮箱地址.

    参数：
        email: 要清理的邮箱地址。

    返回：
        str: 清理后的邮箱地址。
    """
    # 基础清理
    email = sanitize_string(email)

    # 确保邮箱格式正确（简单检查）
    if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email):
        raise ValueError("Invalid email format")

    return email.lower()


def sanitize_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """递归清理字典中的所有字符串值.

    参数：
        data: 要清理的字典。

    返回：
        Dict[str, Any]: 清理后的字典。
    """
    sanitized = {}
    for key, value in data.items():
        if isinstance(value, str):
            sanitized[key] = sanitize_string(value)
        elif isinstance(value, dict):
            sanitized[key] = sanitize_dict(value)
        elif isinstance(value, list):
            sanitized[key] = sanitize_list(value)
        else:
            sanitized[key] = value
    return sanitized


def sanitize_list(data: List[Any]) -> List[Any]:
    """递归清理列表中的所有字符串值.

    参数：
        data: 要清理的列表。

    返回：
        List[Any]: 清理后的列表。
    """
    sanitized = []
    for item in data:
        if isinstance(item, str):
            sanitized.append(sanitize_string(item))
        elif isinstance(item, dict):
            sanitized.append(sanitize_dict(item))
        elif isinstance(item, list):
            sanitized.append(sanitize_list(item))
        else:
            sanitized.append(item)
    return sanitized


def validate_password_strength(password: str) -> bool:
    """校验密码强度.

    参数：
        password: 要校验的密码。

    返回：
        bool: 密码是否足够强。

    抛出：
        ValueError: 密码强度不足时抛出，并说明原因。
    """
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long")

    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain at least one uppercase letter")

    if not re.search(r"[a-z]", password):
        raise ValueError("Password must contain at least one lowercase letter")

    if not re.search(r"[0-9]", password):
        raise ValueError("Password must contain at least one number")

    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        raise ValueError("Password must contain at least one special character")

    return True
