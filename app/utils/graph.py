"""应用图工具函数."""

import tiktoken
from langchain_core.messages import BaseMessage
from langchain_core.messages import trim_messages as _trim_messages

from app.core.config import settings
from app.core.logging import logger
from app.schemas import Message

# 在模块级缓存 tiktoken encoding，线程安全且可复用
try:
    _TIKTOKEN_ENCODING = tiktoken.encoding_for_model(settings.DEFAULT_LLM_MODEL)
except KeyError:
    _TIKTOKEN_ENCODING = tiktoken.get_encoding("cl100k_base")


def _count_tokens_tiktoken(messages: list) -> int:
    """使用 tiktoken 在本地统计 token，无需调用 API."""
    num_tokens = 0
    for message in messages:
        # 每条消息都会有 role/name 的额外 token 开销
        num_tokens += 4
        if isinstance(message, dict):
            for _, value in message.items():
                if isinstance(value, str):
                    num_tokens += len(_TIKTOKEN_ENCODING.encode(value))
        elif isinstance(message, BaseMessage):
            content = message.content
            if isinstance(content, str):
                num_tokens += len(_TIKTOKEN_ENCODING.encode(content))
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, str):
                        num_tokens += len(_TIKTOKEN_ENCODING.encode(block))
                    elif isinstance(block, dict) and "text" in block:
                        num_tokens += len(_TIKTOKEN_ENCODING.encode(block["text"]))
    num_tokens += 2  # every reply is primed with assistant
    return num_tokens


def dump_messages(messages: list[Message]) -> list[dict]:
    """将消息转换为字典列表.

    参数：
        messages: 要转换的消息列表。

    返回：
        list[dict]: 转换后的消息字典列表。
    """
    return [message.model_dump() for message in messages]


def extract_text_content(content: str | list) -> str:
    """从 LLM content 值中提取纯文本.

    Handles both the simple string format and the structured block list returned
    by GPT-5 / Responses API models:
        [{'type': 'reasoning', ...}, {'type': 'text', 'text': '...'}]

    参数：
        content: LangChain BaseMessage 中的原始内容。

    返回：
        Plain text string (empty string when nothing extractable is present).
    """
    if isinstance(content, str):
        return content

    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif block.get("type") == "reasoning":
                logger.debug(
                    "reasoning_block_received",
                    reasoning_id=block.get("id"),
                    has_summary=bool(block.get("summary")),
                )
    return "".join(parts)


def process_llm_response(response: BaseMessage) -> BaseMessage:
    """规范化原始 LLM 响应，确保 response.content 始终是纯字符串，不受供应商内容格式影响.

    参数：
        response: LLM 原始响应。

    返回：
        同一个 BaseMessage 实例，其中 content 会被设置为纯字符串。
    """
    if isinstance(response.content, list):
        response.content = extract_text_content(response.content)
        logger.debug(
            "processed_structured_content",
            content_block_count=len(response.content),
            extracted_length=len(response.content),
        )
    return response


def prepare_messages(messages: list[Message], system_prompt: str) -> list[Message]:
    """准备发送给 LLM 的消息.

    参数：
        messages (list[Message]): 要准备的消息列表。
        system_prompt: 要使用的系统提示词。

    返回：
        list[Message]: 准备后的消息列表。
    """
    try:
        trimmed_messages = _trim_messages(
            dump_messages(messages),
            strategy="last",
            token_counter=_count_tokens_tiktoken,
            max_tokens=settings.MAX_TOKENS,
            start_on="human",
            include_system=False,
            allow_partial=False,
        )
    except ValueError as e:
        # 处理无法识别的内容块，例如 GPT-5 reasoning block
        if "Unrecognized content block type" in str(e):
            logger.warning(
                "token_counting_failed_skipping_trim",
                error=str(e),
                message_count=len(messages),
            )
            # 跳过裁剪并返回所有消息
            trimmed_messages = messages
        else:
            raise

    return [Message(role="system", content=system_prompt)] + trimmed_messages
