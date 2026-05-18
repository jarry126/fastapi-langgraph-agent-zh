"""LangGraph 智能体/工作流以及与 LLM 交互的实现."""

import asyncio
from typing import (
    AsyncGenerator,
    Optional,
    cast,
)
from urllib.parse import quote_plus

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.tools.base import BaseTool
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    ToolMessage,
    convert_to_openai_messages,
)
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.errors import GraphInterrupt
from langgraph.graph import (
    END,
    StateGraph,
)
from langchain_core.runnables.config import RunnableConfig
from langgraph.graph.state import (
    Command,
    CompiledStateGraph,
)
from langgraph.types import (
    RetryPolicy,
    StateSnapshot,
)
from psycopg import (
    AsyncConnection,
    sql,
)
from psycopg.rows import (
    DictRow,
    dict_row,
)
from psycopg_pool import AsyncConnectionPool

from app.core.config import (
    Environment,
    settings,
)
from app.core.langgraph.tools import static_tools, load_all_tools
from app.core.logging import logger
from app.core.metrics import llm_inference_duration_seconds
from app.core.observability import langfuse_callback_handler
from app.core.prompts import load_system_prompt
from app.schemas import (
    GraphState,
    Message,
)
from app.services.llm import llm_service
from app.services.memory import memory_service
from app.utils import (
    dump_messages,
    extract_text_content,
    prepare_messages,
    process_llm_response,
)

PostgresConnPool = AsyncConnectionPool[AsyncConnection[DictRow]]


class LangGraphAgent:
    """管理 LangGraph 智能体/工作流以及与 LLM 的交互.

    该类负责创建和管理 LangGraph 工作流，包括 LLM 交互、数据库连接和响应处理。
    """

    def __init__(self):
        """使用必要组件初始化 LangGraph 智能体.

        注意：工具绑定（含 MCP 工具）在 create_graph() 中异步完成。
        __init__ 阶段先用静态工具占位，确保同步初始化不阻塞。
        """
        self.llm_service = llm_service
        # 先绑定静态工具（同步），MCP 工具在 create_graph() 异步加载后重新绑定
        self.llm_service.bind_tools(static_tools)
        self.tools_by_name: dict[str, BaseTool] = {tool.name: tool for tool in static_tools}
        self._connection_pool: Optional[PostgresConnPool] = None
        self._graph: Optional[CompiledStateGraph] = None
        logger.info(
            "langgraph_agent_initialized",
            model=settings.DEFAULT_LLM_MODEL,
            environment=settings.ENVIRONMENT.value,
        )

    async def _get_connection_pool(self) -> Optional[PostgresConnPool]:
        """根据当前环境配置获取 PostgreSQL 连接池.

        返回：
            AsyncConnectionPool；生产环境连接池初始化失败时返回 None，应用会以降级模式继续运行。
        """
        if self._connection_pool is None:
            try:
                max_size = settings.POSTGRES_POOL_SIZE

                # 用 quote_plus 对用户名和密码做 URL 编码，防止特殊字符（如 @、:）导致连接串解析失败
                connection_url = (
                    "postgresql://"
                    f"{quote_plus(settings.POSTGRES_USER)}:{quote_plus(settings.POSTGRES_PASSWORD)}"
                    f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
                )

                self._connection_pool = AsyncConnectionPool(
                    connection_url,
                    open=False,
                    max_size=max_size,
                    kwargs={
                        "autocommit": True,
                        "connect_timeout": 5,
                        # prepare_threshold=None 禁用服务端 prepared statement 缓存，
                        # 避免在连接池复用时出现 "prepared statement already exists" 错误
                        "prepare_threshold": None,
                        "row_factory": dict_row,
                    },
                )
                await self._connection_pool.open()
                logger.info("connection_pool_created", max_size=max_size, environment=settings.ENVIRONMENT.value)
            except Exception as e:
                logger.error("connection_pool_creation_failed", error=str(e), environment=settings.ENVIRONMENT.value)
                # 生产环境降级处理：DB 不可用时允许应用继续启动，聊天功能会失效但服务不崩溃
                if settings.ENVIRONMENT == Environment.PRODUCTION:
                    logger.warning("continuing_without_connection_pool", environment=settings.ENVIRONMENT.value)
                    return None
                raise e
        return self._connection_pool

    async def _chat(self, state: GraphState, config: RunnableConfig) -> Command:
        """处理聊天状态并生成回复.

        参数：
            state (GraphState): 当前对话状态。
            config (RunnableConfig): 本次调用的 runnable 配置。

        返回：
            Command: 包含更新后状态和下一个执行节点的命令对象。
        """
        # 获取当前 LLM 实例用于指标统计
        current_llm = self.llm_service.get_llm()
        model_name = (
            current_llm.model_name
            if current_llm and hasattr(current_llm, "model_name")
            else settings.DEFAULT_LLM_MODEL
        )

        username = config.get("metadata", {}).get("username")
        thread_id = config.get("configurable", {}).get("thread_id")
        SYSTEM_PROMPT = load_system_prompt(username=username, long_term_memory=state.long_term_memory)

        # 使用系统提示词准备消息
        messages = prepare_messages(state.messages, SYSTEM_PROMPT)

        try:
            # 使用带自动重试和循环 fallback 的 LLM 服务
            with llm_inference_duration_seconds.labels(model=model_name).time():
                response_message = await self.llm_service.call(dump_messages(messages))

            # 处理响应，兼容结构化内容块
            response_message = process_llm_response(response_message)

            logger.info("大模型回答已生成", session_id=thread_id, model=model_name)

            # 根据响应是否包含工具调用决定下一个节点：
            # 有工具调用 → tool_call 节点执行工具 → 再回到 chat
            # 无工具调用 → 直接结束
            if isinstance(response_message, AIMessage) and response_message.tool_calls:
                goto = "tool_call"
            else:
                goto = END

            return Command(update={"messages": [response_message]}, goto=goto)
        except Exception as e:
            logger.error(
                "llm_call_failed_all_models",
                session_id=thread_id,
                error=str(e),
                environment=settings.ENVIRONMENT.value,
            )
            raise Exception(f"failed to get llm response after trying all models: {str(e)}")

    # 定义工具节点
    async def _tool_call(self, state: GraphState) -> Command:
        """处理最后一条消息中的工具调用.

        参数：
            state: 当前智能体状态，包含消息和工具调用。

        返回：
            Command: 包含更新后消息，并路由回 chat 节点的命令对象。
        """
        tool_calls = state.messages[-1].tool_calls

        async def _execute_tool(tool_call: dict) -> ToolMessage:
            tool_result = await self.tools_by_name[tool_call["name"]].ainvoke(tool_call["args"])
            return ToolMessage(
                content=tool_result,
                name=tool_call["name"],
                tool_call_id=tool_call["id"],
            )

        # 单个工具调用直接 await，多个工具调用并发执行以节省等待时间
        if len(tool_calls) == 1:
            outputs = [await _execute_tool(tool_calls[0])]
        else:
            outputs = list(await asyncio.gather(*[_execute_tool(tc) for tc in tool_calls]))

        return Command(update={"messages": outputs}, goto="chat")

    async def create_graph(self) -> Optional[CompiledStateGraph]:
        """创建并配置 LangGraph 工作流.

        返回：
            Optional[CompiledStateGraph]: 配置完成的 LangGraph 实例；初始化失败时为 None。
        """
        if self._graph is None:
            try:
                # 异步加载全部工具（静态工具 + MCP 工具），然后重新绑定给 LLM
                # MCP 加载失败时 load_all_tools() 会自动降级，这里无需额外处理
                all_tools = await load_all_tools()
                self.llm_service.bind_tools(all_tools)
                self.tools_by_name = {tool.name: tool for tool in all_tools}
                logger.info(
                    "agent_tools_bound",
                    tool_names=list(self.tools_by_name.keys()),
                    total=len(all_tools),
                )

                graph_builder = StateGraph(GraphState)
                graph_builder.add_node("chat", self._chat, destinations=("tool_call", END))
                graph_builder.add_node(
                    "tool_call",
                    self._tool_call,
                    destinations=("chat",),
                    retry_policy=RetryPolicy(max_attempts=3),
                )
                graph_builder.set_entry_point("chat")
                graph_builder.set_finish_point("chat")

                # 获取连接池；生产环境数据库不可用时可能为 None
                connection_pool = await self._get_connection_pool()
                if connection_pool:
                    # LangGraph 的 AsyncPostgresSaver 在处理同一个 session 时会加数据库锁,也就是说同一个session，同一时间发出多个请求，在代码层次还是串行执行。
                    checkpointer = AsyncPostgresSaver(connection_pool)
                    await checkpointer.setup()
                else:
                    # 生产环境必要时允许不带 checkpointer 继续运行
                    checkpointer = None
                    if settings.ENVIRONMENT != Environment.PRODUCTION:
                        raise Exception("Connection pool initialization failed")

                self._graph = graph_builder.compile(
                    checkpointer=checkpointer, name=f"{settings.PROJECT_NAME} Agent ({settings.ENVIRONMENT.value})"
                )

                logger.info(
                    "graph_created",
                    graph_name=f"{settings.PROJECT_NAME} Agent",
                    environment=settings.ENVIRONMENT.value,
                    has_checkpointer=checkpointer is not None,
                )
            except Exception as e:
                logger.error("graph_creation_failed", error=str(e), environment=settings.ENVIRONMENT.value)
                # 生产环境不希望因此导致应用崩溃
                if settings.ENVIRONMENT == Environment.PRODUCTION:
                    logger.warning("continuing_without_graph")
                    return None
                raise e

        return self._graph

    async def _get_graph(self) -> CompiledStateGraph:
        """返回已编译的图；首次访问时创建.

        抛出：
            RuntimeError: 当 ``create_graph()`` 在生产环境路径吞掉初始化失败并返回 ``None`` 时抛出；
                调用方可以依赖本方法返回值一定不是 ``None``。
        """
        if self._graph is None:
            self._graph = await self.create_graph()
        if self._graph is None:
            raise RuntimeError("graph initialization failed")
        return self._graph

    async def get_response(
        self,
        messages: list[Message],
        session_id: str,
        user_id: Optional[str] = None,
        username: Optional[str] = None,
    ) -> list[Message]:
        """从 LLM 获取回复.

        参数：
            messages (list[Message]): 要发送给 LLM 的消息。
            session_id (str): 当前对话的 session ID。
            user_id (Optional[str]): 当前对话的用户 ID。
            username (Optional[str]): 用户展示名称。

        返回：
            list[Message]: LLM 返回的响应消息。
        """
        graph = await self._get_graph()
        callbacks: list[BaseCallbackHandler] = [langfuse_callback_handler] if settings.LANGFUSE_TRACING_ENABLED else []
        config: RunnableConfig = {
            "configurable": {"thread_id": session_id},
            "callbacks": callbacks,
            "metadata": {
                "user_id": user_id,
                "username": username,
                "session_id": session_id,
                "environment": settings.ENVIRONMENT.value,
                "debug": settings.DEBUG,
            },
        }

        try:
            # 并发获取 graph 状态和长期记忆，避免串行等待节省 200-500ms
            state, relevant_memory = await asyncio.gather(
                graph.aget_state(config),
                memory_service.search(user_id, messages[-1].content),
            )

            if state.next:
                # state.next 非空说明上次执行被 interrupt（如 ask_human 工具），
                # 此次用用户输入作为 resume 值继续执行，而不是重新开始
                logger.info("继续执行被中断的图流程", session_id=session_id, next_nodes=state.next)
                response = await graph.ainvoke(
                    Command(resume=messages[-1].content),
                    config=config,
                )
            else:
                relevant_memory = relevant_memory or "No relevant memory found."
                response = await graph.ainvoke(
                    input={"messages": dump_messages(messages), "long_term_memory": relevant_memory},
                    config=config,
                )

            # ainvoke 返回后再检查一次状态：图在本次执行中可能又遇到了 interrupt
            state = await graph.aget_state(config)
            if state.next:
                interrupt_value = state.tasks[0].interrupts[0].value if state.tasks else "Waiting for input."
                logger.info("图流程已中断等待用户输入", session_id=session_id, interrupt_value=str(interrupt_value))
                return [Message(role="assistant", content=str(interrupt_value))]

            openai_msgs = cast(list[dict], convert_to_openai_messages(response["messages"]))
            # 记忆写入不阻塞响应返回，后台异步执行
            asyncio.create_task(memory_service.add(user_id, openai_msgs, config.get("metadata")))
            return self.__process_messages(response["messages"])
        except GraphInterrupt:
            state = await graph.aget_state(config)
            interrupt_value = state.tasks[0].interrupts[0].value if state.tasks else "Waiting for input."
            logger.info("图流程已中断等待用户输入", session_id=session_id, interrupt_value=str(interrupt_value))
            return [Message(role="assistant", content=str(interrupt_value))]
        except Exception as e:
            logger.exception("get_response_failed", error=str(e), session_id=session_id)
            raise

    async def get_stream_response(
        self,
        messages: list[Message],
        session_id: str,
        user_id: Optional[str] = None,
        username: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """从 LLM 获取流式回复.

        参数：
            messages (list[Message]): 要发送给 LLM 的消息。
            session_id (str): 当前对话的 session ID。
            user_id (Optional[str]): 当前对话的用户 ID。
            username (Optional[str]): 用户展示名称。

        产出：
            str: LLM 响应中的 token。
        """
        callbacks: list[BaseCallbackHandler] = [langfuse_callback_handler] if settings.LANGFUSE_TRACING_ENABLED else []
        config: RunnableConfig = {
            "configurable": {"thread_id": session_id},
            "callbacks": callbacks,
            "metadata": {
                "user_id": user_id,
                "username": username,
                "session_id": session_id,
                "environment": settings.ENVIRONMENT.value,
                "debug": settings.DEBUG,
            },
        }
        graph = await self._get_graph()

        try:
            # 并发检查状态和检索记忆，节省 200-500ms
            state, relevant_memory = await asyncio.gather(
                graph.aget_state(config),
                memory_service.search(user_id, messages[-1].content),
            )

            if state.next:
                logger.info("继续执行被中断的流式图流程", session_id=session_id, next_nodes=state.next)
                graph_input = Command(resume=messages[-1].content)
            else:
                relevant_memory = relevant_memory or "No relevant memory found."
                graph_input = {"messages": dump_messages(messages), "long_term_memory": relevant_memory}

            async for token, _ in graph.astream(
                graph_input,
                config,
                stream_mode="messages",
            ):
                # stream_mode="messages" 会同时产出工具消息等，只透传 AI 文本 token
                if not isinstance(token, (AIMessage, AIMessageChunk)):
                    continue

                text = extract_text_content(token.content)
                if text:
                    yield text

            # 流式结束后检查是否触发了 interrupt（如 ask_human），有则把 interrupt 值作为最后一条消息推送
            state = await graph.aget_state(config)
            if state.next:
                interrupt_value = state.tasks[0].interrupts[0].value if state.tasks else "Waiting for input."
                logger.info("流式图流程已中断等待用户输入", session_id=session_id, interrupt_value=str(interrupt_value))
                yield str(interrupt_value)
            elif state.values and "messages" in state.values:
                openai_msgs = cast(list[dict], convert_to_openai_messages(state.values["messages"]))
                # 记忆写入放后台，不阻塞流式响应的关闭
                asyncio.create_task(memory_service.add(user_id, openai_msgs, config.get("metadata")))
        except GraphInterrupt:
            state = await graph.aget_state(config)
            interrupt_value = state.tasks[0].interrupts[0].value if state.tasks else "Waiting for input."
            logger.info("流式图流程已中断等待用户输入", session_id=session_id, interrupt_value=str(interrupt_value))
            yield str(interrupt_value)
        except Exception as stream_error:
            logger.exception("stream_processing_failed", error=str(stream_error), session_id=session_id)
            raise stream_error

    async def get_chat_history(self, session_id: str) -> list[Message]:
        """获取指定 thread ID 的聊天历史.

        参数：
            session_id (str): 当前对话的 session ID。

        返回：
            list[Message]: 聊天历史。
        """
        graph = await self._get_graph()

        config: RunnableConfig = {"configurable": {"thread_id": session_id}}
        state: StateSnapshot = await graph.aget_state(config=config)
        return self.__process_messages(state.values["messages"]) if state.values else []

    def __process_messages(self, messages: list[BaseMessage]) -> list[Message]:
        openai_style_messages = convert_to_openai_messages(messages)
        # 只保留 assistant 和 user 消息
        return [
            Message(role=message["role"], content=str(message["content"]))
            for message in openai_style_messages
            if message["role"] in ["assistant", "user"] and message["content"]
        ]

    async def clear_chat_history(self, session_id: str) -> None:
        """清空指定 thread ID 的全部聊天历史.

        参数：
            session_id: 要清理聊天历史的 session ID。

        抛出：
            Exception: 清理聊天历史出错时抛出。
        """
        try:
            # 确保连接池已在当前事件循环初始化
            conn_pool = await self._get_connection_pool()
            if conn_pool is None:
                raise RuntimeError("connection pool unavailable; cannot clear chat history")

            # 将所有 DELETE 合并到一次 pipeline 往返中
            async with conn_pool.connection() as conn:
                # pipeline() 将多条 DELETE 合并为一次网络往返，减少清理多张表的延迟
                async with conn.pipeline():
                    for table in settings.CHECKPOINT_TABLES:
                        await conn.execute(
                            sql.SQL("DELETE FROM {} WHERE thread_id = %s").format(sql.Identifier(table)),
                            (session_id,),
                        )
                logger.info(
                    "checkpoint_tables_cleared_for_session",
                    tables=settings.CHECKPOINT_TABLES,
                    session_id=session_id,
                )

        except Exception as e:
            logger.error(
                "clear_chat_history_operation_failed",
                session_id=session_id,
                error=str(e),
            )
            raise
