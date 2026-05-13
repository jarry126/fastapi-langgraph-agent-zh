# LLM 服务

## 概览

LLM 服务负责统一调用大模型，处理重试、超时、模型切换、工具绑定和结构化输出。

核心文件：

```text
app/services/llm/registry.py
app/services/llm/service.py
```

## 模型注册

`registry.py` 维护可用模型列表。默认模型由配置项控制：

```env
DEFAULT_LLM_MODEL=qwen-plus
```

## 调用流程

```text
业务代码
  ↓
LLMService.call()
  ↓
_invoke_with_retry()
  ↓
失败后 tenacity 重试
  ↓
仍失败则 fallback 到下一个模型
```

## 重试策略

项目使用 tenacity 做重试。常见可重试错误包括：

- 限流
- 超时
- 服务端临时错误

## fallback 机制

如果当前模型多次调用失败，服务会切换到注册表里的下一个模型。

## 工具绑定

LangGraph Agent 初始化时会把工具绑定到默认 LLM 上。如果模型 fallback，工具绑定也会迁移到新模型。

## 结构化输出

调用 `LLMService.call(..., response_format=SomePydanticModel)` 时，会使用模型的结构化输出能力返回 Pydantic 对象。

## 日志

关键日志：

| event | 说明 |
| --- | --- |
| `llm_call_started` | 开始调用大模型 |
| `llm_call_successful` | 大模型调用成功 |
| `llm_call_failed_retrying` | 调用失败，准备重试 |
| `llm_call_failed_after_retries` | 当前模型重试后仍失败 |
| `model_switched` | 已切换模型 |
| `all_models_failed` | 所有模型均失败 |
