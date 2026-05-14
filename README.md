# fastapi-langgraph-agent-zh

> 基于 [fastapi-langgraph-agent-production-ready-template](https://github.com/wassim249/fastapi-langgraph-agent-production-ready-template) 的中文适配版本，面向国内开发者的生产级 LangGraph 工作流编排框架。

---

## 项目简介

本项目是一个开箱即用的 **LangGraph + FastAPI 生产级智能体模板**，适合作为国内团队构建 AI Agent 应用的起点。

在原项目基础上完成了以下工作：
- 全面的中文注释，降低阅读和接手门槛
- 对接阿里云 DashScope（Qwen 系列模型 + qwen-embedding）
- 完整的本地链路调试验证（PostgreSQL + pgvector + mem0 + pg_jieba）
- 认证流程简化、日志系统重构

---

## 核心能力

| 能力 | 实现方式 |
|---|---|
| 异步 REST API | FastAPI |
| AI Agent 工作流编排 | LangGraph（StateGraph + 工具调用） |
| LLM 调用 / 重试 / Fallback | LangChain + tenacity |
| 长期记忆 | mem0 + pgvector + qwen-embedding |
| 中文语义检索 | pg_jieba 分词插件 | （待定）
| 业务数据 + Checkpoint 持久化 | PostgreSQL + SQLModel |
| 用户鉴权 | JWT（登录 token 全程通用） |
| 结构化日志 | structlog（本地彩色 / 容器纯文本统一格式） |
| 指标监控 | Prometheus + Grafana |
| LLM 链路追踪 | Langfuse |
| 限流 | slowapi |

---

## 相较于原项目的改动

### 1. 认证流程简化

**原流程：** 登录 → 获取 token → 调用 `/session` 换取新 token → 使用新 token 请求

**现流程：** 登录 → 获取 token → 直接使用该 token 请求所有接口

去除冗余的 session 换 token 步骤，客户端逻辑更简单。

---

### 2. 长期记忆向量化方案替换

| | 原项目 | 本项目 |
|---|---|---|
| 向量表 | mem0migrations | longterm_memory_qwen_1024_v2 |
| Embedding 模型 | OpenAI text-embedding | 阿里云 qwen-text-embedding-v3 |
| 向量维度 | 1536 | 1024 |
| 适用网络环境 | 海外 OpenAI | 国内阿里云 DashScope |

---

### 3. 日志系统重构

所有环境统一使用 text 格式，消除本地与线上的行为差异：

- **本地终端**：自动着色（INFO 绿 / WARNING 黄 / ERROR 红）
- **Docker / K8s 容器**：`isatty()=False` 自动关闭颜色，输出纯文本
- 运维可按固定格式拆分字段

**日志行格式：**
```
2026-05-13 10:30:45.123 - [production] - INFO     - [6e932b38] - [chatbot.chat:138] - 收到聊天请求  {"session_id": "sess_abc", "user_id": "42", "message_count": 3}
```

---

### 4. 限流策略改为按用户 ID

**原项目：** 按客户端 IP 限流，同一出口 IP 下的所有用户共享配额，公司/学校内网多人使用时会互相消耗。

**本项目：** 改为按登录用户 ID 限流，每个用户拥有独立配额，互不干扰。

| | 原项目 | 本项目 |
|---|---|---|
| 限流维度 | 客户端 IP | 登录用户 ID |
| 未登录请求 | 按 IP 限流 | 降级为 IP 限流兜底 |
| 多人共用 IP | 共享配额，互相影响 | 各自独立，互不干扰 |

如需切换回按 IP 限流，修改 `app/core/limiter.py` 中的 `key_func` 即可：

```python
key_func=get_user_id,           # 按用户 ID 限流（当前）
# key_func=get_remote_address,  # 按 IP 限流（切换时取消注释，注释上一行）
```

#### slowapi 限流规则说明

本项目使用 `app.state.limiter` 挂载方式（非 `SlowAPIMiddleware`），限流规则如下：

| 场景 | 行为 |
|---|---|
| 接口上有 `@limiter.limit("X/minute")` | 按该接口自身配置限流，每个接口独立计数 |
| 接口上没有 `@limiter.limit()` | **不做任何限流**，请求直接放行 |
| `Limiter(default_limits=...)` | 在当前挂载方式下对无装饰器接口**不生效**，仅作配置留存 |

> **注意**：若改用 `SlowAPIMiddleware` 中间件模式，`default_limits` 会对所有无装饰器的接口自动生效。
> 当前选择 `app.state.limiter` 挂载是为了精确控制——只有主动声明限流的接口才受约束，避免对健康检查等内部接口误限。

**当前各接口限额一览：**

| 接口 | 限额 |
|---|---|
| `POST /chatbot/chat` | 30 次 / 分钟 |
| `POST /chatbot/chat/stream` | 20 次 / 分钟 |
| `GET/DELETE /chatbot/messages` | 50 次 / 分钟 |
| `POST /auth/register` | 10 次 / 小时 |
| `POST /auth/login` | 20 次 / 分钟 |
| `GET /health` | 无限流 |
| `GET /debug/rate-limit/ping`（压测专用） | 10 次 / 分钟 |

---

### 5. 限流错误响应优化

**原项目：** 使用 slowapi 内置的 `_rate_limit_exceeded_handler`，存在两个问题：
- 直接 `print` 到 stdout，绕过 structlog，日志格式与其他日志不一致，无法按用户追溯
- 返回的错误信息为英文技术报错，对用户不友好

**本项目：** 在 `app/main.py` 中注册自定义 handler 替换内置实现：

```python
async def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    # 通过 structlog 记录结构化日志，包含触发限流的用户/IP 和限额信息
    logger.warning("请求频率超出限制", path=path, rate_limit_key=rate_limit_key, limit=limit_str)
    # 返回友好的中文提示
    return JSONResponse(status_code=429, content={"detail": "请求过于频繁，请稍后再试", ...})
```

| | 原项目 | 本项目 |
|---|---|---|
| 日志输出 | `print` 绕过 structlog | structlog `WARNING` 结构化日志 |
| 日志包含限流 key | ❌ | ✅ `rate_limit_key: user:42` |
| 客户端错误提示 | 英文技术信息 | 中文友好提示 |

**触发限流时的日志示例：**
```
WARNING - 请求频率超出限制  {"path": "/api/v1/chatbot/chat", "rate_limit_key": "user:1", "limit": "10 per 1 minute", "client_ip": "127.0.0.1"}
```

**触发限流时客户端收到的响应：**
```json
{
  "detail": "请求过于频繁，请稍后再试",
  "limit": "10 per 1 minute",
  "hint": "如持续受限，请联系管理员"
}
```

---

### 6. 限流压测验证（JMeter）

新增专用轻量压测接口 `GET /api/v1/debug/rate-limit/ping`（仅开发 / 测试环境可用），绕开 LangGraph session 锁，可真正并发触发 slowapi 计数。

**为什么需要专用压测接口？**

`/chatbot/chat` 接口底层由 LangGraph 的 `AsyncPostgresSaver` 对同一 `session_id` 加数据库行锁，导致并发请求在 DB 层串行化。每次 LLM 调用约需 10~15 秒，1 分钟内只能完成约 5~9 次请求，远低于 30 次 / 分钟的限额，slowapi 没有机会触发 429。

**压测结果（JMeter，15 线程，Ramp-Up=0，瞬间并发）：**

```
限额：10次 / 分钟（按用户 ID）

前 10 个请求 → 200 OK（约 16~29ms）
后  5 个请求 → 429 Too Many Requests
```

日志中可清晰看到限流 key 和限额，便于运维排查：
```
INFO    - 限流压测 ping          {"rate_limit_key": "user:1"}   ×10
WARNING - 请求频率超出限制       {"rate_limit_key": "user:1", "limit": "10 per 1 minute"}  ×5
```

如需查看当前限流计数，可调用配套调试接口：
```
GET /api/v1/debug/rate-limit/check?user_id=1
GET /api/v1/debug/rate-limit/storage-info
```

---

### 7. 中文注释与本地化

- 所有核心模块补充中文注释
- 日志事件名统一使用中文，去除英文 key + 中文描述的双键冗余模式

---

### 8. 本地完整链路验证

完成以下组件的端到端测试：
- PostgreSQL + pgvector 向量存储
- mem0 长期记忆（search / add）
- pg_jieba 中文分词
- qwen-embedding 向量化
- LangGraph 多轮对话 + 工具调用

---

## 技术栈

```
FastAPI · LangGraph · LangChain · PostgreSQL · pgvector
mem0ai · pg_jieba · SQLModel · structlog · Prometheus
Grafana · Langfuse · slowapi · tenacity · Pydantic v2
阿里云 DashScope（Qwen LLM + qwen-embedding）
```

---

## 快速启动

### 环境要求

- Python 3.11+
- PostgreSQL 15+（需安装 pgvector、pg_jieba 扩展）
- uv

### 安装依赖

```bash
uv sync
```

### 配置环境变量

```bash
cp .env.example .env.development
# 编辑 .env.development，填写数据库连接、DashScope API Key 等
```

### 启动服务

```bash
# 本地开发
make dev

# Docker 启动（API + DB）
make docker-run

# 完整栈（API + Prometheus + Grafana）
make docker-compose-up ENV=development
```

### 接口文档

```
http://127.0.0.1:8000/docs
```

---

## 常用命令

```bash
make install          # 安装依赖（uv sync）
make dev              # 本地热加载启动（端口 8000）
make lint             # ruff 代码检查
make format           # ruff 格式化
make typecheck        # pyright 类型检查
make check            # lint + typecheck
make eval             # 运行 LLM 评测（交互式）
make eval-quick       # 运行 LLM 评测（默认配置）
make docker-run       # Docker 启动 API + DB
```

---

## 项目结构

```
app/
  api/v1/            # 路由（auth.py · chatbot.py · api.py）
  core/
    config.py        # Pydantic Settings 配置
    langgraph/       # LangGraph Agent 图 + 工具
    logging.py       # structlog 日志配置
    middleware.py    # ASGI 中间件
    metrics.py       # Prometheus 指标
    limiter.py       # 限流（slowapi）
    prompts/         # 系统提示词
  models/            # SQLModel ORM 模型
  schemas/           # Pydantic 请求/响应模型 + 图状态
  services/          # 业务逻辑（database · memory · llm）
  utils/             # 公共工具函数
evals/               # LLM 评测框架（基于 Langfuse）
scripts/             # 环境初始化、Docker 构建脚本
```

---

## 文档目录

| 文档 | 说明 |
|---|---|
| [快速开始](docs/getting-started.md) | 本地启动、注册、登录、聊天接口示例 |
| [架构说明](docs/architecture.md) | 项目整体架构和请求链路 |
| [鉴权说明](docs/authentication.md) | JWT、用户 token、会话归属校验 |
| [数据库说明](docs/database.md) | 业务表、迁移、checkpoint 表说明 |
| [长期记忆](docs/memory.md) | mem0、pgvector、长期记忆读写流程 |
| [LLM 服务](docs/llm-service.md) | 模型注册、重试、fallback、结构化输出 |
| [Docker](docs/docker.md) | Docker Compose 启动方式 |
| [配置说明](docs/configuration.md) | `.env` 配置项和环境切换 |
| [观测说明](docs/observability.md) | 日志、Prometheus、Grafana、Langfuse |
| [评测说明](docs/evaluation.md) | LLM 输出评测框架 |

---

## 致谢

本项目基于 [wassim249/fastapi-langgraph-agent-production-ready-template](https://github.com/wassim249/fastapi-langgraph-agent-production-ready-template) 进行二次开发，感谢原作者的开源贡献。
