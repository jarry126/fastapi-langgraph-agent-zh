"""LangGraph 人工确认工具.

This module provides a tool that pauses graph execution to ask the user
for confirmation before proceeding with a sensitive action.
"""

from langchain_core.tools import tool
from langgraph.types import interrupt


@tool
def ask_human(question: str) -> str:
    """暂停执行并向用户提问，等待确认后继续.

    Use this tool whenever you need clarification, confirmation, or additional
    input from the user before taking a significant action (e.g. deleting data,
    sending emails, making purchases, or any irreversible operation).

    参数：
        question: 要询问用户的问题。

    返回：
        str: 用户的回复。
    """
    user_response = interrupt(question)
    return str(user_response)
