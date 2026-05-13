# 配置说明

## 配置文件加载顺序

项目会根据 `APP_ENV` 加载环境变量文件，优先级大致为：

```text
.env.<environment>.local
.env.<environment>
.env.local
.env
```

## 常用环境

```env
APP_ENV=development
DEBUG=true
LOG_FORMAT=text
```

生产环境建议：

```env
APP_ENV=production
DEBUG=false
LOG_FORMAT=json
```

## 数据库配置

```env
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=mydb
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
```

## JWT 配置

```env
JWT_SECRET_KEY=please-change-me
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_DAYS=30
```

## LLM 配置

```env
DEFAULT_LLM_MODEL=qwen-plus
DASHSCOPE_API_KEY=your-key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MAX_TOKENS=2000
LLM_TOTAL_TIMEOUT=60
```

## 长期记忆配置

```env
LONG_TERM_MEMORY_MODEL=qwen-plus
LONG_TERM_MEMORY_EMBEDDER_MODEL=text-embedding-v4
LONG_TERM_MEMORY_EMBEDDING_DIMS=1024
LONG_TERM_MEMORY_COLLECTION_NAME=longterm_memory_qwen_1024_v2
```

## 缓存配置

如果配置了 `VALKEY_HOST`，项目会使用 Valkey/Redis；否则使用进程内存缓存。

```env
VALKEY_HOST=localhost
VALKEY_PORT=6379
CACHE_TTL_SECONDS=60
```

## 日志配置

```env
LOG_LEVEL=INFO
LOG_FORMAT=text
LOG_DIR=logs
```

当前阶段建议先使用 `text`，方便本地和测试环境直接阅读。后期接 Elasticsearch/Loki/OpenSearch 时，可以再切换为 `json`。
