"""LangGraph 使用的 DuckDuckGo 搜索工具.

This module provides a DuckDuckGo search tool that can be used with LangGraph
to perform web searches. It returns up to 10 search results and handles errors
gracefully.
"""

from langchain_community.tools import DuckDuckGoSearchResults

duckduckgo_search_tool = DuckDuckGoSearchResults(num_results=10, handle_tool_error=True)
