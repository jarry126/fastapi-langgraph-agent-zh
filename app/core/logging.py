"""应用日志配置与初始化.

本模块使用 structlog 提供结构化日志配置，所有环境统一使用 text 格式输出。
本地开发时终端自动着色；Docker/K8s 容器中 isatty() 返回 False，颜色自动关闭，
输出纯文本，运维可按固定格式正则拆分字段。
"""

import json
import logging
import os
import sys
from contextvars import ContextVar
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    MutableMapping,
    Optional,
    override,
)

import structlog
from asgi_correlation_id import correlation_id

from app.core.config import settings

# 确保日志目录存在
settings.LOG_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# ANSI 颜色常量
# PyCharm 控制台通过 PYCHARM_HOSTED 环境变量识别，isatty() 在其中可能返回 False
# ---------------------------------------------------------------------------
_USE_COLORS = sys.stdout.isatty() or bool(os.environ.get("PYCHARM_HOSTED"))

_RESET    = "\033[0m"
_BOLD     = "\033[1m"
_DIM      = "\033[2m"
_GRAY     = "\033[90m"
_CYAN     = "\033[96m"
_GREEN    = "\033[32m"
_YELLOW   = "\033[33m"
_RED      = "\033[31m"
_BOLD_RED = "\033[1;31m"

_LEVEL_COLOR: Dict[str, str] = {
    "DEBUG":    _CYAN,
    "INFO":     _GREEN,
    "WARNING":  _YELLOW,
    "ERROR":    _RED,
    "CRITICAL": _BOLD_RED,
}


def _c(text: str, *codes: str) -> str:
    """终端支持颜色时应用 ANSI 代码，否则原样返回."""
    if not _USE_COLORS or not codes:
        return str(text)
    return "".join(codes) + str(text) + _RESET

"""
    request_id 是“自动字段”，但不是每一条日志一定都有。
    它只有在当前代码处于一次 HTTP 请求链路里时才会有。
"""

READABLE_LOG_FIELD_ORDER = (
    "method",
    "path",
    "status_code",
    "duration_ms",
    "user_id",
    "session_id",
    "chat_message_id",
    "message_count",
    "model",
    "error_type",
    "error",
)

NOISY_THIRD_PARTY_LOGGERS = (
    "httpcore",
    "httpx",
    "openai",
    "urllib3",
    "hpack",
)

# 存储请求级上下文数据的 ContextVar
_request_context: ContextVar[Optional[Dict[str, Any]]] = ContextVar("request_context", default=None)


def bind_context(**kwargs: Any) -> None:
    """将上下文字段绑定到当前请求.

    参数：
        **kwargs: Key-value pairs to bind to the logging context
    """
    current = _request_context.get() or {}
    _request_context.set({**current, **kwargs})


def clear_context() -> None:
    """清理当前请求的全部上下文字段."""
    _request_context.set(None)


def get_context() -> Dict[str, Any]:
    """获取当前日志上下文.

    返回：
        Dict[str, Any]: 当前上下文字典。
    """
    return _request_context.get() or {}


def add_context_to_event_dict(logger: Any, method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """将上下文字段添加到日志事件字典.

    This processor adds any bound context variables to each log event.

    参数：
        logger: logger 实例。
        method_name: 日志方法名称。
        event_dict: 要修改的事件字典。

    返回：
        Dict[str, Any]: Modified event dictionary with context variables
    """
    context = get_context()
    if context:
        event_dict.update(context)
    return event_dict


def add_trace_context_to_event_dict(logger: Any, method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """将 request_id 注入每条日志事件.

    request_id 由 asgi-correlation-id 中间件生成，贯穿整个 HTTP 请求生命周期。
    如未来接入 OpenTelemetry，可在此处同时注入真正的 trace_id / span_id。
    """
    request_id = correlation_id.get()
    if request_id:
        event_dict["request_id"] = request_id
    return event_dict




_CST = timezone(timedelta(hours=8))  # 中国标准时间 UTC+8


def _now_cst() -> datetime:
    """返回当前北京时间（UTC+8），不依赖系统时区设置."""
    return datetime.now(_CST)


def _format_console_timestamp(value: Any) -> str:
    """把 structlog 的 ISO 时间转为控制台更易读的格式（北京时间）."""
    if not value:
        now = _now_cst()
        return f"{now:%Y-%m-%d %H:%M:%S}.{now.microsecond // 1000:03d}"

    raw = str(value)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        # 若是 UTC 时间（有时区信息），转换为北京时间
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(_CST)
        return f"{parsed:%Y-%m-%d %H:%M:%S}.{parsed.microsecond // 1000:03d}"
    except ValueError:
        return raw


def _build_console_parameters(event_dict: MutableMapping[str, Any]) -> Dict[str, Any]:
    """把请求相关细节汇总到统一的 Parameters 字段."""
    parameters: Dict[str, Any] = {}

    raw_parameters = event_dict.get("parameters")
    if isinstance(raw_parameters, dict):
        parameters.update(raw_parameters)

    request_payload = event_dict.get("request_payload")
    if request_payload is not None:
        parameters["body"] = request_payload

    query_params = event_dict.get("query_params")
    if query_params:
        parameters["query"] = query_params

    for field in READABLE_LOG_FIELD_ORDER:
        value = event_dict.get(field)
        if value is not None and value != "":
            parameters.setdefault(field, value)

    return parameters


def prepare_console_event_dict(logger: Any, method_name: str, event_dict: MutableMapping[str, Any]) -> Dict[str, Any]:
    """整理控制台字段顺序，让 structlog 彩色输出更适合人工阅读."""
    original_event = event_dict.get("event")
    parameters = _build_console_parameters(event_dict)
    timestamp = event_dict.get("timestamp")

    event_dict["event"] = str(original_event)
    event_dict["timestamp"] = _format_console_timestamp(timestamp)

    if parameters:
        event_dict["parameters"] = parameters

    # 控制台里去掉重复和过长字段；JSON/结构化语义仍由日志事件本身保留。
    for noisy_field in (
        "message",
        "request_payload",
        "query_params",
        "pathname",
        "filename",   # 代码行位置已在 [module.func:lineno] 里展示，filename 重复
        "logger",
        "logger_name",
    ):
        event_dict.pop(noisy_field, None)

    return dict(event_dict)


def render_text_log(logger: Any, method_name: str, event_dict: MutableMapping[str, Any]) -> str:
    """渲染适合本地调试阅读的彩色 text 日志.

    格式：
        {timestamp} - [{env}] - {LEVEL} - [trace:{id} span:{id}] - [{module.func:line}] - {事件}  {参数JSON}
    """
    timestamp   = event_dict.pop("timestamp", None)
    environment = event_dict.pop("environment", settings.ENVIRONMENT.value)
    level       = str(event_dict.pop("level", method_name)).upper()
    request_id  = event_dict.pop("request_id", "-") or "-"
    module      = event_dict.pop("module", None) or event_dict.pop("logger", None) or "app"
    func_name   = event_dict.pop("func_name", None)
    lineno      = event_dict.pop("lineno", None)
    event       = event_dict.pop("event", "")
    event_dict.pop("event_name", None)  # 控制台有中文描述，机器可读 key 不再单独展示
    parameters  = event_dict.pop("parameters", None)

    # 代码位置
    location = str(module)
    if func_name and lineno:
        location = f"{location}.{func_name}:{lineno}"
    elif lineno:
        location = f"{location}:{lineno}"

    id_display = request_id

    # 各段着色
    level_color = _LEVEL_COLOR.get(level, "")
    ts_str  = _c(_format_console_timestamp(timestamp), _GRAY)
    env_str = _c(f"[{environment}]", _GRAY)
    lvl_str = _c(f"{level:<8}", level_color, _BOLD if level in ("ERROR", "CRITICAL") else "")
    id_str  = _c(f"[{id_display}]", _CYAN)
    loc_str = _c(f"[{location}]", _DIM)
    evt_str = _c(
        str(event),
        _BOLD + level_color if level in ("ERROR", "CRITICAL") else level_color if level == "WARNING" else "",
    )

    line = " - ".join([ts_str, env_str, lvl_str, id_str, loc_str, evt_str])

    if parameters:
        param_str = json.dumps(parameters, ensure_ascii=False, default=str)
        line = f"{line}  {_c(param_str, _YELLOW)}"

    # 去掉已在 parameters 里展示过的字段，避免在 Fields 段重复打印
    for field in READABLE_LOG_FIELD_ORDER:
        event_dict.pop(field, None)
    # 去掉纯噪声字段（filename 已在 prepare_console_event_dict 里移除，这里兜底）
    event_dict.pop("filename", None)
    event_dict.pop("pathname", None)

    remaining_fields = {k: v for k, v in event_dict.items() if v not in (None, "", {})}
    if remaining_fields:
        fields_str = json.dumps(remaining_fields, ensure_ascii=False, default=str)
        line = f"{line}  {_c(fields_str, _GRAY)}"

    return line


def get_log_file_path() -> Path:
    """根据日期和环境获取当前日志文件路径.

    返回：
        Path: 日志文件路径。
    """
    env_prefix = settings.ENVIRONMENT.value
    return settings.LOG_DIR / f"{env_prefix}-{_now_cst().strftime('%Y-%m-%d')}.jsonl"


class JsonlFileHandler(logging.Handler):
    """将 JSONL 日志写入每日文件的自定义 handler."""

    def __init__(self, file_path: Path):
        """初始化 JSONL 文件 handler.

        参数：
            file_path: Path to the log file where entries will be written.
        """
        super().__init__()
        self.file_path = file_path

    @override
    def emit(self, record: logging.LogRecord) -> None:
        """将一条日志记录写入 JSONL 文件."""
        try:
            log_entry = {
                "timestamp": datetime.fromtimestamp(record.created, tz=_CST).isoformat(),
                "level": record.levelname,
                "message": record.getMessage(),
                "module": record.module,
                "function": record.funcName,
                "filename": record.pathname,
                "line": record.lineno,
                "environment": settings.ENVIRONMENT.value,
            }
            extra = getattr(record, "extra", None)
            if isinstance(extra, dict):
                log_entry.update(extra)

            with open(self.file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception:
            self.handleError(record)

    @override
    def close(self) -> None:
        """关闭 handler."""
        super().close()


def get_structlog_processors() -> List[Any]:
    """获取所有环境通用的 structlog processors.

    返回：
        List[Any]: structlog processor 列表。
    """
    return [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        # 将请求上下文字段（user_id、session_id 等）注入所有日志事件
        add_context_to_event_dict,
        # 将 request_id（=correlation_id）注入所有日志事件
        add_trace_context_to_event_dict,
        # 所有环境均记录代码位置，方便线上定位问题；filename/pathname 在渲染时会过滤掉
        structlog.processors.CallsiteParameterAdder(
            {
                structlog.processors.CallsiteParameter.FILENAME,
                structlog.processors.CallsiteParameter.FUNC_NAME,
                structlog.processors.CallsiteParameter.LINENO,
                structlog.processors.CallsiteParameter.MODULE,
                structlog.processors.CallsiteParameter.PATHNAME,
            }
        ),
        # 注入当前环境标识
        lambda _, __, event_dict: {**event_dict, "environment": settings.ENVIRONMENT.value},
    ]


def setup_logging() -> None:
    """配置 structlog，所有环境统一使用 text 格式.

    本地终端：_USE_COLORS=True，输出彩色日志，便于开发调试。
    Docker/K8s：isatty()=False，颜色自动关闭，输出纯文本，运维可按固定格式拆分字段。

    日志行格式：
        {timestamp} - [{env}] - {LEVEL} - [{request_id}] - [{module.func:line}] - {事件}  {参数JSON}
    """
    log_level = logging.DEBUG if settings.DEBUG else logging.INFO

    # 控制台输出（运维从容器标准输出采集日志）
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    logging.basicConfig(
        format="%(message)s",
        level=log_level,
        handlers=[console_handler],
    )

    # 第三方 HTTP 客户端日志太吵，只保留 WARNING 以上
    for logger_name in NOISY_THIRD_PARTY_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    # 统一 processor 链：所有环境格式完全一致
    structlog.configure(
        processors=[
            *get_structlog_processors(),
            prepare_console_event_dict,
            render_text_log,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


# 初始化日志
setup_logging()

# 创建 logger 实例
logger = structlog.get_logger()
logger.info("日志系统已初始化")
