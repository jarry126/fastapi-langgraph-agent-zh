# 生产环境部署说明

> 本文记录首次将项目部署到阿里云 ECS 的完整过程，包含遇到的问题、解决方案和已做的简化说明。

---

## 当前部署架构（简化版）

```
阿里云 ECS（单台服务器）
├── Docker 容器：fastapi-langgraph-agent-zh（端口 8000）
├── Docker 容器：Langfuse（LLM 链路追踪，cloud 版本）
└── 阿里云 RDS PostgreSQL（托管数据库，不在本机）
```

**有意简化的部分（与标准生产不同）：**

| 简化项 | 当前做法 | 标准生产做法 |
|---|---|---|
| 监控 | 无 Prometheus / Grafana | 部署完整监控栈 |
| 缓存 / 限流存储 | 进程内存（单实例） | Redis / Valkey 分布式存储 |
| 日志持久化 | 仅输出到控制台 | 运维系统采集 stdout |
| 反向代理 | 无 Nginx | Nginx 做 SSL 终止和负载均衡 |
| 实例数量 | 单实例 | 多实例 + 负载均衡 |
| .env 管理 | 手动 scp / nano | Secret Manager 或 CI/CD 注入 |

---

## 部署前提条件

- 阿里云 ECS（Ubuntu 22.04）
- 阿里云 RDS PostgreSQL 15+（已安装 pgvector 和 pg_jieba 扩展）
- GitHub 仓库中已有完整代码（`.env.production` 在 `.gitignore` 中，不提交）

---

## 一、阿里云 RDS 权限修复（只做一次）

PostgreSQL 15 修改了默认权限策略，`public` schema 的 CREATE 权限不再自动授予所有用户。
阿里云 RDS 遵循此策略，即使账号叫 `postgres` 也无法直接建表。

**在 DBeaver 连接生产 RDS，执行：**

```sql
GRANT ALL ON SCHEMA public TO postgres;
```

---

## 二、执行数据库迁移（在本地执行，连接生产 RDS）

项目使用 Alembic 管理表结构，需要在部署前执行一次：

```bash
APP_ENV=production uv run alembic upgrade head
```

**迁移成功输出：**
```
Running upgrade  -> b25d38b0cd7c, 初始数据库结构
Running upgrade b25d38b0cd7c -> c7f2a08e4b1d, 新增聊天消息表
```

**表的来源说明：**

| 表 | 创建者 |
|---|---|
| `user` / `session` / `thread` / `chat_message` | Alembic 迁移脚本 |
| `checkpoints` / `checkpoint_blobs` / `checkpoint_writes` | LangGraph 启动时自动创建 |
| `longterm_memory_qwen_1024_v2` | mem0 第一次调用时自动创建 |

---

## 三、服务器初始化（只做一次）

### 安装 Docker

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-plugin git
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker $USER
exit  # 断开重连，使组权限生效
```

### 配置 Docker 镜像加速

```bash
sudo nano /etc/docker/daemon.json
```

写入：
```json
{
  "registry-mirrors": [
    "https://docker.1ms.run",
    "https://hub.rat.dev",
    "https://dockerproxy.com"
  ]
}
```

```bash
sudo systemctl daemon-reload
sudo systemctl restart docker
```

---

## 四、拉取代码

```bash
mkdir -p /app/code && cd /app/code
git clone https://github.com/jarry126/fastapi-langgraph-agent-zh.git
cd fastapi-langgraph-agent-zh
```

---

## 五、创建生产环境配置文件

`.env.production` 不在 Git 中，需要手动在服务器上创建：

```bash
nano .env.production
# 粘贴本地 .env.production 内容，Ctrl+X → Y → Enter 保存
```

---

## 六、构建并启动容器

```bash
APP_ENV=production docker compose -f docker-compose.production.yml up -d --build
```

### 验证启动成功

```bash
# 查看日志（应看到 Uvicorn running on http://0.0.0.0:8000）
docker compose -f docker-compose.production.yml logs --tail=50 app

# 健康检查
curl http://localhost:8000/health
```

成功响应：
```json
{"status":"healthy","version":"1.0.0","environment":"production"}
```

---

## 七、后续更新部署

代码有更新时：

```bash
cd /app/code/fastapi-langgraph-agent-zh
git pull

# 仅代码变更（无新依赖）：重启即可，无需重新构建
docker compose -f docker-compose.production.yml down
APP_ENV=production docker compose -f docker-compose.production.yml up -d

# 有新依赖或 Dockerfile 变更：需要重新构建
APP_ENV=production docker compose -f docker-compose.production.yml up -d --build
```

---

## 常用运维命令

```bash
# 查看实时日志
docker compose -f docker-compose.production.yml logs -f app

# 查看容器状态
docker compose -f docker-compose.production.yml ps

# 重启服务
docker compose -f docker-compose.production.yml restart app

# 停止服务
docker compose -f docker-compose.production.yml down
```

---

## 部署过程中遇到的问题记录

### 问题 1：RDS schema 权限不足

**报错：** `permission denied for schema public`

**原因：** PostgreSQL 15 不再自动给 `public` schema 授予 CREATE 权限。

**解决：** DBeaver 连接 RDS 执行 `GRANT ALL ON SCHEMA public TO postgres;`

---

### 问题 2：端口 8000 被占用

**报错：** `Bind for 0.0.0.0:8000 failed: port is already allocated`

**原因：** 服务器上已有另一个项目（codex55-rag-api）占用了 8000 端口。

**解决：** `docker stop codex55-rag-api`

---

### 问题 3：容器找不到 .env.production

**报错：** `Warning: No .env file found. Using system environment variables.`

**原因：** `.env.production` 在 `.gitignore` 中，git clone 后不存在。`docker-entrypoint.sh` 在容器内用 shell 再读一次文件，但文件没有挂载进容器。

**解决：** 在 `docker-compose.production.yml` 中挂载文件：
```yaml
volumes:
  - ./.env.production:/app/.env.production:ro
```

---

### 问题 4：apt 和 pip 拉取缓慢

**原因：** 服务器在国内，Debian 官方源和 PyPI 官方源访问慢。

**解决：** Dockerfile 中切换为阿里云镜像：

```dockerfile
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources

RUN uv sync --frozen --index-url https://mirrors.aliyun.com/pypi/simple/
```

注意：不要加 `--extra-index-url https://pypi.org/simple/`，pypi.org 在国内访问超时。

---

### 问题 5：OpenAI 模型注册导致启动失败

**报错：** `Missing credentials. OPENAI_API_KEY`

**原因：** `llm/registry.py` 中的 `LLMS` 是类变量，模块导入时会实例化所有模型（包括 gpt-5-mini 等 OpenAI 模型），而项目只使用 DashScope，`OPENAI_API_KEY` 为空导致报错。

**解决：** 删除 registry.py 中所有 OpenAI 模型，只保留 qwen 系列。

---

### 问题 6：日志文件写入权限错误

**报错：** `logging.py emit handleError`

**原因：** 容器以非 root 用户（appuser）运行，但宿主机 `logs` 目录由 root 创建，挂载后没有写权限。

**解决：** 移除文件日志 handler，只保留控制台输出（符合实际运维采集方式）。

---

### 问题 7：AsyncMemory.from_config 不能 await

**报错：** `TypeError: object AsyncMemory can't be used in 'await' expression`

**原因：** 本地用 `uv sync` 按 `uv.lock` 安装，Docker 用 `uv pip install -e .` 拉取最新版，两者 mem0 版本不同，新版 `from_config` 是同步方法。

**解决：** Dockerfile 改为 `uv sync --frozen`，强制使用 `uv.lock` 中的版本，保证本地与容器一致。
