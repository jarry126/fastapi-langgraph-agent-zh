"""智能体 prompt 加载模块."""

import os
from datetime import datetime
from typing import Optional

from app.core.config import settings

_PROMPTS_DIR = os.path.dirname(__file__)

# 模块加载时读取模板一次，避免每次请求都进行文件 I/O
with open(os.path.join(_PROMPTS_DIR, "system.md"), "r") as _f:
    _SYSTEM_PROMPT_TEMPLATE = _f.read()

with open(os.path.join(_PROMPTS_DIR, "session_title.md"), "r") as _f:
    SESSION_TITLE_PROMPT = _f.read()


def load_system_prompt(username: Optional[str] = None, **kwargs):
    """从缓存模板加载系统 prompt."""
    user_context = f"# User\nYou are talking to {username}.\n" if username else ""
    return _SYSTEM_PROMPT_TEMPLATE.format(
        agent_name=settings.PROJECT_NAME + " Agent",
        current_date_and_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        user_context=user_context,
        **kwargs,
    )
