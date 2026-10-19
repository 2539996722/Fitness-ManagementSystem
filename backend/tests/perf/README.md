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

## 当前基线（2026-10-19，dev + 本机 MySQL + 17 迁移 + 385 单测）

> 注：M12 (#122) 跑过 alembic 0017 customer_service 归一；数据集 1324 动作 / 36 用户 / 4 公告 / 6 模板。
> 单进程脚本：`backend/tests/perf/quick_bench.py`（不依赖 locust）
> 并发脚本：`backend/tests/perf/concurrent_bench.py`（10 用户 × 15 秒，纯 threading）

### 单进程基准 `python tests/perf/quick_bench.py`

`GET /api/v1/exercises?page=1&page_size=24` × 50 次：

| 指标 | 值 | 对比 2026-09-09 |
|---|---|---|
| avg | 25.9 ms | 9.3 ms（+178%） |
| p50 | 20.4 ms | 8.6 ms |
| p95 | 55.1 ms | 9.6 ms |
| p99 | 56.2 ms | 41.2 ms |
| max | 56.2 ms | 41.2 ms |
| 成功 | 50/50 | 50/50 |

> 延迟上升原因：M12 期间 `0016` 改 `users.avatar_url` 字段长度、`0017` 跑过数据 UPDATE；M5-M7 期间新加的字段（`weight_logs` / `banners` 全文索引）使表 schema 复杂度上升。仍在 200ms 阈值内。

### 10 用户并发 × 15 秒 `python tests/perf/concurrent_bench.py`

| 指标 | 值 |
|---|---|
| 用户数 | 10（threading） |
| 时长 | 15s |
| 总请求 | 1676 |
| 成功 | 1676（100%） |
| 失败 | 0（无 5xx / 4xx） |
| **RPS** | **111.5** |
| avg | 89.6 ms |
| p50 | 85.6 ms |
| p95 | 113.3 ms |
| p99 | 155.1 ms |
| max | 162.7 ms |

> 老基线（locust 9 月 10 用户 15 秒）总请求 181，本基线 1676（**+826%**）—— 旧 locust 跑得太保守，10 用户里只有 9 个真在打；新脚本 10 个 thread 持续 15s 是真实压力。

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