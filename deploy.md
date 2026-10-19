# FitHub 部署指南

> 生产环境上线手册。开发模式用 `docker-compose.yml`，生产用 [`docker-compose.prod.yml`](./docker-compose.prod.yml)。

## 目录

1. [前置条件](#1-前置条件)
2. [生成密钥](#2-生成密钥)
3. [准备 `.env.prod`](#3-准备-envprod)
4. [准备数据](#4-准备数据)
5. [构建 + 启动](#5-构建--启动)
6. [验证 + 健康检查](#6-验证--健康检查)
7. [运维](#7-运维)
8. [回滚](#8-回滚)
9. [故障排查](#9-故障排查)

---

## 1. 前置条件

| 依赖 | 版本 | 用途 |
|---|---|---|
| Docker | 24.0+ | 容器化 |
| Docker Compose | v2 (内置) | 多服务编排 |
| 反向代理 | nginx / caddy | 域名 + HTTPS（推荐前置） |
| 主机端口 | 80 / 443 | HTTPS 入口（443 推荐前置 nginx 终止 TLS） |

> 资源：2 vCPU + 4GB RAM 起步；1000 并发建议 4 vCPU + 8GB。

---

## 2. 生成密钥

```bash
# JWT 密钥（必须 32+ 字符，生产前用此覆盖默认）
openssl rand -hex 32

# 默认管理员密码（≥16 位随机）
openssl rand -base64 18

# MySQL root / 应用账号密码（≥20 位随机）
openssl rand -base64 24

# Redis 密码
openssl rand -hex 24
```

**全部保存到密码管理器**（1Password / Bitwarden / Vault），不要提交到 git。

---

## 3. 准备 `.env.prod`

新建 `项目根/.env.prod`（**绝不提交**）：

```bash
# ---------- 应用 ----------
APP_ENV=production
DEBUG=false
LOG_LEVEL=INFO
TZ=Asia/Shanghai

# ---------- 主机端口 ----------
FRONTEND_PORT=80
BACKEND_PORT=8000    # 127.0.0.1 绑定，外部走 nginx
MYSQL_PORT=3306      # 127.0.0.1 绑定
REDIS_PORT=6379      # 127.0.0.1 绑定

# ---------- 数据库（必填）----------
MYSQL_ROOT_PASSWORD=<openssl rand -base64 24>
MYSQL_USER=fithub_user
MYSQL_PASSWORD=<openssl rand -base64 24>
MYSQL_DB=fithub
MYSQL_INNODB_BUFFER_POOL_SIZE=1G
MYSQL_MAX_CONNECTIONS=500

# ---------- 后端资源 ----------
BACKEND_WORKERS=4
BACKEND_CPU_LIMIT=2.0
BACKEND_MEMORY_LIMIT=2G

# ---------- JWT（必填）----------
JWT_SECRET=<openssl rand -hex 32>
ACCESS_TOKEN_EXPIRE_MINUTES=120
REFRESH_TOKEN_EXPIRE_DAYS=7

# ---------- 默认管理员（必填且不能是 admin/admin123）----------
DEFAULT_ADMIN_USERNAME=fithub_admin
DEFAULT_ADMIN_PASSWORD=<openssl rand -base64 18>

# ---------- CORS（域名白名单，逗号分隔）----------
CORS_ORIGINS=https://fithub.example.com

# ---------- LLM（必填）----------
LLM_API_BASE=https://api.openai.com/v1
LLM_API_KEY=sk-...
LLM_MODEL_CHAT=gpt-4o-mini
LLM_MODEL_EMBED=text-embedding-3-small

# ---------- Redis ----------
REDIS_PASSWORD=<openssl rand -hex 24>
REDIS_MAXMEM=512mb

# ---------- 限流 ----------
RATE_LIMIT_PER_MINUTE=60
RATE_LIMIT_AI_PER_USER_PER_DAY=50

# ---------- 数据集（主机绝对路径）----------
HOST_EXERCISES_DIR=/opt/fithub/data/exercises-dataset-zh
```

应用启动时会自动校验（[SECURITY.md §1](./SECURITY.md)）：
- `APP_ENV=production` 但 `DEBUG=true` → 启动失败
- `JWT_SECRET` 是占位 → 启动失败
- 默认 admin 密码是 `admin123`/`password` → 启动失败

---

## 4. 准备数据

### 4.1 动作数据集（首次部署）

```bash
mkdir -p /opt/fithub/data
cd /opt/fithub/data
git clone https://github.com/wangmuerxiao/exercises-dataset-zh.git
# 路径写到 .env.prod 的 HOST_EXERCISES_DIR
```

### 4.2 MySQL 数据卷

`docker-compose.prod.yml` 自动建 `mysql_prod_data` 卷。如需从已有数据恢复：

```bash
# 1) 停服
docker-compose -f docker-compose.prod.yml stop

# 2) 临时启一个 mysql，挂载备份
docker run --rm -it \
  -v fithub_mysql_prod_data:/var/lib/mysql \
  -v /path/to/backup:/backup:ro \
  mysql:8.0 \
  bash -c "mysqldump --all-databases > /backup/dump.sql"

# 3) 重新启动
docker-compose -f docker-compose.prod.yml up -d
```

---

## 5. 构建 + 启动

```bash
# 1) 拉取/构建镜像
docker-compose -f docker-compose.prod.yml --env-file .env.prod build

# 2) 后台启动
docker-compose -f docker-compose.prod.yml --env-file .env.prod up -d

# 3) 看启动日志（确认没报错）
docker-compose -f docker-compose.prod.yml logs -f --tail=200

# 应看到类似：
# mysql    | 2026-10-19T... [System] [MY-013602] Server handshake complete
# backend  | 🗄️ 数据库引擎已创建 | pool_size=20
# backend  | 🚀 Application startup complete
# frontend | start worker processes
```

**首次启动需手动跑迁移**（MySQL 容器起来后、backend 健康之前）：

```bash
# 1) 等 mysql 30 秒就绪
sleep 30

# 2) 跑迁移（在 backend 容器内）
docker-compose -f docker-compose.prod.yml exec backend alembic upgrade head

# 3) 导入种子（可选）
docker-compose -f docker-compose.prod.yml exec backend python -m app.db.create_default_admin
docker-compose -f docker-compose.prod.yml exec backend python -m app.db.seed_exercises
docker-compose -f docker-compose.prod.yml exec backend python -m app.db.seed_rag
```

---

## 6. 验证 + 健康检查

```bash
# 1) 服务健康
curl -sf http://localhost/nginx-health
# → ok

curl -sf http://localhost/api/v1/health
# → {"status":"ok"}

# 2) 容器健康状态
docker-compose -f docker-compose.prod.yml ps
# 期望所有 service 状态 = (healthy)

# 3) 数据库连接
docker-compose -f docker-compose.prod.yml exec backend \
  python -c "import asyncio; from sqlalchemy import text; \
  from app.db.session import async_session; \
  async def m(): async with async_session() as s: \
    print('version:', (await s.execute(text('SELECT VERSION()'))).scalar()) \
  asyncio.run(m())"

# 4) 端到端登录
curl -X POST http://localhost/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"${DEFAULT_ADMIN_USERNAME}\",\"password\":\"${DEFAULT_ADMIN_PASSWORD}\"}"
```

---

## 7. 运维

### 7.1 日志

```bash
# 所有服务
docker-compose -f docker-compose.prod.yml logs -f

# 单个服务
docker-compose -f docker-compose.prod.yml logs -f backend --tail=100

# 写文件（用 logrotate）
docker-compose -f docker-compose.prod.yml logs -f backend 2>&1 | tee /var/log/fithub/backend.log
```

### 7.2 数据库备份（cron）

```bash
# /etc/cron.daily/fithub-backup
#!/bin/bash
set -e
BACKUP_DIR=/opt/fithub/backups/$(date +%Y%m%d)
mkdir -p "$BACKUP_DIR"
docker-compose -f /opt/fithub/docker-compose.prod.yml exec -T mysql \
  mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" fithub | gzip > "$BACKUP_DIR/fithub-$(date +%H%M).sql.gz"
# 保留 14 天
find /opt/fithub/backups -type d -mtime +14 -exec rm -rf {} +
```

### 7.3 升级

```bash
# 1) 备份（见 7.2）
# 2) 拉新代码
git pull
# 3) 重新构建（仅 backend 改动时）
docker-compose -f docker-compose.prod.yml --env-file .env.prod build backend
# 4) 重启 + 跑迁移
docker-compose -f docker-compose.prod.yml --env-file .env.prod up -d
docker-compose -f docker-compose.prod.yml exec backend alembic upgrade head
```

### 7.4 监控建议

| 指标 | 工具 | 阈值 |
|---|---|---|
| 容器 CPU/内存 | cAdvisor + Prometheus | CPU > 80% / 内存 > 90% 持续 5min |
| MySQL 连接 | mysqld_exporter | `Threads_connected` > 100 |
| LLM 调用 | `ai_call_logs` 表 | 单分钟失败 > 10 |
| 后端 p95 | nginx access log 解析 | p95 > 500ms 持续 10min |

---

## 8. 回滚

```bash
# 1) 停当前版本
docker-compose -f docker-compose.prod.yml down

# 2) 切回上一版本（git tag 标记）
cd /opt/fithub
git checkout v1.0.0   # 假设的上一稳定版 tag

# 3) 重建 + 启动
docker-compose -f docker-compose.prod.yml --env-file .env.prod build
docker-compose -f docker-compose.prod.yml --env-file .env.prod up -d

# 4) 数据库回滚（如迁移是 DML，0017 等不可逆；DDL 可 downgrade）
docker-compose -f docker-compose.prod.yml exec backend alembic downgrade -1
```

**不可逆迁移**（如 M12 0017_drop_cs_legacy）：只能从迁移前 mysqldump 恢复。

---

## 9. 故障排查

| 症状 | 可能原因 | 修法 |
|---|---|---|
| `backend` 一直 restarting | `JWT_SECRET` 仍是占位 / 密码是默认值 | 改 `.env.prod` 重启 |
| `backend` 连不上 mysql | DSN 错 / MySQL 未就绪 | 等 healthcheck 通过；检查 `MYSQL_DSN` |
| 502 Bad Gateway | backend 崩了 / workers 死 | `logs backend` 看堆栈 |
| SSE 流断 | nginx buffering | 已在 `nginx.conf` 设 `proxy_buffering off` |
| 中文乱码 | DB collation 不是 utf8mb4 | `SHOW VARIABLES LIKE 'collation%';` |
| 慢查询 | 缺索引 | 跑 `EXPLAIN` 定位；对照 `数据库使用.md §6.1` |

---

## 📌 速查

```bash
# 第一次部署
cp .env.prod.template .env.prod   # 改完所有占位
mkdir -p /opt/fithub/data && cd /opt/fithub/data
git clone https://github.com/wangmuerxiao/exercises-dataset-zh.git
cd /opt/fithub
docker-compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
sleep 30
docker-compose -f docker-compose.prod.yml exec backend alembic upgrade head
docker-compose -f docker-compose.prod.yml exec backend python -m app.db.create_default_admin
docker-compose -f docker-compose.prod.yml exec backend python -m app.db.seed_exercises

# 日常运维
docker-compose -f docker-compose.prod.yml ps
docker-compose -f docker-compose.prod.yml logs -f backend --tail=100
```

> 生产安全检查清单见 [SECURITY.md](./SECURITY.md)（13 节必读）。
