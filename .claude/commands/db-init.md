---
description: 初始化/重置 FitHub MySQL 数据库，包括建库、迁移、动作数据导入和默认账号创建
argument-hint: [--reset] [--skip-seed]
allowed-tools: Bash, Read, Glob, Grep
---

# 数据库初始化命令

执行 FitHub 项目的 MySQL 数据库初始化流程。

## 步骤

### 1. 检查 MySQL 是否运行

```bash
# Windows / Git Bash
docker ps | grep fithub-mysql || echo "MYSQL_NOT_RUNNING"

# 或者检查端口
netstat -an | grep 3306 || echo "PORT_3306_NOT_LISTENING"
```

如果未运行：
- 提示用户使用 Docker 启动（参见 `数据库使用.md` §本地启动 MySQL）
- 或者让用户手动启动 MySQL 服务

### 2. 检查 .env 配置

读取 `backend/.env`，确认以下变量存在：
- `MYSQL_DSN` 或 `MYSQL_HOST/PORT/USER/PASSWORD/DB`
- `OPENAI_API_KEY`（可选，AI 功能相关）

### 3. 创建数据库（如不存在）

```bash
mysql -h ${MYSQL_HOST:-localhost} -P ${MYSQL_PORT:-3306} \
  -u ${MYSQL_USER:-root} -p${MYSQL_PASSWORD} \
  -e "CREATE DATABASE IF NOT EXISTS fithub CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

### 4. 应用 alembic 迁移

```bash
cd backend
alembic current             # 查看当前版本
alembic upgrade head        # 应用最新迁移
```

如果用户传入了 `--reset` 参数：
```bash
alembic downgrade base      # 回滚到初始
alembic upgrade head        # 重新应用
```

### 5. 导入动作数据

```bash
# 检查数据集是否存在
ls ../data/exercises-dataset-zh/data/exercises.json || {
  echo "❌ 数据集缺失，请先执行："
  echo "   cd data && git clone https://github.com/wangmuerxiao/exercises-dataset-zh.git"
  exit 1
}

# 导入
python -m app.db.seed_exercises
```

如果用户传入了 `--skip-seed`，跳过此步。

### 6. 创建默认管理员账号（仅当 users 表为空）

```bash
python -m app.db.create_default_admin \
  --username admin \
  --password admin123 \
  --email admin@fithub.local
```

提示用户：默认账号密码 `admin/admin123`，**首次登录后必须修改**。

### 7. 验证

执行以下 SQL 确认：

```sql
SELECT COUNT(*) AS exercise_count FROM exercises;
SELECT COUNT(*) AS user_count FROM users;
SELECT version_num FROM alembic_version;
```

预期结果：
- `exercise_count = 1324`
- `user_count ≥ 1`（管理员）
- `version_num` 是最新迁移版本

## 输出

完成后输出汇总报告：

```
✅ 数据库初始化完成
   - 数据库：fithub @ ${MYSQL_HOST}:3306
   - 迁移版本：${version_num}
   - 动作数量：${exercise_count}
   - 用户数量：${user_count}（含 1 个管理员）
   
📌 默认管理员账号：admin / admin123（请登录后修改）
🚀 启动后端：cd backend && uvicorn app.main:app --reload
```

## 常见错误处理

| 错误 | 原因 | 解决 |
|---|---|---|
| `Access denied for user` | 密码错误 | 检查 `.env` 的 MYSQL_PASSWORD |
| `Unknown database 'fithub'` | 数据库未创建 | 回到步骤 3 |
| `Can't connect to MySQL server` | MySQL 未运行 | 启动 Docker 容器或服务 |
| `exercises.json not found` | 数据集缺失 | `cd data && git clone ...` |
| `alembic: command not found` | 依赖缺失 | `pip install alembic` |
| `permission denied` on file | 文件权限 | Windows 一般不会出现，Linux/Mac 用 `chmod` |

## 不做的事

- ❌ 不修改数据库字符集（必须 utf8mb4）
- ❌ 不修改 collation（必须 utf8mb4_unicode_ci）
- ❌ 不删除已有 users 表数据（除非 --reset 且用户明确确认）
- ❌ 不在生产环境执行（脚本开头会检测 `APP_ENV` 环境变量）