"""带重试、循环 fallback 和可选结构化输出的 LLM 服务."""

import asyncio
import logging
from typing import (
    Any,
    Callable,
    List,
    Optional,
    Type,
    TypeVar,
    Union,
    overload,
)

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import BaseMessage
from openai import (
    APIError,
    APITimeoutError,
    OpenAIError,
    RateLimitError,
)
from pydantic import BaseModel
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.core.logging import logger
from app.services.llm.registry import LLMRegistry

T = TypeVar("T", bound=BaseModel)


class LLMService:
    """管理 LLM 调用、重试和循环 fallback 的服务.

    服务内部有两条执行路径：

    - **默认路径**（不传 model_name / response_format / model_kwargs）：使用
      ``self._llm``，也就是已绑定工具的智能体模型。循环 fallback 会更新
      ``self._llm``，因此切换模型后工具绑定仍然保留。

    - **一次性路径**（传入任意覆盖参数）：为本次调用解析一个新的本地
      ``Runnable``，不会修改 ``self._llm``，因此不会影响并发中的默认路径调用。
    """

    def __init__(self):
        """使用配置的默认模型初始化 LLM 服务."""
        self._llm: Any = None  # BaseChatModel pre-bind_tools, Runnable after
        self._current_model_index: int = 0
        self._bound_tools: List = []

        all_names = LLMRegistry.get_all_names()
        try:
            self._current_model_index = all_names.index(settings.DEFAULT_LLM_MODEL)
            self._llm = LLMRegistry.get(settings.DEFAULT_LLM_MODEL)
            logger.info(
                "大模型服务已初始化",
                default_model=settings.DEFAULT_LLM_MODEL,
                model_index=self._current_model_index,
                total_models=len(all_names),
            )
        except Exception as e:
            self._current_model_index = 0
            self._llm = LLMRegistry.LLMS[0]["llm"]
            logger.warning(
                "default_model_not_found_using_first",
                requested=settings.DEFAULT_LLM_MODEL,
                using=all_names[0] if all_names else "none",
                error=str(e),
            )

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    # 两个 @overload 仅用于类型推断：让调用方在传入 response_format 时得到 T，
    # 不传时得到 BaseMessage，运行时只有下面的 async def call 实际执行
    @overload
    async def call(
        self,
        messages: LanguageModelInput,
        model_name: Optional[str] = ...,
        response_format: None = ...,
        **model_kwargs: Any,
    ) -> BaseMessage: ...

    @overload
    async def call(
        self,
        messages: LanguageModelInput,
        model_name: Optional[str] = ...,
        *,
        response_format: Type[T],
        **model_kwargs: Any,
    ) -> T: ...

    async def call(
        self,
        messages: LanguageModelInput,
        model_name: Optional[str] = None,
        response_format: Optional[Type[BaseModel]] = None,
        **model_kwargs: Any,
    ) -> Union[BaseMessage, BaseModel]:
        """调用 LLM，并支持重试和循环 fallback.

        参数：
            messages: 要发送的对话消息。
            model_name: 覆盖本次调用使用的模型；``None`` 表示使用当前默认模型。
            response_format: 结构化输出使用的 Pydantic schema。传入后会链式调用
                ``.with_structured_output(schema)``，并返回经过校验的 schema
                实例，而不是原始 ``BaseMessage``。
            **model_kwargs: 构造一次性模型实例时透传给 ``LLMRegistry.get`` 的额外参数，
                例如 ``temperature``、``max_tokens``、``reasoning``。

        返回：
            ``response_format`` 为 ``None`` 时返回 ``BaseMessage``，否则返回经过校验的
            ``response_format`` 实例。

        抛出：
            RuntimeError: 当所有模型重试后仍失败，或总超时时间耗尽时抛出。
        """
        try:
            return await asyncio.wait_for(
                self._call_with_fallback(messages, model_name, response_format, model_kwargs),
                timeout=settings.LLM_TOTAL_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.exception(
                "llm_total_timeout_exceeded",
                timeout_seconds=settings.LLM_TOTAL_TIMEOUT,
            )
            raise RuntimeError(f"llm call timed out after {settings.LLM_TOTAL_TIMEOUT}s total budget")

    def get_llm(self) -> Any:
        """返回当前已绑定工具的默认 LLM 实例.

        返回：
            当前 ``BaseChatModel`` 实例；尚未初始化时返回 ``None``。
        """
        return self._llm

    def bind_tools(self, tools: List) -> "LLMService":
        """将工具绑定到默认 LLM 实例.

        参数：
            tools: 要绑定的工具列表。

        返回：
            返回自身，方便链式调用。
        """
        if self._llm:
            self._bound_tools = tools
            self._llm = self._llm.bind_tools(tools)
            logger.debug("工具已绑定到大模型", tool_count=len(tools))
        return self

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(settings.MAX_LLM_CALL_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((RateLimitError, APITimeoutError, APIError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def _invoke_with_retry(self, llm: Any, messages: LanguageModelInput) -> Any:
        """调用 LLM runnable，并使用每个模型自己的自动重试逻辑.

        参数：
            llm: 任意 LangChain ``Runnable``，可以是普通模型或结构化输出链。
            messages: 要发送的消息。

        返回：
            runnable 的响应，可能是 ``BaseMessage`` 或 ``BaseModel`` 实例。

        抛出：
            OpenAIError: 所有重试耗尽后继续向外抛出。
        """
        try:
            logger.debug("开始调用大模型")
            response = await llm.ainvoke(messages)
            logger.debug("大模型调用成功")
            return response
        except (RateLimitError, APITimeoutError, APIError) as e:
            logger.warning("大模型调用失败，准备重试", error_type=type(e).__name__, error=str(e), exc_info=True)
            raise
        except OpenAIError as e:
            logger.error("大模型调用失败", error_type=type(e).__name__, error=str(e))
            raise

    def _switch_to_next_model(self) -> bool:
        """将默认模型切换到注册表中的下一个模型（循环）.

        会修改 ``self._llm`` 和 ``self._current_model_index``，确保默认智能体路径
        切换模型后仍保留工具绑定。

        返回：
            切换成功返回 ``True``，切换失败返回 ``False``。
        """
        try:
            next_index = (self._current_model_index + 1) % len(LLMRegistry.LLMS)
            next_entry = LLMRegistry.get_model_at_index(next_index)
            logger.warning(
                "正在切换到下一个大模型",
                from_index=self._current_model_index,
                to_index=next_index,
                to_model=next_entry["name"],
            )
            self._current_model_index = next_index
            self._llm = next_entry["llm"]
            if self._bound_tools:
                self._llm = self._llm.bind_tools(self._bound_tools)
            logger.info("大模型已切换", new_model=next_entry["name"], new_index=next_index)
            return True
        except Exception as e:
            logger.error("大模型切换失败", error=str(e))
            return False

    async def _call_with_fallback(
        self,
        messages: LanguageModelInput,
        model_name: Optional[str],
        response_format: Optional[Type[BaseModel]],
        model_kwargs: dict,
    ) -> Union[BaseMessage, BaseModel]:
        """构建不同调用路径的策略，并委托给共享 fallback 循环.

        一次性路径（设置了任意覆盖参数）：
            ``get_target`` 每次尝试都会构建新的注册表实例。
            ``advance`` 只递增本地索引，不会触碰 ``self._llm``。

        默认路径（没有覆盖参数）：
            ``get_target`` 返回已绑定工具的 ``self._llm``。
            ``advance`` 调用 ``_switch_to_next_model``，因此工具绑定会保留。
        """

        def _override_target(idx: int) -> Any:
            base = LLMRegistry.get(LLMRegistry.LLMS[idx]["name"], **model_kwargs)
            return base.with_structured_output(response_format) if response_format else base

        def _default_target(_: int) -> Any:
            return self._llm

        def _default_advance(_: int) -> Optional[int]:
            return self._current_model_index if self._switch_to_next_model() else None

        if model_name or response_format or model_kwargs:
            # 一次性调用路径：构造临时 LLM 实例，不修改 self._llm，
            # 保证并发的默认路径调用不受影响
            all_names = LLMRegistry.get_all_names()
            if model_name and model_name not in all_names:
                logger.error("requested_model_not_found", model_name=model_name)
                raise ValueError(
                    f"model '{model_name}' not found in registry. available models: {', '.join(all_names)}"
                )

            start = all_names.index(model_name) if model_name else self._current_model_index
            total = len(LLMRegistry.LLMS)
            get_target: Callable[[int], Any] = _override_target

            def _override_advance(idx: int) -> Optional[int]:
                return (idx + 1) % total

            advance: Callable[[int], Optional[int]] = _override_advance
        else:
            # 默认路径：使用已绑定工具的 self._llm，模型切换时工具绑定会随之迁移
            start = self._current_model_index
            get_target = _default_target
            advance = _default_advance

        return await self._fallback_loop(messages, start, get_target, advance)

    async def _fallback_loop(
        self,
        messages: LanguageModelInput,
        start: int,
        get_target: Callable[[int], Any],
        advance: Callable[[int], Optional[int]],
    ) -> Any:
        """共享 fallback 循环：依次尝试每个模型，直到成功.

        参数：
            messages: 要发送的消息。
            start: 开始尝试的注册表索引。
            get_target: 根据索引返回要调用的 ``Runnable``。
            advance: 返回下一个要尝试的索引；返回 ``None`` 表示停止。

        返回：
            第一个成功的响应。

        抛出：
            RuntimeError: 当所有模型都已尝试且失败时抛出。
        """
        total = len(LLMRegistry.LLMS)
        current = start
        models_tried = 0
        last_error: Optional[Exception] = None

        # 循环遍历所有模型：每个模型内部已有 tenacity 重试，全部耗尽后才切换到下一个
        for models_tried in range(1, total + 1):
            current_name = LLMRegistry.LLMS[current]["name"]
            try:
                return await self._invoke_with_retry(get_target(current), messages)
            except OpenAIError as e:
                last_error = e
                logger.error(
                    "当前大模型重试后仍失败",
                    model=current_name,
                    models_tried=models_tried,
                    total_models=total,
                    error=str(e),
                )
                if models_tried >= total:
                    logger.error(
                        "所有大模型均调用失败",
                        models_tried=models_tried,
                        starting_model=LLMRegistry.LLMS[start]["name"],
                    )
                    break
                next_idx = advance(current)
                if next_idx is None:
                    logger.error("failed_to_switch_to_next_model")
                    break
                current = next_idx

        raise RuntimeError(
            f"failed to get response from llm after trying {models_tried} models. last error: {str(last_error)}"
        )


llm_service = LLMService()
