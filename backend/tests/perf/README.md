# FitHub 性能测试指南

> 工具：Locust（基于 Python 协程，单进程模拟上千用户）。脚本在 `backend/tests/perf/locustfile.py`。
> 当前基线（dev + 本机 MySQL）见文末。

## 快速开始

```bash
cd backend
.venv/Scripts/python.exe -m pip install locust        # 首次

# 1) 启动被测服务
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8002

# 2) 不开浏览器，单进程快速基准（不开 locust）
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tests/perf/locustfile.py

# 3) 浏览器压测（推荐）
.venv/Scripts/python.exe -m locust -f tests/perf/locustfile.py --host=http://127.0.0.1:8002
# 打开 http://localhost:8089，填入 Users=50 / Spawn rate=10 / Host=已填，点 Start

# 4) 无界面压测
.venv/Scripts/python.exe -m locust -f tests/perf/locustfile.py \
    --host=http://127.0.0.1:8002 --headless -u 50 -r 10 -t 60s --csv=perf_report
```

## 覆盖的场景

| 类别 | 占比 | 接口 |
|---|---|---|
| `CEndUser` | 9/10 | `/exercises`（带/不带筛选）、`/exercises/{id}`、`/exercises/filters`、`/plan-templates`、`/banners/active`、`/health` |
| `AdminUser` | 1/10 | `/admin/dashboard/overview`、`/admin/dashboard/ai-cost`、`/admin/templates/queue`、`/admin/dashboard/user-trend` |

## 性能阈值（dev 环境参考）

| 指标 | 阈值 | 说明 |
|---|---|---|
| avg | < 50 ms | 健康 |
| p50 | < 50 ms | 健康 |
| p95 | < 200 ms | 健康；超过要查 SQL |
| p99 | < 500 ms | 健康；超过要查索引或加缓存 |
| max | < 1000 ms | 偶发抖动可接受 |

## 当前基线（2026-09-09，dev + 本机 MySQL）

### 单进程基准 `tests/perf/locustfile.py quick_benchmark`

`GET /api/v1/exercises?page=1&page_size=24` × 50 次：

| 指标 | 值 |
|---|---|
| avg | 9.3 ms |
| p50 | 8.6 ms |
| p95 | 9.6 ms |
| p99 | 41.2 ms |
| max | 41.2 ms |

### 10 用户并发 × 15 秒（locust --headless）

| 端点 | p50 | p95 | 总请求 |
|---|---|---|---|
| `/exercises` (带筛选) | 40 ms | 77 ms | 40 |
| `/exercises` (无筛选) | 41 ms | 50 ms | 41 |
| `/exercises/{id}` | 19 ms | 29 ms | 19 |
| `/exercises/filters` | 27 ms | 35 ms | 27 |
| `/plan-templates` | 25 ms | 27 ms | 25 |
| `/banners/active` | 29 ms | 29 ms | 29 |
| C 端**聚合** | **29 ms** | **77 ms** | **181** |
| `/admin/*` (B 端) | 16 ms | 16 ms | 63 |

## 已识别的潜在瓶颈

| 端点 | 风险点 | 优化建议 |
|---|---|---|
| `GET /exercises/filters` | 4-5 条 `DISTINCT` 聚合全表 | 数据集 1324 行还能撑；>10 万行时需 `GROUP BY` 缓存到 Redis 或物化视图 |
| `GET /exercises/{id}` | 主键查询 | 当前很快；后续加评论预加载时要注意 N+1 |
| `POST /chat/send` | LLM API 同步等待 | 已加 5/min + 50/day 限流；超时 60s 已是上限 |
| `POST /chat/send/stream` | 同上 | SSE 推送；客户端断线不会反向取消（后续优化） |
| `GET /admin/dashboard/ai-cost` | `GROUP BY date(intent)` | 数据量大时按月聚合表 + 增量更新 |

## 压测前必须做的事

1. **不要**用 `admin/admin123` 跑压测 —— 创建专用账号 + token
   ```bash
   # 后台创建 user_role=test 账号
   python -m app.db.seed_cs --users "perf1:Perf123456"
   # 拿 token
   curl -X POST http://127.0.0.1:8002/api/v1/auth/login \
       -d '{"username":"perf1","password":"Perf123456"}'
   # 注入 locust
   export PERF_USER_TOKEN=<access_token>
   ```
2. **确认**慢查询日志已开（生产部署时要观察 SQL 性能）
3. **关掉** `LOG_LEVEL=INFO`（高压测时写日志拖慢）；改为 `WARNING`
4. **MySQL** 配置：
   - `innodb_buffer_pool_size` ≥ 数据集 2 倍
   - `query_cache_size` ≥ 64MB（旧版本 MySQL 8 不需要）
   - 打开 `slow_query_log`，阈值 100ms

## 不在 MVP 测试范围

- LLM 端到端（受外部厂商限流，无法压测）
- WebSocket / SSE 长连接（locust 不擅长）
- 文件上传（需先准备大文件 fixture）

这些建议用其它工具（k6/wrk）单独测试。