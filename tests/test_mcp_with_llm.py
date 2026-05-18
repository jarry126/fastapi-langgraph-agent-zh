"""测试 LLM 通过 MCP 工具自动调用高德地图.

流程：
    1. 从高德 MCP Server 获取工具列表（使用 LangChain MCP 适配器）
    2. 将工具绑定给 LLM
    3. 向 LLM 提问，LLM 自动决定调用哪个工具
    4. 循环执行工具，直到 LLM 给出最终文字回答（支持多轮 ReAct）

运行：
    uv run pytest tests/test_mcp_with_llm.py -v -s -m slow
"""

import asyncio
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.core.config import settings
from app.core.langgraph.tools.amap_mcp import get_amap_mcp_servers
from app.core.langgraph.tools.mcp_client import get_langchain_mcp_tools

# Key 从环境变量读取（AMAP_API_KEY），在 .env 中配置，不要硬编码
AMAP_SERVERS = get_amap_mcp_servers()


async def run_llm_with_mcp_tools(question: str) -> str:
    """让 LLM 使用 MCP 工具回答问题.

    支持多轮工具调用：LLM 可能先查坐标，再用坐标查路线，直到给出最终文字回答为止。

    参数：
        question: 用户问题

    返回：
        LLM 最终回答
    """
    # 1. 获取 MCP 工具（LangChain 格式，使用 mcp_client 封装）
    tools = await get_langchain_mcp_tools(AMAP_SERVERS)
    tools_by_name = {tool.name: tool for tool in tools}

    # 2. 初始化 LLM，绑定工具
    llm = ChatOpenAI(
        model="qwen-plus",
        api_key=SecretStr(settings.DASHSCOPE_API_KEY),
        base_url=settings.DASHSCOPE_BASE_URL,
    ).bind_tools(tools)

    messages = [HumanMessage(content=question)]
    print(f"\n问题：{question}")

    # 3. 循环调用，直到 LLM 不再需要工具（给出最终文字回答）
    round_num = 0
    while True:
        round_num += 1
        response = await llm.ainvoke(messages)
        messages.append(response)

        # LLM 没有调用工具，说明已经给出最终回答
        if not isinstance(response, AIMessage) or not response.tool_calls:
            print(f"\n第 {round_num} 轮：LLM 给出最终回答")
            return str(response.content)

        # LLM 选择了工具，执行所有工具调用
        print(f"\n第 {round_num} 轮：LLM 选择工具 {[tc['name'] for tc in response.tool_calls]}")
        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            print(f"  调用：{tool_name}，参数：{tool_args}")

            tool_result = await tools_by_name[tool_name].ainvoke(tool_args)
            messages.append(ToolMessage(
                content=str(tool_result),
                tool_call_id=tool_call["id"],
            ))
            print(f"  结果：{str(tool_result)[:300]}")


skip_if_no_amap_key = pytest.mark.skipif(
    not AMAP_SERVERS,
    reason="AMAP_API_KEY 未配置，跳过高德 MCP 测试（在 .env 中设置 AMAP_API_KEY）",
)


class TestLLMWithMCPTools:
    """测试 LLM 通过 MCP 工具自动调用."""

    @pytest.mark.slow
    @skip_if_no_amap_key
    def test_query_weather(self) -> None:
        """LLM 应自动调用天气工具回答天气问题."""
        result = asyncio.run(run_llm_with_mcp_tools("北京今天天气怎么样？"))
        print(f"\n最终回答：{result}")
        assert result, "应有回答"

    @pytest.mark.slow
    @skip_if_no_amap_key
    def test_query_nearby(self) -> None:
        """LLM 应自动调用周边搜索工具."""
        result = asyncio.run(run_llm_with_mcp_tools("上海人民广场附近有什么药店？"))
        print(f"\n最终回答：{result}")
        assert result, "应有回答"

    @pytest.mark.slow
    @skip_if_no_amap_key
    def test_query_route(self) -> None:
        """LLM 应自动调用路径规划工具."""
        result = asyncio.run(run_llm_with_mcp_tools("从北京天安门开车到颐和园怎么走？"))
        print(f"\n最终回答：{result}")
        assert result, "应有回答"
