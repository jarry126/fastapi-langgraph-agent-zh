# 快速开始

## 1. 安装依赖

```bash
uv sync
```

## 2. 配置环境变量

复制 `.env.example` 为 `.env`，然后填写数据库、JWT、模型和记忆相关配置。

常见配置：

```env
APP_ENV=development
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=mydb
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
JWT_SECRET_KEY=please-change-me
DEFAULT_LLM_MODEL=qwen-plus
DASHSCOPE_API_KEY=your-key
```

## 3. 执行数据库迁移

```bash
uv run alembic upgrade head
```

## 4. 启动服务

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

接口文档：

```text
http://127.0.0.1:8000/docs
```

## 5. 注册用户

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/register   -H 'Content-Type: application/json'   -d '{"email":"user@example.com","password":"Password123","username":"orson"}'
```

## 6. 登录获取用户 token

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/login   -H 'Content-Type: application/x-www-form-urlencoded'   -d 'username=user@example.com&password=Password123&grant_type=password'
```

后续接口都使用这个用户 token。

## 7. 创建聊天会话

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/session   -H 'Authorization: Bearer <access_token>'
```

响应只包含：

```json
{
  "session_id": "...",
  "name": ""
}
```

## 8. 调用聊天接口

```bash
curl -X POST http://127.0.0.1:8000/api/v1/chatbot/chat   -H 'Authorization: Bearer <access_token>'   -H 'Content-Type: application/json'   -d '{
    "session_id": "<session_id>",
    "messages": [
      {"role": "user", "content": "你好"}
    ]
  }'
```

## 9. 获取聊天历史

```bash
curl 'http://127.0.0.1:8000/api/v1/chatbot/messages?session_id=<session_id>'   -H 'Authorization: Bearer <access_token>'
```

这里读取的是业务表 `chat_message`，不是 LangGraph checkpoint 表。
