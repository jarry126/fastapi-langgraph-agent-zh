# MCP 工具集成

## 概述

本项目通过 **MCP（Model Context Protocol）** 协议接入远程工具服务，目前已集成高德地图 MCP Server，为 LangGraph Agent 提供地理位置相关能力。

MCP 是 Anthropic 推出的开放标准，定义了 AI 应用与外部工具之间的通信接口。任何实现了 MCP 协议的服务，都可以用同一套方式接入，不需要为每个服务单独写适配代码。

---

## 架构设计

### 两种 MCP 接入方式

项目中同时保留了两种调用方式，对应不同使用场景：

```
app/core/langgraph/tools/mcp_client.py
├── MCPClient                      # 方式一：原生 MCP 协议（底层控制）
│   ├── list_tools() → list[Tool]
│   └── call_tool()  → str
│
└── get_langchain_mcp_tools()      # 方式二：LangChain 适配器（推荐与 Agent 配合）
    └── 返回 list[BaseTool]，可直接 bind_tools / ToolNode
```

| 场景 | 推荐方式 |
|------|---------|
| 接入 LangGraph Agent / ToolNode | `get_langchain_mcp_tools()` |
| LLM 自动决策调用工具（ReAct 模式） | `get_langchain_mcp_tools()` |
| 手动控制工具调用流程 | `MCPClient` |
| 查询 MCP Server 暴露的工具列表 | `MCPClient.list_tools()` |

### 与 LangGraph Agent 的集成方式

MCP 工具在 Agent 初始化时一次性加载，流程如下：

```
FastAPI 启动
  └── LangGraphAgent.__init__()         同步，用静态工具（DuckDuckGo、ask_human）占位
        └── create_graph()（首次请求）   异步
              ├── load_all_tools()       静态工具(2) + 高德 MCP 工具(15) = 17 个
              ├── llm_service.bind_tools() 绑定全部工具给 LLM
              └── graph_builder.compile() 图编译完成，工具可用
```

工具加载完成后，LLM 在对话中会自动决定是否调用工具，整个过程对上层 API 完全透明。

---

## 高德地图 MCP

### 传输协议：Streamable HTTP

高德 MCP Server 使用 **Streamable HTTP** 协议（MCP 2025 新标准），区别于旧版 SSE：

| 协议 | 方向 | 特点 |
|------|------|------|
| SSE | 单向（服务端推送） | 旧版，仅服务端主动推数据 |
| Streamable HTTP | 双向 | 新版，客户端发请求 + 服务端流式返回，一个连接搞定 |

本项目使用 `mcp` 官方 SDK 的 `streamable_http_client` 建立连接。

### 可用工具（15 个）

| 工具名 | 功能 |
|--------|------|
| `maps_geo` | 地理编码：地址 → 经纬度坐标 |
| `maps_regeocode` | 逆地理编码：坐标 → 地址信息 |
| `maps_weather` | 天气查询（城市当前天气） |
| `maps_around_search` | 周边搜索（POI，如附近药店、餐厅） |
| `maps_text_search` | 关键字搜索地点 |
| `maps_search_detail` | 地点详情查询 |
| `maps_distance` | 两点距离计算 |
| `maps_direction_driving` | 驾车路径规划 |
| `maps_direction_walking` | 步行路径规划 |
| `maps_direction_bicycling` | 骑行路径规划 |
| `maps_direction_transit_integrated` | 公交综合路径规划 |
| `maps_ip_location` | IP 定位 |
| `maps_schema_navi` | 导航跳转 Schema |
| `maps_schema_take_taxi` | 打车跳转 Schema |
| `maps_schema_personal_map` | 个人地图 Schema |

### 多轮工具调用（ReAct 模式）

LLM 可能需要多轮才能完成一个复杂任务，例如「从天安门开车到颐和园」：

```
第 1 轮：LLM 调用 maps_geo × 2（分别获取两个地点坐标）
第 2 轮：LLM 调用 maps_direction_driving（用坐标规划路线）
第 3 轮：LLM 没有 tool_calls，给出最终文字回答 → 结束
```

LangGraph 的 `chat → tool_call → chat` 循环结构天然支持这个模式，无需额外处理。

---

## 配置

### 环境变量

在 `.env`（本地）或 `.env.production`（生产）中添加：

```bash
# 高德地图 Web 服务 Key
# 申请地址：https://lbs.amap.com/dev/key/app
AMAP_API_KEY=your-amap-api-key

# 是否启用高德 MCP 工具（默认 true）
AMAP_MCP_ENABLED=true
```

> **注意**：`.env` 文件已在 `.gitignore` 中，Key 不会提交到代码仓库。
> 向团队共享配置时，参考 `.env.example` 中的占位符格式。

### Key 申请步骤

1. 登录[高德开放平台](https://lbs.amap.com/dev/key/app)
2. 创建应用，服务类型选择 **Web 服务**
3. 复制生成的 Key，填入 `AMAP_API_KEY`

### 降级机制

Key 未配置或网络不通时，Agent 自动降级，**不影响服务启动**：

| 情况 | 结果 |
|------|------|
| `AMAP_API_KEY` 为空 | 跳过高德工具，仅使用 DuckDuckGo + ask_human |
| `AMAP_MCP_ENABLED=false` | 同上 |
| 高德网络连接失败 | 捕获异常后降级，打印 warning 日志 |

---

## 核心代码

### 原生 MCP 客户端

```python
# app/core/langgraph/tools/mcp_client.py
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

class MCPClient:
    async def list_tools(self) -> list[Tool]:
        async with streamable_http_client(url=self.url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()   # MCP 握手
                result = await session.list_tools()
                return result.tools

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        async with streamable_http_client(url=self.url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                contents = [c.text for c in result.content if hasattr(c, "text")]
                return "\n".join(contents)
```

> `(read, write, _)` 中的第三个值是 `get_session_id`，MCP SDK 新版本新增，用 `_` 忽略。

### LangChain 适配器

```python
# 获取工具（LangChain BaseTool 格式）
async def get_langchain_mcp_tools(servers: dict) -> list[BaseTool]:
    from langchain_mcp_adapters.client import MultiServerMCPClient
    client = MultiServerMCPClient(servers)
    return await client.get_tools()

# 用法：绑定给 LLM
tools = await get_langchain_mcp_tools({
    "amap": {
        "url": "https://mcp.amap.com/mcp?key=YOUR_KEY",
        "transport": "streamable_http",
    }
})
llm_with_tools = llm.bind_tools(tools)
```

### 工具加载入口

```python
# app/core/langgraph/tools/__init__.py
static_tools = [duckduckgo_search_tool, ask_human]   # 同步，始终可用

async def load_all_tools() -> list[BaseTool]:
    """静态工具 + MCP 工具，MCP 失败时自动降级."""
    try:
        mcp_tools = await get_langchain_mcp_tools(get_amap_mcp_servers())
        return static_tools + mcp_tools    # 共 17 个
    except Exception:
        return list(static_tools)          # 降级：仅 2 个静态工具
```

---

## 依赖

```toml
# pyproject.toml
mcp = ">=1.9.0"                    # MCP 官方 SDK（Streamable HTTP 支持）
langchain-mcp-adapters = ">=0.1.0" # MCP → LangChain BaseTool 转换
```

---

## 测试

```bash
# 测试原生 MCP 连接（获取工具列表）
uv run pytest tests/test_mcp_client.py -v -s -m slow

# 测试 LLM 通过 MCP 工具自动回答问题（天气、周边搜索、路径规划）
uv run pytest tests/test_mcp_with_llm.py -v -s -m slow

# 运行单个测试
uv run pytest tests/test_mcp_with_llm.py::TestLLMWithMCPTools::test_query_route -v -s -m slow
```

测试文件位置：

```
tests/
├── test_mcp_client.py      # MCPClient 原生接口测试
└── test_mcp_with_llm.py    # LLM + MCP 工具端到端测试
```

---

## 扩展：接入其他 MCP Server

高德只是第一个接入的 MCP Server。如需新增其他服务（如天气、数据库、企业内部系统），只需：

**1. 新建配置文件**

```python
# app/core/langgraph/tools/my_service_mcp.py
def get_my_service_mcp_servers() -> dict:
    if not settings.MY_SERVICE_API_KEY:
        return {}
    return {
        "my_service": {
            "url": f"https://mcp.myservice.com/mcp?key={settings.MY_SERVICE_API_KEY}",
            "transport": "streamable_http",
        }
    }
```

**2. 在 `load_all_tools()` 中合并**

```python
async def load_all_tools() -> list[BaseTool]:
    servers = {}
    servers.update(get_amap_mcp_servers())
    servers.update(get_my_service_mcp_servers())   # 新增这行
    mcp_tools = await get_langchain_mcp_tools(servers)
    return static_tools + mcp_tools
```

**3. 添加环境变量**

```bash
# .env
MY_SERVICE_API_KEY=your-key
```

其余代码无需改动，LLM 会自动发现并使用新工具。
