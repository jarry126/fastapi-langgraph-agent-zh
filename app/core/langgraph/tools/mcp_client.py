"""MCP 远程服务客户端.

提供两种接入远程 MCP Server 的方式：

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
方式一：MCPClient（原生 MCP 协议，底层控制）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
使用 mcp 官方 SDK，直接通过 Streamable HTTP 协议连接 MCP Server。
返回原始 MCP Tool 对象，适合自定义工具执行逻辑。

适用场景：
  - 需要精细控制工具调用过程（超时、重试、日志）
  - 不依赖 LangChain，保持最小化依赖
  - 构建自定义 Agent，不走 LangChain 工具调用链

用法：
    client = MCPClient("https://mcp.amap.com/mcp?key=YOUR_KEY")
    tools = await client.list_tools()          # 返回 list[mcp.types.Tool]
    result = await client.call_tool("maps_weather", {"city": "北京"})

说明（MCP 协议强制要求每个 Server 必须实现）：
    session.initialize()   ← 握手，建立连接
    session.list_tools()   ← 查有哪些工具
    session.call_tool()    ← 调用工具

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
方式二：get_langchain_mcp_tools（LangChain 适配器）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
使用 langchain-mcp-adapters 将 MCP 工具转换为 LangChain BaseTool。
可直接绑定给 LLM（llm.bind_tools）或 LangGraph Agent 使用。

适用场景：
  - 配合 LangGraph ToolNode / bind_tools 使用
  - 让 LLM 自动决策调用哪个工具（ReAct 模式）
  - 需要同时连接多个 MCP Server，统一管理工具列表

用法：
    tools = await get_langchain_mcp_tools({"amap": {"url": URL, "transport": "streamable_http"}})
    llm_with_tools = llm.bind_tools(tools)    # 绑定给 LLM

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
本质说明：
  两种方式底层都走 MCP 协议（list_tools / call_tool），区别在于：
  - 方式一：你手动管理「获取工具 → 调用工具」的完整流程
  - 方式二：LangChain 帮你把工具包装成 BaseTool，LLM 自动决定调用
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import Tool

from app.core.logging import logger


# ============================================================
# 方式一：原生 MCP 客户端（底层，不依赖 LangChain）
# ============================================================

class MCPClient:
    """封装 MCP 远程服务连接，支持 Streamable HTTP 协议.

    直接使用 MCP 官方 SDK，返回原始工具对象和字符串结果。
    适合需要精细控制调用过程，或不使用 LangChain 的场景。
    """

    def __init__(self, url: str) -> None:
        """初始化 MCP 客户端.

        参数：
            url: MCP Server 地址，例如 https://mcp.amap.com/mcp?key=YOUR_KEY
        """
        self.url = url

    async def list_tools(self) -> list[Tool]:
        """获取远程 MCP Server 暴露的所有工具.

        返回：
            Tool 列表，每个 Tool 包含 name、description、inputSchema。
        """
        async with streamable_http_client(url=self.url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                logger.info("mcp_tools_listed", url=self.url, tool_count=len(result.tools))
                return result.tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """调用远程 MCP Server 上的指定工具.

        参数：
            tool_name: 工具名称，需与 list_tools() 返回的 name 一致。
            arguments: 工具所需参数字典。

        返回：
            工具执行结果字符串。
        """
        async with streamable_http_client(url=self.url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                logger.info("mcp_tool_called", tool_name=tool_name, url=self.url)

                # 提取文本内容（MCP 返回的是 content 列表，每项可能是 text/image/resource）
                contents = [c.text for c in result.content if hasattr(c, "text")]
                return "\n".join(contents)


# ============================================================
# 方式二：LangChain MCP 适配器（推荐与 LangGraph Agent 配合使用）
# ============================================================

async def get_langchain_mcp_tools(
    servers: dict[str, dict[str, str]] | None = None,
) -> list[Any]:
    """从一个或多个 MCP Server 获取工具，转换为 LangChain BaseTool 格式.

    转换后的工具可直接用于：
      - llm.bind_tools(tools)         绑定给 LLM，让其自动决策调用
      - LangGraph ToolNode(tools)      挂入 LangGraph 图节点

    参数：
        servers: MCP Server 配置字典，格式为：
            {
                "server_name": {
                    "url": "https://...",
                    "transport": "streamable_http",  # 或 "sse"
                }
            }
            为 None 时使用内置的高德地图配置（需设置 AMAP_API_KEY 环境变量）。

    返回：
        LangChain BaseTool 列表，可直接绑定给 LLM 或 LangGraph Agent。

    示例——连接单个 Server：
        tools = await get_langchain_mcp_tools({
            "amap": {
                "url": "https://mcp.amap.com/mcp?key=YOUR_KEY",
                "transport": "streamable_http",
            }
        })
        llm_with_tools = llm.bind_tools(tools)

    示例——同时连接多个 Server：
        tools = await get_langchain_mcp_tools({
            "amap": {"url": "https://mcp.amap.com/mcp?key=KEY", "transport": "streamable_http"},
            "weather": {"url": "https://mcp.weather.com/mcp", "transport": "streamable_http"},
        })
    """
    # 延迟导入：langchain-mcp-adapters 是可选依赖，不安装时不影响其他功能
    from langchain_mcp_adapters.client import MultiServerMCPClient  # noqa: PLC0415

    client = MultiServerMCPClient(servers or {})
    tools = await client.get_tools()
    logger.info(
        "langchain_mcp_tools_loaded",
        server_count=len(servers or {}),
        tool_count=len(tools),
    )
    return tools
