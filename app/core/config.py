"""应用配置管理.

This module handles environment-specific configuration loading, parsing, and management
for the application. It includes environment detection, .env file loading, and
configuration value parsing.
"""

import os
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv


# 定义环境类型
class Environment(str, Enum):
    """应用环境类型.

    Defines the possible environments the application can run in:
    development, staging, production, and test.
    """

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TEST = "test"


# 判断当前环境
def get_environment() -> Environment:
    """获取当前运行环境.

    返回：
        Environment: 当前环境。
    """
    match os.getenv("APP_ENV", "development").lower():
        case "production" | "prod":
            return Environment.PRODUCTION
        case "staging" | "stage":
            return Environment.STAGING
        case "test":
            return Environment.TEST
        case _:
            return Environment.DEVELOPMENT


# 根据环境加载对应的 .env 文件
def load_env_file():
    """加载当前环境对应的 .env 文件."""
    env = get_environment()
    print(f"Loading environment: {env}")
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

    # 按优先级定义环境变量文件
    env_files = [
        os.path.join(base_dir, f".env.{env.value}.local"),
        os.path.join(base_dir, f".env.{env.value}"),
        os.path.join(base_dir, ".env.local"),
        os.path.join(base_dir, ".env"),
    ]

    # 加载第一个存在的环境变量文件
    for env_file in env_files:
        if os.path.isfile(env_file):
            load_dotenv(dotenv_path=env_file)
            print(f"Loaded environment from {env_file}")
            return env_file

    # 没有找到环境文件时回退到默认配置
    return None


ENV_FILE = load_env_file()


# 从环境变量解析列表值
def parse_list_from_env(env_key, default=None):
    """从环境变量解析逗号分隔列表."""
    value = os.getenv(env_key)
    if not value:
        return default or []

    # 移除可能存在的引号
    value = value.strip("\"'")
    # 处理单值场景
    if "," not in value:
        return [value]
    # 拆分逗号分隔值
    return [item.strip() for item in value.split(",") if item.strip()]


# 根据前缀从环境变量解析列表字典
def parse_dict_of_lists_from_env(prefix, default_dict=None):
    """根据公共前缀从环境变量解析列表字典."""
    result = default_dict or {}

    # 查找指定前缀的所有环境变量
    for key, value in os.environ.items():
        if key.startswith(prefix):
            endpoint = key[len(prefix) :].lower()  # Extract endpoint name
            # 解析该接口对应的值
            if value:
                value = value.strip("\"'")
                if "," in value:
                    result[endpoint] = [item.strip() for item in value.split(",") if item.strip()]
                else:
                    result[endpoint] = [value]

    return result


class Settings:
    """不依赖 pydantic 的应用配置对象."""

    def __init__(self):
        """从环境变量初始化应用配置.

        Loads and sets all configuration values from environment variables,
        with appropriate defaults for each setting. Also applies
        environment-specific overrides based on the current environment.
        """
        # 设置当前环境
        self.ENVIRONMENT = get_environment()

        # 应用配置
        self.PROJECT_NAME = os.getenv("PROJECT_NAME", "FastAPI LangGraph Template")
        self.VERSION = os.getenv("VERSION", "1.0.0")
        self.DESCRIPTION = os.getenv(
            "DESCRIPTION", "A production-ready FastAPI template with LangGraph and Langfuse integration"
        )
        self.API_V1_STR = os.getenv("API_V1_STR", "/api/v1")
        self.DEBUG = os.getenv("DEBUG", "false").lower() in ("true", "1", "t", "yes")

        # CORS 配置
        self.ALLOWED_ORIGINS = parse_list_from_env("ALLOWED_ORIGINS", ["*"])

        # Langfuse 配置
        self.LANGFUSE_TRACING_ENABLED = os.getenv("LANGFUSE_TRACING_ENABLED", "true").lower() in (
            "true",
            "1",
            "t",
            "yes",
        )
        self.LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
        self.LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
        self.LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

        # LangGraph 配置
        self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
        self.DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")

        # MCP 工具配置
        # 高德地图 MCP：https://lbs.amap.com/api/mcp-server/summary
        # 申请地址：https://lbs.amap.com/dev/key/app
        self.AMAP_API_KEY = os.getenv("AMAP_API_KEY", "")
        self.AMAP_MCP_ENABLED = os.getenv("AMAP_MCP_ENABLED", "true").lower() in ("true", "1", "yes")
        self.DASHSCOPE_BASE_URL = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.DEFAULT_LLM_MODEL = os.getenv("DEFAULT_LLM_MODEL", "gpt-5-mini")
        self.SESSION_NAMING_ENABLED = os.getenv("SESSION_NAMING_ENABLED", "true").lower() == "true"
        self.DEFAULT_LLM_TEMPERATURE = float(os.getenv("DEFAULT_LLM_TEMPERATURE", "0.2"))
        self.MAX_TOKENS = int(os.getenv("MAX_TOKENS", "2000"))
        self.MAX_LLM_CALL_RETRIES = int(os.getenv("MAX_LLM_CALL_RETRIES", "3"))
        self.LLM_TOTAL_TIMEOUT = int(os.getenv("LLM_TOTAL_TIMEOUT", "60"))
        # LangGraph 最大递归次数：chat → tool_call 算 2 步，10 轮工具调用 = 20 步，留一点余量设 25
        # 超出后 LangGraph 抛出 GraphRecursionError，防止 LLM 陷入无限循环
        self.LANGGRAPH_RECURSION_LIMIT = int(os.getenv("LANGGRAPH_RECURSION_LIMIT", "25"))

        # 长期记忆配置
        self.LONG_TERM_MEMORY_MODEL = os.getenv("LONG_TERM_MEMORY_MODEL", self.DEFAULT_LLM_MODEL)
        self.LONG_TERM_MEMORY_EMBEDDER_MODEL = os.getenv("LONG_TERM_MEMORY_EMBEDDER_MODEL", "text-embedding-v4")
        self.LONG_TERM_MEMORY_EMBEDDING_DIMS = int(os.getenv("LONG_TERM_MEMORY_EMBEDDING_DIMS", "1024"))
        self.LONG_TERM_MEMORY_COLLECTION_NAME = os.getenv("LONG_TERM_MEMORY_COLLECTION_NAME", "longterm_memory")
        # JWT 配置
        self.JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "")
        self.JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
        self.JWT_ACCESS_TOKEN_EXPIRE_DAYS = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_DAYS", "30"))

        # 日志配置
        self.LOG_DIR = Path(os.getenv("LOG_DIR", "logs"))
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
        self.LOG_FORMAT = os.getenv("LOG_FORMAT", "json")  # "text"/"console" or "json"

        # 性能分析配置（仅 DEBUG）
        self.PROFILING_DIR = Path(os.getenv("PROFILING_DIR", "/tmp/fastapi_profiles"))
        self.PROFILING_THRESHOLD_SECONDS = float(os.getenv("PROFILING_THRESHOLD_SECONDS", "2.0"))

        # PostgreSQL 配置
        self.POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
        self.POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
        self.POSTGRES_DB = os.getenv("POSTGRES_DB", "food_order_db")
        self.POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
        self.POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
        self.POSTGRES_POOL_SIZE = int(os.getenv("POSTGRES_POOL_SIZE", "20"))
        self.POSTGRES_MAX_OVERFLOW = int(os.getenv("POSTGRES_MAX_OVERFLOW", "10"))
        self.CHECKPOINT_TABLES = ["checkpoint_blobs", "checkpoint_writes", "checkpoints"]

        # Valkey/Redis 缓存配置（可选；配置 host 后启用）
        self.VALKEY_HOST = os.getenv("VALKEY_HOST", "")
        self.VALKEY_PORT = int(os.getenv("VALKEY_PORT", "6379"))
        self.VALKEY_DB = int(os.getenv("VALKEY_DB", "0"))
        self.VALKEY_PASSWORD = os.getenv("VALKEY_PASSWORD", "")
        self.VALKEY_MAX_CONNECTIONS = int(os.getenv("VALKEY_MAX_CONNECTIONS", "20"))
        self.CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "60"))

        # 限流配置
        self.RATE_LIMIT_DEFAULT = parse_list_from_env("RATE_LIMIT_DEFAULT", ["200 per day", "50 per hour"])

        # 默认接口限流配置
        default_endpoints = {
            "chat": ["30 per minute"],
            "chat_stream": ["20 per minute"],
            "messages": ["50 per minute"],
            "register": ["10 per hour"],
            "login": ["20 per minute"],
            "root": ["10 per minute"],
            "health": ["20 per minute"],
        }

        # 使用环境变量更新接口限流配置
        self.RATE_LIMIT_ENDPOINTS = default_endpoints.copy()
        for endpoint in default_endpoints:
            env_key = f"RATE_LIMIT_{endpoint.upper()}"
            value = parse_list_from_env(env_key)
            if value:
                self.RATE_LIMIT_ENDPOINTS[endpoint] = value

        # 评测配置
        self.EVALUATION_LLM = os.getenv("EVALUATION_LLM", "gpt-5")
        self.EVALUATION_BASE_URL = os.getenv("EVALUATION_BASE_URL", "https://api.openai.com/v1")
        self.EVALUATION_API_KEY = os.getenv("EVALUATION_API_KEY", self.OPENAI_API_KEY)
        self.EVALUATION_SLEEP_TIME = int(os.getenv("EVALUATION_SLEEP_TIME", "10"))

        # 应用环境特定配置
        self.apply_environment_settings()

    def apply_environment_settings(self):
        """根据当前环境应用环境特定配置."""
        env_settings = {
            Environment.DEVELOPMENT: {
                "DEBUG": True,
                "LOG_LEVEL": "DEBUG",
                "LOG_FORMAT": "text",
                "RATE_LIMIT_DEFAULT": ["1000 per day", "200 per hour"],
            },
            Environment.STAGING: {
                "DEBUG": False,
                "LOG_LEVEL": "INFO",
                "RATE_LIMIT_DEFAULT": ["500 per day", "100 per hour"],
            },
            Environment.PRODUCTION: {
                "DEBUG": False,
                "LOG_LEVEL": "WARNING",
                "RATE_LIMIT_DEFAULT": ["200 per day", "50 per hour"],
            },
            Environment.TEST: {
                "DEBUG": True,
                "LOG_LEVEL": "DEBUG",
                "LOG_FORMAT": "text",
                "RATE_LIMIT_DEFAULT": ["1000 per day", "1000 per hour"],  # Relaxed for testing
            },
        }

        # 获取当前环境的配置
        current_env_settings = env_settings.get(self.ENVIRONMENT, {})

        # 如果环境变量未显式设置，则应用默认环境配置
        for key, value in current_env_settings.items():
            env_var_name = key.upper()
            # 仅在环境变量未显式设置时覆盖
            if env_var_name not in os.environ:
                setattr(self, key, value)


# 创建配置实例
settings = Settings()
