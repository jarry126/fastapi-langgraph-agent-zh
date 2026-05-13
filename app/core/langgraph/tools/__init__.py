"""用于增强语言模型能力的 LangGraph 工具.

This package contains custom tools that can be used with LangGraph to extend
the capabilities of language models. Currently includes tools for web search
and other external integrations.
"""

from langchain_core.tools.base import BaseTool

from .ask_human import ask_human
from .duckduckgo_search import duckduckgo_search_tool

tools: list[BaseTool] = [duckduckgo_search_tool, ask_human]
