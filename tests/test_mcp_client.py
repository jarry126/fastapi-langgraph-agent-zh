"""MCP 客户端测试.

运行方式：
    # 安装测试依赖
    uv sync --group test

    # 运行所有测试
    uv run pytest tests/test_mcp_client.py -v

    # 只运行快速测试（跳过需要真实网络的测试）
    uv run pytest tests/test_mcp_client.py -v -m "not slow"
"""

import asyncio

import pytest

from app.core.config import settings
from app.core.langgraph.tools.mcp_client import MCPClient

# Key 从环境变量读取，在 .env 中配置 AMAP_API_KEY，不要硬编码
AMAP_MCP_URL = f"https://mcp.amap.com/mcp?key={settings.AMAP_API_KEY}"

skip_if_no_amap_key = pytest.mark.skipif(
    not settings.AMAP_API_KEY,
    reason="AMAP_API_KEY 未配置，跳过高德 MCP 测试（在 .env 中设置 AMAP_API_KEY）",
)


class TestMCPClientListTools:
    """测试 list_tools：验证能否连接并获取工具列表."""

    @pytest.mark.slow
    @skip_if_no_amap_key
    def test_list_tools_returns_tools(self) -> None:
        """连接高德 MCP Server，应返回非空工具列表."""
        client = MCPClient(AMAP_MCP_URL)
        tools = asyncio.run(client.list_tools())

        assert len(tools) > 0, "工具列表不应为空"

    @pytest.mark.slow
    @skip_if_no_amap_key
    def test_list_tools_have_required_fields(self) -> None:
        """每个工具应包含 name 和 description 字段."""
        client = MCPClient(AMAP_MCP_URL)
        tools = asyncio.run(client.list_tools())

        for tool in tools:
            assert tool.name, f"工具缺少 name 字段: {tool}"
            assert tool.description, f"工具 {tool.name} 缺少 description 字段"

    @pytest.mark.slow
    @skip_if_no_amap_key
    def test_print_all_tools(self) -> None:
        """打印所有工具名和描述，方便了解 MCP Server 提供了什么能力."""
        client = MCPClient(AMAP_MCP_URL)
        tools = asyncio.run(client.list_tools())

        print(f"\n共 {len(tools)} 个工具：")
        for tool in tools:
            print(f"  - {tool.name}: {tool.description}")
            print(f"    参数: {tool.inputSchema}")


class TestMCPClientCallTool:
    """测试 call_tool：验证工具调用是否正常."""

    @pytest.mark.slow
    @skip_if_no_amap_key
    def test_call_tool_returns_string(self) -> None:
        """调用工具应返回字符串结果."""
        client = MCPClient(AMAP_MCP_URL)

        # 先获取工具列表，取第一个工具名
        tools = asyncio.run(client.list_tools())
        assert tools, "没有可用工具"

        first_tool = tools[0]
        print(f"\n测试工具: {first_tool.name}")

        # 注意：这里的参数需要根据实际工具调整
        # 先运行 test_print_all_tools 看工具参数格式
        result = asyncio.run(
            client.call_tool(
                tool_name=first_tool.name,
                arguments={},  # 根据 inputSchema 填写
            )
        )
        assert isinstance(result, str), "结果应为字符串"
        print(f"结果: {result[:200]}")  # 只打印前 200 字符
