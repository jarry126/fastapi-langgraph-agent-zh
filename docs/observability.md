# 观测说明

## 观测组件

项目包含三类观测能力：

| 类型 | 工具 | 用途 |
| --- | --- | --- |
| 日志 | structlog + stdout | 排查业务链路和异常 |
| 指标 | Prometheus + Grafana | 查看 QPS、耗时、错误率 |
| LLM 追踪 | Langfuse | 查看模型输入、输出、耗时和 token |

## 日志

项目使用 structlog 输出混合日志：既适合人看，也适合 Elasticsearch/Grafana 查询。

一条典型日志包含：

```json
{
  "event": "chat_request_received",
  "event_cn": "收到聊天请求",
  "message": "收到聊天请求 | user_id=1, session_id=0038..., message_count=1",
  "request_id": "56ef...",
  "user_id": 1,
  "session_id": "0038...",
  "level": "info"
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `event` | 稳定事件名，适合机器查询 |
| `event_cn` | 中文含义，适合人阅读 |
| `message` | 中文摘要，适合 Grafana 列表展示 |
| `request_id` | 一次 HTTP 请求的链路 ID |
| `user_id` | 当前用户 |
| `session_id` | 当前聊天会话 |

## 请求排查

生产环境中可以先搜 `request_id`，一条聊天请求通常会看到：

```text
request_started
chat_request_received
memory_search_started
memory_search_finished
llm_call_started
llm_call_successful
llm_response_generated
chat_message_created
chat_request_processed
request_finished
```

常用查询：

```text
request_id = "..."
event = "chat_request_failed"
status_code >= 500
duration_ms > 3000
user_id = 1 AND event = "chat_message_created"
```

## Prometheus 和 Grafana

FastAPI 暴露：

```text
GET /metrics
```

Prometheus 定时采集 `/metrics`，Grafana 根据 Prometheus 数据画图。

常见指标：

| 指标 | 说明 |
| --- | --- |
| `http_requests_total` | HTTP 请求总数 |
| `http_request_duration_seconds` | HTTP 请求耗时 |
| `llm_inference_duration_seconds` | LLM 调用耗时 |
| `llm_stream_duration_seconds` | 流式响应耗时 |
| `session_names_generated_total` | 会话标题生成次数 |

## Langfuse

Langfuse 用来查看 LLM 调用链路，包括输入、输出、模型、耗时和 token 用量。

本地不想启用可以配置：

```env
LANGFUSE_TRACING_ENABLED=false
```

## 慢请求分析

当 `DEBUG=true` 时，慢请求会写入 `PROFILING_DIR`，文件名包含 `request_id`，方便和日志对应起来。
