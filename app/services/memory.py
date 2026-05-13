"""基于 mem0 和 pgvector 的长期记忆服务，带可选缓存层."""

from mem0 import AsyncMemory

from app.core.cache import (
    cache_key,
    cache_service,
)
from app.core.config import settings
from app.core.logging import logger

"""
   mem0 会在对话后使用 LLM 分析本轮消息，判断其中是否包含值得长期保存的用户事实、偏好或背景信息。
   如果有，它会把这些信息提炼成记忆，并根据已有记忆决定新增、更新、合并或忽略。
   随后通过 embedding 模型把记忆向量化，存入 PostgreSQL + pgvector。
   当用户下次提问时，系统会把当前问题向量化，在 pgvector 中按 user_id 检索语义相关的长期记忆，
   再把这些记忆作为额外上下文放进 prompt，让大模型回答时参考。


"""

class MemoryService:
    """使用 mem0 和 pgvector 管理长期记忆的服务."""

    def __init__(self):
        """初始化记忆服务."""
        self._memory: AsyncMemory | None = None

    async def _get_memory(self) -> AsyncMemory:
        if self._memory is None:
            api_key = settings.DASHSCOPE_API_KEY or settings.OPENAI_API_KEY
            openai_base_url = settings.DASHSCOPE_BASE_URL if settings.DASHSCOPE_API_KEY else None
            self._memory = await AsyncMemory.from_config(
                config_dict={
                    "vector_store": {
                        "provider": "pgvector",
                        "config": {
                            "embedding_model_dims": settings.LONG_TERM_MEMORY_EMBEDDING_DIMS,
                            "collection_name": settings.LONG_TERM_MEMORY_COLLECTION_NAME,
                            "dbname": settings.POSTGRES_DB,
                            "user": settings.POSTGRES_USER,
                            "password": settings.POSTGRES_PASSWORD,
                            "host": settings.POSTGRES_HOST,
                            "port": settings.POSTGRES_PORT,
                        },
                    },
                    "llm": {
                        "provider": "openai",
                        "config": {
                            "model": settings.LONG_TERM_MEMORY_MODEL,
                            "api_key": api_key,
                            "openai_base_url": openai_base_url,
                        },
                    },
                    "embedder": {
                        "provider": "openai",
                        "config": {
                            "model": settings.LONG_TERM_MEMORY_EMBEDDER_MODEL,
                            "api_key": api_key,
                            "openai_base_url": openai_base_url,
                            "embedding_dims": settings.LONG_TERM_MEMORY_EMBEDDING_DIMS,
                        },
                    },
                }
            )
        return self._memory

    async def initialize(self) -> None:
        """预热 mem0 AsyncMemory 实例和 pgvector 连接池.

        启动时调用一次，避免首次 search() 或 add() 承担 from_config 和 pgvector.list_cols() 的冷启动成本。
        """
        await self._get_memory()
        logger.info("长期记忆服务已初始化")

    async def search(self, user_id: str | None, query: str) -> str:
        """检索指定用户的相关长期记忆.

        先查缓存；未命中时查询 mem0，并缓存结果。

        返回格式化后的记忆字符串；失败或未提供 user_id 时返回空字符串，避免匿名请求共享同一记忆分区。
        """
        if user_id is None:
            # 匿名会话不使用长期记忆，避免跨用户数据污染
            return ""
        try:
            # 以 user_id + query 的哈希作为缓存键，避免向量数据库重复查询
            key = cache_key("memory", str(user_id), query)
            cached = await cache_service.get(key)
            if cached is not None:
                logger.debug("长期记忆命中缓存", user_id=user_id)
                return cached

            logger.info("开始检索长期记忆", user_id=user_id)
            memory = await self._get_memory()
            results = await memory.search(user_id=str(user_id), query=query)
            result = "\n".join([f"* {r['memory']}" for r in results["results"]])
            result_count = len(results["results"])
            logger.info("长期记忆检索完成", user_id=user_id, memory_count=result_count)

            # 只缓存非空结果；空结果不缓存，下次仍会查询以防有新记忆写入
            if result:
                await cache_service.set(key, result)

            return result
        except Exception as e:
            # 记忆搜索失败不应中断对话，降级返回空字符串
            logger.error("长期记忆检索失败", error=str(e), user_id=user_id)
            return ""

    async def add(self, user_id: str | None, messages: list[dict], metadata: dict | None = None) -> None:
        """为指定用户添加长期记忆.

        当 user_id 为 None 时不执行操作，原因同 search。
        """
        if user_id is None:
            return
        try:
            logger.info("开始更新长期记忆", user_id=user_id)
            memory = await self._get_memory()
            await memory.add(messages, user_id=str(user_id), metadata=metadata)
            logger.info("长期记忆更新成功", user_id=user_id)
        except Exception as e:
            logger.exception("长期记忆更新失败", user_id=user_id, error=str(e))


memory_service = MemoryService()
