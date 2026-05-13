"""预初始化 LLM 实例的模型注册表."""

from typing import (
    Any,
    Dict,
    List,
)

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.core.config import (
    Environment,
    settings,
)
from app.core.logging import logger

_OPENAI_API_KEY = SecretStr(settings.OPENAI_API_KEY)
_DASHSCOPE_API_KEY = SecretStr(settings.DASHSCOPE_API_KEY)
_DASHSCOPE_BASE_URL = settings.DASHSCOPE_BASE_URL


class LLMRegistry:
    """可用 LLM 模型注册表，包含预初始化实例.

    This class maintains a list of LLM configurations and provides
    methods to retrieve them by name with optional argument overrides.
    """

    LLMS: List[Dict[str, Any]] = [
        {
            "name": "qwen-plus",
            "llm": ChatOpenAI(
                model="qwen-plus",
                api_key=_DASHSCOPE_API_KEY,
                base_url=_DASHSCOPE_BASE_URL,
                temperature=settings.DEFAULT_LLM_TEMPERATURE,
                max_completion_tokens=settings.MAX_TOKENS,
            ),
        },
        {
            "name": "gpt-5-mini",
            "llm": ChatOpenAI(
                model="gpt-5-mini",
                api_key=_OPENAI_API_KEY,
                max_completion_tokens=settings.MAX_TOKENS,
                reasoning={"effort": "low"},
            ),
        },
        {
            "name": "gpt-5.4",
            "llm": ChatOpenAI(
                model="gpt-5",
                api_key=_OPENAI_API_KEY,
                max_completion_tokens=settings.MAX_TOKENS,
                reasoning={"effort": "medium"},
            ),
        },
        {
            "name": "gpt-5.4-nano",
            "llm": ChatOpenAI(
                model="gpt-5.4-nano",
                api_key=_OPENAI_API_KEY,
                max_completion_tokens=settings.MAX_TOKENS,
                reasoning={"effort": "low"},
            ),
        },
        {
            "name": "gpt-5",
            "llm": ChatOpenAI(
                model="gpt-5",
                api_key=_OPENAI_API_KEY,
                max_completion_tokens=settings.MAX_TOKENS,
                top_p=0.95 if settings.ENVIRONMENT == Environment.PRODUCTION else 0.8,
                presence_penalty=0.1 if settings.ENVIRONMENT == Environment.PRODUCTION else 0.0,
                frequency_penalty=0.1 if settings.ENVIRONMENT == Environment.PRODUCTION else 0.0,
            ),
        },
    ]

    @classmethod
    def get(cls, model_name: str, **kwargs) -> BaseChatModel:
        """根据名称获取 LLM，并可覆盖部分参数.

        传入 kwargs 时会创建一个新的 ChatOpenAI 实例并应用这些覆盖参数，
        不会修改注册表里的共享模型实例。

        参数：
            model_name: 要获取的模型名称。
            **kwargs: 覆盖默认模型配置的可选参数。

        返回：
            BaseChatModel 实例。

        抛出：
            ValueError: 当 model_name 不在 LLMS 中时抛出。
        """
        model_entry = next((e for e in cls.LLMS if e["name"] == model_name), None)

        if not model_entry:
            available = ", ".join(e["name"] for e in cls.LLMS)
            raise ValueError(f"model '{model_name}' not found in registry. available models: {available}")

        if kwargs:
            if "max_tokens" in kwargs:
                kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
            logger.debug("creating_llm_with_custom_args", model_name=model_name, custom_args=list(kwargs.keys()))
            if model_name.startswith("qwen-"):
                return ChatOpenAI(model=model_name, api_key=_DASHSCOPE_API_KEY, base_url=_DASHSCOPE_BASE_URL, **kwargs)
            return ChatOpenAI(model=model_name, api_key=_OPENAI_API_KEY, **kwargs)

        logger.debug("using_default_llm_instance", model_name=model_name)
        return model_entry["llm"]

    @classmethod
    def get_all_names(cls) -> List[str]:
        """按顺序返回所有已注册模型名称.

        返回：
            模型名称字符串列表。
        """
        return [e["name"] for e in cls.LLMS]

    @classmethod
    def get_model_at_index(cls, index: int) -> Dict[str, Any]:
        """返回指定索引的模型配置；索引越界时回到 0.

        参数：
            index: LLMS 中的索引。

        返回：
            模型配置字典。
        """
        if 0 <= index < len(cls.LLMS):
            return cls.LLMS[index]
        return cls.LLMS[0]
