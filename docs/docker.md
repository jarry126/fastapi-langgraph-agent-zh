# Docker 运行说明

## 组件

`docker-compose.yml` 可以启动以下服务：

| 服务 | 端口 | 说明 |
| --- | --- | --- |
| `app` | 8000 | FastAPI 应用 |
| `db` | 5432 | PostgreSQL + pgvector |
| `valkey` | 6379 | Redis 兼容缓存，可选 |
| `prometheus` | 9090 | 指标采集 |
| `grafana` | 3000 | 指标图表展示 |
| `cadvisor` | 8080 | 容器指标采集 |

## 启动

```bash
docker compose up --build
```

或者使用 Makefile：

```bash
make docker-run
```

## 访问地址

```text
FastAPI:    http://127.0.0.1:8000
Swagger:    http://127.0.0.1:8000/docs
Prometheus: http://127.0.0.1:9090
Grafana:    http://127.0.0.1:3000
```

Grafana 默认账号通常是：

```text
admin / admin
```

## Prometheus 配置

Prometheus 配置在：

```text
prometheus/prometheus.yml
```

它会抓取：

```text
app:8000/metrics
cadvisor:8080
```

## 本地不启动 Prometheus/Grafana 是否影响应用

不影响。FastAPI 只负责暴露 `/metrics`，Prometheus/Grafana 是可选观测组件。
