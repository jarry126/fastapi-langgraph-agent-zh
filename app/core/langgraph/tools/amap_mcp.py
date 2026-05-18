"""高德地图 MCP Server 配置.

高德地图通过 MCP 协议暴露了地图能力，包括：
  - 地理编码（地址 → 坐标）
  - 逆地理编码（坐标 → 地址）
  - 天气查询
  - 周边搜索（POI）
  - 驾车 / 步行 / 公交路径规划
  - ...共 15+ 个工具

申请 Key：https://lbs.amap.com/dev/key/app
MCP 文档：https://lbs.amap.com/api/mcp-server/summary

环境变量：
    AMAP_API_KEY      高德 Web 服务 API Key（必填，为空时自动禁用此工具集）
    AMAP_MCP_ENABLED  是否启用高德 MCP 工具（默认 true）
"""

from app.core.config import settings
from app.core.logging import logger


def get_amap_mcp_servers() -> dict[str, dict[str, str]]:
    """返回高德地图 MCP Server 配置.

    返回：
        MultiServerMCPClient 所需的 servers 配置字典。
        未配置 Key 或已禁用时返回空字典，外层调用无需特判。

    示例返回值：
        {
            "amap": {
                "url": "https://mcp.amap.com/mcp?key=xxx",
                "transport": "streamable_http",
            }
        }
    """
    if not settings.AMAP_MCP_ENABLED:
        logger.info("amap_mcp_disabled", reason="AMAP_MCP_ENABLED=false")
        return {}

    if not settings.AMAP_API_KEY:
        logger.warning("amap_mcp_skipped", reason="AMAP_API_KEY not configured")
        return {}

    return {
        "amap": {
            "url": f"https://mcp.amap.com/mcp?key={settings.AMAP_API_KEY}",
            "transport": "streamable_http",
        }
    }
