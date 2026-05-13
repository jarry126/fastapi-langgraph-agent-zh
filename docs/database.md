# 数据库说明

## 数据库类型

项目使用 PostgreSQL。长期记忆需要 pgvector 扩展。

## 业务表

主要业务表：

| 表 | 用途 |
| --- | --- |
| `user` | 用户账号 |
| `session` | 聊天会话 |
| `chat_message` | 每一轮用户问题和助手答案 |

`chat_message` 是业务聊天记录表，适合前端展示历史对话、后台审计和问题排查。

## LangGraph 表

LangGraph 会自动创建 checkpoint 相关表，例如：

```text
checkpoints
checkpoint_blobs
checkpoint_writes
```

这些表用于 LangGraph 内部状态恢复，不建议作为业务聊天记录表使用。

## 长期记忆表

mem0 + pgvector 会创建长期记忆 collection 对应的表，例如：

```text
longterm_memory_qwen_1024_v2
```

这里保存的是用户偏好、事实、计划等长期记忆向量，不是完整聊天记录。

## 迁移

项目使用 Alembic 管理业务表迁移。

```bash
uv run alembic upgrade head
```

新增迁移：

```bash
uv run alembic revision -m "描述"
```

## 数据边界

- 业务聊天历史：查 `chat_message`
- LangGraph 状态恢复：查 checkpoint 表
- 用户长期记忆：查 mem0 / pgvector collection 表
