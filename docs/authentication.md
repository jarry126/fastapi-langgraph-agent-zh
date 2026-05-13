# 鉴权说明

## 总体设计

项目使用一个全局用户 token。用户登录后拿到 JWT，后续创建会话、聊天、查看历史、删除历史等接口都使用同一个用户 token。

当前项目不再使用“创建会话时再生成一个 session token”的设计。

## 登录流程

```text
注册 / 登录
    ↓
返回用户 access_token
    ↓
创建聊天会话，返回 session_id
    ↓
聊天接口使用 access_token + session_id
```

## 请求头

```http
Authorization: Bearer <access_token>
```

## 创建会话

```http
POST /api/v1/auth/session
```

响应：

```json
{
  "session_id": "0038...",
  "name": ""
}
```

## 聊天请求

```json
{
  "session_id": "0038...",
  "messages": [
    {"role": "user", "content": "你好"}
  ]
}
```

服务端会校验：

- token 是否有效
- token 中的用户是否存在
- `session_id` 是否属于当前用户

## 为什么不使用会话 token

一个用户 token 更简单，前端只需要维护一份登录态。会话归属通过数据库校验完成，安全边界更清晰。

## 相关文件

- `app/api/v1/auth.py`：注册、登录、会话管理
- `app/utils/auth.py`：JWT 创建和校验
- `app/core/middleware.py`：请求上下文绑定
- `app/schemas/auth.py`：鉴权相关响应模型
