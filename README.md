# FitHub 健身管理系统

> 一款面向健身爱好者与运营团队的 C 端 + B 端一体化健身管理系统。
> 1,324 个健身动作库 + 198 个谭师库（教练原创）· AI 健身教练（OpenAI 协议）· 两级 B 端权限（管理员/教练）
> 训练计划：三分化（3 天）/ 四分化（4 天）预设 · 饮食原理：克数计算 + 5 个原片嵌入

## 📋 文档导航

| 文档 | 说明 |
|---|---|
| [SECURITY.md](./SECURITY.md) | 生产部署前安全自检清单（13 节） |
| [.claude/CLAUDE.md](./.claude/CLAUDE.md) | Claude 协作时的项目级指令（含技术栈锁定、工作约定） |
| [.claude/agents/backend-dev.md](./.claude/agents/backend-dev.md) | 后端开发专属 agent |
| [.claude/commands/db-init.md](./.claude/commands/db-init.md) | 数据库初始化 slash command |
| [backend/tests/perf/README.md](./backend/tests/perf/README.md) | Locust 性能测试指南 + 当前基线 |
| [`数据库使用.md`](./数据库使用.md) | MySQL 日常使用手册（启动 + alembic + 排错 + 17 迁移清单） |
| [`deploy.md`](./deploy.md) | 生产部署指南（docker-compose.prod.yml + .env.prod + 备份 / 回滚） |

### 📊 项目状态

| 指标 | 数字 |
|---|---|
| alembic 迁移 | 17（head 0017） |
| 后端路由文件 | 21（`app/api/v1/`） |
| 前端页面 | 28（`web/c` + `web/admin`） |
| 单测覆盖 | 385/385 通过（17 文件） |
| 角色 | 3（`user` / `trainer` / `admin`） |
| 里程碑 | M1~M7 基本完成，M8（测试 + 上线）进行中 |

---

## 🎯 产品定位

### C 端（用户侧）
- 浏览 1,324 个健身动作（含中文名、GIF 演示、10 语言步骤说明）
- 浏览 **198 个谭师库动作**（教练原创：分类筛选 + 训练计划 + 饮食专题）
- 创建训练计划（手动 / AI 生成 / 教练模板 · 含三分化 / 四分化预设）
- 与 AI 健身教练对话（问答 / 计划 / 动作替代 / 饮食建议）
- 饮食原理与计算（克数计算器 + 谭成义饮食原理 + 5 个嵌入原片）
- 动作评论打分、训练打卡、个人中心

### B 端（管理侧）— **两级角色**
- **管理员（`admin`）**：会员管理、教练账号、模板审核、数据看板、系统配置、操作日志、链路追踪
- **教练（`trainer`）**：发布计划模板、模板审核、专业训练咨询（队列接管，**兼原客服** M4 合并）
- **普通用户（`user`）**：C 端全功能

> 角色定义见 `app/db/models/user.py`（`User.role` 枚举），RBAC 在路由层用 `Depends(require_role(...))` 校验。

---

## 🛠️ 技术栈

### 存储架构（三层）

| 层 | 存储 | 用途 |
|---|---|---|
| **结构化** | MySQL 8 | 用户、训练计划、全量会话历史、知识库台账、系统配置 |
| **向量层** | Chroma（嵌入式） | 子块向量（RAG 检索，零部署，Windows 友好） |
| **缓存层** | Redis | 最近 5 轮短期会话缓存，加速 AI 响应 |

### 应用栈

| 层 | 选型 |
|---|---|
| 前端 | 纯 HTML + CSS + 原生 JS（无构建步骤） |
| 后端 | Python 3.11+ / FastAPI |
| 数据库 | MySQL 8 + SQLAlchemy 2.x（async）+ Alembic 迁移 |
| 向量库 | Chroma（chromadb ≥ 0.5，嵌入式模式，数据落 `./data/chroma/`） |
| 缓存 | Redis（redis-py ≥ 5.0，async） |
| 鉴权 | JWT（Access 2h + Refresh 7d，HS256） |
| LLM | OpenAI 兼容协议（GPT-4o / GPT-4o-mini / DeepSeek / Qwen 等） |
| 限流 | slowapi（全局 60/分钟 + AI 5/分钟 + 50/天·每用户） |
| 日志 | loguru + 链路追踪（RequestIdMiddleware → trace_spans 表） |
| 数据源 | [wangmuerxiao/exercises-dataset-zh](https://github.com/wangmuerxiao/exercises-dataset-zh) |

### 数据流（AI 对话场景）

```
用户消息 → Redis 取最近 5 轮上下文 → 拼接 Prompt
   ↓
   ├─ MySQL：拉取用户画像、计划、长期会话摘要
   └─ Chroma：用当前问题检索 Top-K 相似动作子块
   ↓
LLM（OpenAI 协议）→ 流式响应（SSE）
   ↓
   ├─ Redis：追加本轮到短期缓存
   ├─ MySQL：持久化完整会话 + 摘要 + ai_call_logs（tokens/cost/latency）
   └─ trace_spans：写入全链路 span
```

---

## 📁 目录结构

```
/健身管理
├── README.md                # 本文件
├── SECURITY.md              # 生产部署前安全自检清单
├── 健身房最全详细知识问答手册（新手通用版）.md   # 业务知识库种子文档
│
├── /web                     # 前端（HTML + CSS + JS，无构建）
│   ├── /c                   # C 端
│   │   ├── /pages           # 页面（index / detail / plans / plan-create / plan-detail
│   │   │                    #         templates / template-detail / login / register / chat
│   │   │                    #         tan-library / tan-plan / tan-diet / tan-diet-topic 谭师库）
│   │   ├── /js              # 脚本（api / app / banner / reviews / chat-tab / translations）
│   │   ├── /css             # 样式（style / reviews）
│   │   └── favicon.svg
│   ├── /admin               # B 端
│   │   ├── /pages           # index / login / workbench / dashboard / users / templates
│   │   │                    # reviews / banners / system-config / operation-logs
│   │   │                    # knowledge-base / traces
│   │   ├── /js              # admin-layout / queue / trainer-queue / banners-admin / reviews-admin
│   │   └── /css             # soft-ui / queue / reviews-admin
│   └── /shared              # 共享静态资源
│
├── /backend                 # FastAPI 后端
│   ├── /app
│   │   ├── /api             # 路由
│   │   │   ├── deps.py      # 依赖注入（DB session / 当前用户 / RBAC）
│   │   │   └── /v1          # 业务路由（20 个文件，详见下方「API 路由总览」）
│   │   ├── /core            # 配置（config）、安全（security）、JWT、日志、链路追踪
│   │   ├── /middleware      # RequestIdMiddleware（全链路追踪入口）
│   │   ├── /db              # SQLAlchemy session、models、seed 脚本
│   │   │   └── /models      # 16 个 ORM 模型（详见下方「数据模型」）
│   │   ├── /schemas         # Pydantic schemas（按模块分文件）
│   │   ├── /services        # 业务逻辑（LLM / RAG / KB / Embedding / Tracing / OperationLog）
│   │   └── main.py          # 应用工厂 + 单端口托管前端 + 静态资源挂载
│   ├── /alembic             # 数据库迁移（14 个版本：0001~0014，含一个 hotfix 0008）
│   ├── /data                # 后端运行时数据
│   │   ├── /chroma          # Chroma 向量库持久化目录
│   │   └── /uploads         # 用户上传文件
│   ├── /tests
│   │   └── /perf            # Locust 性能测试（locustfile.py + README.md）
│   ├── requirements.txt
│   ├── .env.example
│   └── Dockerfile
│
├── /data                    # 原始数据集（git clone 进来，路径可能嵌套）
│   └── /exercises-dataset-zh-master          # 注意：实际目录名带 -master
│       └── /exercises-dataset-zh-master      # 且可能是双重嵌套（zip 解压所致）
│           ├── data/exercises.json
│           ├── data/name_zh.json
│           ├── images/
│           └── videos/
│
├── /nginx.conf              # 反代配置（docker-compose 中挂到前端容器）
├── /docker-compose.yml      # 一键启动（profile: default / full / tools）
├── /.claude                 # Claude 协作配置
│   ├── CLAUDE.md
│   ├── settings.local.json
│   ├── /agents
│   └── /commands
└── /.dockerignore, .gitignore
```

> **数据路径说明**：`main.py` 启动时会按候选顺序自动探测数据集目录（`EXERCISES_DATA_DIR` → `data/exercises-dataset-zh` → `data/exercises-dataset-zh-master/exercises-dataset-zh-master` → `data/exercises-dataset-zh-master`），命中 `images/` + `videos/` 同时存在的目录即挂载到 `/static/images` 和 `/static/videos`。

---

## 🚀 快速启动（单端口，前后端统一入口）

> **设计要点**：所有访问都通过 **同一个端口**（默认 8000）。
> 前端 C 端、B 端、后端 API 都挂在同一个 uvicorn 进程里。
>
> | 路径 | 入口 |
> |---|---|
> | `/` | 自动重定向到 `/c/` |
> | `/portal` | 入口选择页（C 端 / B 端 卡片） |
> | `/c/` | C 端首页（动作库） |
> | `/c/login.html`、`/c/register.html`、`/c/detail.html?id=0001` | C 端各页面 |
> | `/admin/` | B 端首页 |
> | `/admin/login.html` | B 端登录 |
> | `/api/v1/...` | 后端 API |
> | `/docs` | Swagger UI |
> | `/static/images`、`/static/videos` | 动作 GIF / 缩略图（如数据集已挂载） |

### 0. 准备数据集

```bash
mkdir -p data && cd data
git clone https://github.com/wangmuerxiao/exercises-dataset-zh.git
# 实际克隆下来的目录名是 exercises-dataset-zh-master（GitHub 默认）
```

### 1. 启动 MySQL

参见 [SECURITY.md §4](./SECURITY.md) 的 MySQL 加固清单。

```bash
# Docker 方式（推荐）
docker run -d --name fithub-mysql \
  -e MYSQL_ROOT_PASSWORD=rootpass \
  -e MYSQL_DATABASE=fithub \
  -p 3306:3306 \
  mysql:8.0 --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci
```

### 2. 启动后端（同时托管前端）

#### 方式 A：conda（推荐，miniconda / anaconda 用户）

```bash
# 创建独立环境（一次性）
conda create -n fithub python=3.11 -y

# 激活（PowerShell / cmd）
conda activate fithub
# Git Bash 用全路径：
#   /c/Users/<你>/miniconda3/envs/fithub/python.exe -m uvicorn ...

cd backend
pip install -r requirements.txt

# 复制环境变量
cp .env.example .env
# 编辑 .env，填入 MySQL 连接串、LLM API Key、JWT_SECRET 等
#   MYSQL_DSN=mysql+aiomysql://root:Lb403706@localhost:3306/fithub?charset=utf8mb4
#   JWT_SECRET=$(openssl rand -hex 32)
#   LLM_API_KEY=sk-xxx

# 数据库迁移 + 数据导入
alembic upgrade head
python -m app.db.seed_exercises     # 导入 1,324 个动作（幂等）
python -m app.db.seed_cs            # 创建测试用教练账号（兼原客服，可选）
python -m app.db.seed_rag           # 初始化 Chroma 向量库（M3 需要）
python -m app.db.create_default_admin   # 创建默认管理员 admin/admin123（仅当 users 表为空）
# 可选：python -m app.db.backfill_ai_cost   # 历史 AI 成本回填

# 启动（单端口）
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

> 镜像加速：若 `pip install` 慢或 404，可显式指定清华源或官方源：
> ```bash
> pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
> # 或
> pip install -r requirements.txt -i https://pypi.org/simple
> ```

#### 方式 B：venv（系统 Python 用户）

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

> conda 用户的常见坑：`python -m venv .venv` 会失败（conda 自带的 venv 模块复制 `venvlauncher.exe` 报错）。**conda 用户走方式 A**，别用 venv。

> **⚠️ Windows PowerShell 提示**：如果 `pip install` 报 `UnicodeDecodeError: 'gbk' codec can't decode...`，是 PowerShell 默认 GBK 编码读 requirements.txt 失败。解决方案（任选其一）：
>
> ```powershell
> # 方案 1：临时设置环境变量
> $env:PYTHONUTF8=1
> pip install -r requirements.txt
>
> # 方案 2：永久设置（推荐，所有 Python 项目受益）
> [System.Environment]::SetEnvironmentVariable("PYTHONUTF8", "1", "User")
>
> # 方案 3：用 cmd 替代 PowerShell
> cmd /c "pip install -r requirements.txt"
> ```
>
> requirements.txt 已全部改为英文注释，避免此问题再次发生。
>
> **⚠️ Chroma 0.6.x 已知 bug**：若 B 端知识库上传文档后状态变成 `failed`、错误信息为 `"'_type'"`，是 `chromadb==0.6.3` 的配置迁移 bug（`chromadb/api/configuration.py:from_json` 缺 `_type` 字段）。修复：停服务后清空 `backend/data/chroma/` 整个目录再重启，让 chroma 重建 collection（新建 config 字段齐全）。
> ```bash
> # Windows PowerShell
> Stop-Process -Name python -Force   # 或在任务管理器里结束 uvicorn
> Remove-Item -Recurse -Force backend/data/chroma/*
> uvicorn app.main:app --reload --port 8000
> ```
> 长期方案：把 `requirements.txt` 中 `chromadb` 锁到 `<0.6.0`（如 `==0.5.23`），等 chromadb 上游修 bug 后再放开。

### 3. 访问

打开浏览器：

- **入口选择页**：http://localhost:8000/portal
- **C 端**：http://localhost:8000/c/
- **B 端**：http://localhost:8000/admin/
- **API 文档**：http://localhost:8000/docs
- **健康检查**：http://localhost:8000/api/v1/health

默认管理员：`admin / admin123`（首次登录后立即修改）。

### 备选：Docker Compose 启动（生产环境风格）

```bash
cd 项目根目录
docker-compose up -d
```

启动后访问 http://localhost:8080（nginx 反代到后端 8000）。
- C 端：http://localhost:8080/c/
- B 端：http://localhost:8080/admin/
- API：http://localhost:8080/api/v1/

### Redis 部署

**M1-M3 阶段**不强制启动 Redis（短会话上下文走 MySQL 兜底）。M4+ 阶段（AI 助手大规模上线）必须：

```bash
# 启动 Redis（Docker 方式）
docker run -d --name fithub-redis -p 6379:6379 redis:7-alpine
```

`.env` 配置：
```env
REDIS_URL=redis://localhost:6379/0
REDIS_SESSION_CACHE_ROUNDS=5
REDIS_SESSION_TTL_SECONDS=3600
```

docker-compose 一键：`docker-compose --profile full up -d`（同时拉起 Redis + Milvus Standalone，仅当你显式切到独立 Milvus 时才用到）。

### Chroma 向量库

向量库**始终随 backend 进程启动**（嵌入式，零部署）：

```env
# .env
CHROMA_PERSIST_DIR=./data/chroma       # 数据持久化目录
```

数据落到 `./data/chroma/`（已加进 `.gitignore`）。首次跑 `python -m app.db.seed_rag` 会把动作子块 embedding 后写入；之后 RAG 检索即用。

> **Windows 友好**：Chroma 嵌入式模式在 Windows 上原生支持（不像 Milvus Lite 仅支持 Linux/macOS），是 Windows 用户的首选。
> 若要切到独立向量库服务，可改用 Milvus Standalone（docker-compose profile=full）或 Qdrant，但需自行实现适配器。

### 父块/子块策略（RAG 文档分块）

每个动作的 10 语言步骤说明会被切分为：

- **父块（parent chunk）**：完整动作的某个语言完整说明 → 存 MySQL（`exercises.instructions`）
- **子块（child chunk）**：每一步动作 → 单独成块 → 嵌入向量 → 存 Chroma

检索时按子块相似度匹配，命中后**回溯父块**返回完整说明。这样检索粒度细、回答粒度粗。

---

## 🔑 关键决策（D1~D10）

详见 [prd.md §6](./prd.md)：

| # | 决策 | 选择 |
|---|---|---|
| D1 | C 端登录 | JWT + 账号密码，预留扩展 |
| D2 | 角色 | **3 个**：`user` / `trainer` / `admin`（M12 迁移后 DB 已清理 `customer_service`） |
| D3 | LLM 功能 | 问答 + 计划 + 替代 + 饮食 |
| D4 | 技术栈 | FastAPI + MySQL + Chroma，前端 HTML/CSS/JS |
| D5 | 动作数据源 | wangmuerxiao/exercises-dataset-zh |
| D6 | 付费会员 | MVP 不实现，预留扩展 |
| D7 | 动作社区化 | 允许评论 + 1-5 星打分 |
| D8 | AI 兜底 | RAG 检索相似动作重生成 |
| D9 | 客服排班 | 不需要 |
| D10 | 国际化 | 仅中文 |

---

## 📚 数据模型（16 张表）

> 表结构详见 `backend/app/db/models/` 和 `backend/alembic/versions/`（14 个迁移文件）。所有表都有 `created_at` / `updated_at`，所有外键都建了索引。

| # | 表 | 模型文件 | 用途 |
|---|---|---|---|
| 1 | `users` | `user.py` | C/B 端账号（`role` 3 枚举：`user` / `trainer` / `admin`） |
| 2 | `exercises` | `exercise.py` | 1,324 个动作主数据（含 10 语言 `instructions`） |
| 3 | `exercise_reviews` | `exercise_review.py` | 动作评论 + 1-5 星打分（M6） |
| 4 | `plans` | `plan.py` | 用户训练计划（含 `weeks` JSON） |
| 5 | `training_records` | `training_record.py` | 训练打卡记录 |
| 6 | `plan_templates` | `plan_template.py` | 教练发布的计划模板（市场 + 审核流） |
| 7 | `conversations` | `conversation.py` | AI/人工会话聚合（`assigned_trainer_id` 字段） |
| 8 | `messages` | `message.py` | 会话消息流（user / assistant / trainer / cs） |
| 9 | `system_configs` | `system_config.py` | 系统配置 KV（限流、模型名、提示词模板） |
| 10 | `ai_call_logs` | `ai_call_log.py` | 每次 LLM 调用记录（tokens / cost_cny / latency / intent） |
| 11 | `operation_logs` | `operation_log.py` | B 端写操作审计（`operator` / `action` / `target_type` / `target_id`） |
| 12 | `banners` | `banner.py` | C 端公告 + B 端公告管理 |
| 13 | `trace_spans` | `trace_span.py` | 全链路追踪 span（与 RequestIdMiddleware 联动） |
| 14 | `knowledge_base` | `knowledge_base.py` | RAG 知识库台账（标题/来源/状态） |
| 15 | `knowledge_documents` | `knowledge_document.py` | 知识库文档子块（向量 + 原文） |
| 16 | `alembic_version` | — | Alembic 版本号 |

> 业务知识种子见仓库根的 `健身房最全详细知识问答手册（新手通用版）.md`（用于知识库初始化）。

---

## 🧩 后端 API 路由总览

> 路由文件均在 `backend/app/api/v1/`，聚合入口 `__init__.py`。所有路由默认带 `/api/v1` 前缀。

| 路径前缀 | 文件 | 角色 | 功能 |
|---|---|---|---|
| `/health` | `health.py` | 公开 | 健康检查 |
| `/auth` | `auth.py` | 公开 | 登录 / 注册 / 刷新 token |
| `/users` | `users.py` | user | 当前用户 CRUD、个人中心 |
| `/exercises` | `exercises.py` | user | 动作列表（分页/筛选）、详情、filters 聚合 |
| `/reviews` | `reviews.py` | user | 动作评论 + 打分 |
| `/plans` | `plans.py` | user | 训练计划 CRUD + 打卡 |
| `/plan-templates` | `plan_templates.py` | user | C 端模板市场 + 采用 |
| `/trainer` | `trainer.py` | trainer | 教练工作台：模板 CRUD + 会话队列 |
| `/chat` | `chat.py` | user | AI 对话（4 场景：问答/计划/替代/饮食，SSE 流式） |
| `/admin` | `admin.py` | admin | 系统配置 |
| `/admin` | `admin_member.py` | admin | 会员管理 |
| `/admin` | `admin_dashboard.py` | admin | 数据看板（overview / ai-cost / user-trend / chat-metrics） |
| `/admin` | `admin_templates.py` | admin | 模板审核队列（approve / reject / offline） |
| `/admin` | `admin_log.py` | admin | 操作日志查询 |
| `/admin` | `admin_trace.py` | admin | 链路追踪查询 |
| `/admin/knowledge-bases` | `admin_knowledge_base.py` (admin) | admin | RAG 知识库 CRUD |
| `/admin/knowledge-bases/{kb_id}/documents/{doc_id}/chunks` | `admin_knowledge_base.py` (admin) | admin | **查看文档的所有分片原文（调试可视化）** |
| `/admin/knowledge-bases/{kb_id}/retrieval-test` | `admin_knowledge_base.py` (admin) | admin | KB 检索测试 |
| `/banners` | `admin_banner.py` (public) | 公开 | C 端公告 |
| `/admin/banners` | `admin_banner.py` (admin) | admin | 公告管理 |
| `/tan-actions` | `tan_actions.py` (public) | 公开 | 谭师库：198 个教练动作（筛选 / 详情 / meta） |
| `/tan-plans` | `tan_plans.py` (public) | 公开 | 训练计划：三分化 / 四分化 |
| `/tan-diet` | `tan_diet.py` (public) | 公开 | 饮食专题：5 个视频列表 + 详情 |
| `/static/images`、 `/static/videos` | `main.py` | 公开 | 动作 GIF / 缩略图（数据集直挂） |

> 完整 schema：`http://localhost:8000/docs`（Swagger UI）或 `/openapi.json`。

---

## 🖥️ 前端页面索引

### C 端（`web/c/`，挂在 `/c/`）

| 页面 | 文件 | 说明 |
|---|---|---|
| 首页 | `index.html` | 动作库浏览 + 筛选 |
| 动作详情 | `detail.html?id=0001` | 单动作 GIF + 步骤说明 |
| 谭师库 | `tan-library.html` | 198 个教练动作 + 分类筛选 + 训练计划入口 + 饮食专题 |
| 谭师库指南 | `tan-guide.html` | 谭师库使用引导（首次访问提示） |
| 训练计划详情 | `tan-plan.html?name=三分化` | 教练训练计划（三/四分化）按天分组：热身 + 正式训练 |
| 饮食原理与计算 | `tan-diet.html` | 每日克数计算器 + 谭成义饮食原理 + 5 个嵌入视频 |
| 饮食专题详情 | `tan-diet-topic.html?id=xxx` | 单个饮食视频 + 关联动作 |
| 模板市场 | `templates.html` | 浏览教练发布的计划模板 |
| 模板详情 | `template-detail.html` | 模板预览 + 采用 |
| 训练计划 | `plans.html` | 计划列表 |
| 创建计划 | `plan-create.html` | 手动 / AI 生成 / 模板采用 |
| 计划详情 | `plan-detail.html` | 计划执行 + 打卡 |
| 登录 | `login.html` | JWT 登录 |
| 注册 | `register.html` | 账号注册 |
| AI 聊天 | `chat.html` | AI 教练对话入口 |

### B 端（`web/admin/`，挂在 `/admin/`）

| 页面 | 文件 | 角色 | 说明 |
|---|---|---|---|
| 入口 | `index.html` | 公开 | B 端首页 |
| 登录 | `login.html` | 公开 | B 端登录（按角色路由） |
| 工作台 | `workbench.html` | 全部 B 端 | 角色感知的快捷入口 |
| 数据看板 | `dashboard.html` | admin | overview / AI 成本 / 用户趋势 |
| 会员管理 | `users.html` | admin | C 端用户 CRUD + 禁用 |
| 模板审核 | `templates.html` | admin / trainer | 模板队列审核 |
| 动作评论管理 | `reviews.html` | admin | 评论审核 / 删除 |
| 公告管理 | `banners.html` | admin | 公告发布 + 上下线 |
| 系统配置 | `system-config.html` | admin | 全局配置 |
| 操作日志 | `operation-logs.html` | admin | `operation_logs` 查询 |
| 知识库 | `knowledge-base.html` | admin | RAG 知识库管理（含文档分片可视化 ✂️） |
| 链路追踪 | `traces.html` | admin | `trace_spans` 查询（RequestId 串联） |
| 会话工作台 | `workbench.html` + `trainer-queue.js` | trainer / admin | 教练人工会话接管（兼原客服） |

---

## 🗄️ 数据导入与回填脚本

均在 `backend/app/db/` 下，独立可执行：

| 脚本 | 用途 | 何时跑 |
|---|---|---|
| `seed_exercises.py` | 从 `data/exercises-dataset-zh-master/data/exercises.json` 导入 1,324 个动作到 MySQL | 首次部署 |
| `tan_plans.py` | 扫描 `actions_full.json` 的 `training_profile.arrangements` 自动构建三分化 / 四分化计划数据 | 首次部署 / 更新谭师库后 |
| `seed_rag.py` | 把动作子块 embedding 后写入 Chroma | 首次部署 / 数据集更新后 |
| `seed_cs.py` | 创建教练测试账号（兼原客服，参数 `--users "name:pass"`） | 压测 / 测试 |
| `create_default_admin.py` | 创建默认管理员（仅当 `users` 表为空时生效） | 首次部署 |
| `backfill_ai_cost.py` | 给历史 `ai_call_logs` 回填 `cost_cny` | 升级计价模型后 |

---

## 🧪 测试

**181 个测试**（不含 perf/ 下的 Locust），覆盖核心模块：

```
backend/tests/
├── conftest.py                      # 共享 fixtures（autouse + MySQL 集成）
├── test_kb_service_pure.py          # 编码 / 分片 / context 格式化（19）
├── test_kb_service_chroma.py        # Chroma 嵌入式集成（11）
├── test_chat_pure.py                # intent / rewrite / template 映射（32）
├── test_chat_metrics.py             # SSE 实时指标（12）
├── test_chat_integration.py         # mock LLM + DB 端到端（14）
├── test_auth.py                     # 注册 / 登录 / 刷新 / JWT / bcrypt（67）
├── test_plans.py                    # 计划 CRUD + 打卡 + 进度统计（20）
├── test_integration_mysql.py        # 真 MySQL（5，需要本地 MySQL，否则 skip）
└── perf/
    ├── locustfile.py                # Locust 压测脚本
    └── README.md
```

### 运行

```bash
cd backend
# 装一次
pip install pytest pytest-asyncio pytest-cov -i https://pypi.org/simple

# 全跑（默认跳过 integration，因为需要 MySQL）
pytest                         # ≈11s
pytest -v                       # 详细模式
pytest -q                       # 安静模式

# 跑某个文件
pytest tests/test_auth.py -v

# 跑某个测试
pytest tests/test_auth.py::TestJwt::test_access_token_exp_2h

# 跑带覆盖度
pytest --cov=app.services.kb_service --cov-report=term-missing

# 跑集成测试（需要 MySQL）
pytest tests/test_integration_mysql.py -v
# MySQL 不可达会自动 skip，不会报错
```

### 集成测试（MySQL）

`test_integration_mysql.py` 用真 MySQL 跑真实写库：

- 探测 `localhost:3306` 是否在线，不可达则 `pytest.skip`
- 自动 `CREATE DATABASE IF NOT EXISTS fithub_test`
- 用 `Base.metadata.create_all` 同步 schema（比 alembic 快）
- 嵌套事务 + 测试结束 `rollback`，**不污染 fithub_test**

不需要 testcontainers，本机 MySQL 即可。CI 上需要起一个 MySQL service container。

### Markers

```ini
[pytest]
markers =
    integration: 需要 MySQL / Chroma
    slow: 跑得慢（>5s）
```

```bash
pytest -m "not integration"           # 跳过集成测试（CI 默认）
pytest -m integration                 # 只跑集成测试
pytest -m "integration and not slow"  # 跑集成但跳慢的
```

### pytest.ini 关键配置

```ini
[pytest]
asyncio_mode = auto                     # 自动识别 async 测试
asyncio_default_fixture_loop_scope = function   # 关键：fixture 和 test 用同一 loop
asyncio_default_test_loop_scope = function      # 否则会触发 "Task attached to different loop"
testpaths = tests
addopts = -v --tb=short --strict-markers
```

### conftest.py Fixtures

- `cleanup_test_kb`（autouse）：每个测试前后清 `kb_9999` collection，避免跨测试数据污染
- `mock_embed`：用 md5 hash 生成确定性 fake embedding，不调真 LLM
- `mysql_available`（session）：探测 MySQL 是否在线
- `integration_db_url`：把生产 DSN 的 db 名换成 `fithub_test`
- `bootstrap_test_db`：确保 `fithub_test` 库存在
- `integration_session`（async）：嵌套事务 session，测试结束 rollback

### CI 接入示例（GitHub Actions）

```yaml
- name: Tests
  run: |
    cd backend
    pip install -r requirements.txt
    pip install pytest pytest-asyncio pytest-cov
    pytest --cov=app --cov-report=xml -m "not integration"

- name: Integration Tests
  services:
    mysql:
      image: mysql:8.0
      env:
        MYSQL_ROOT_PASSWORD: rootpass
        MYSQL_DATABASE: fithub
      ports: ['3306:3306']
  run: pytest tests/test_integration_mysql.py -v
```

### Mock 技巧（auth / plans / chat 集成测试）

- **`AsyncMock` + `MagicMock`**：DB session 多步 execute 用 `side_effect` 链模拟返回
- **`_mock_session_create`**：`fake_refresh` 回填 id / created_at / updated_at（ORM 默认行为）
- **`LLMCallResult` dataclass**：直接构造（不是 OpenAI raw response 对象）

---

## 🚀 性能测试

工具：[Locust](https://locust.io/)。脚本在 `backend/tests/perf/locustfile.py`。

```bash
cd backend
.venv/Scripts/python.exe -m pip install locust

# 1) 启动被测服务
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8002

# 2) 浏览器压测
.venv/Scripts/python.exe -m locust -f tests/perf/locustfile.py --host=http://127.0.0.1:8002
# 打开 http://localhost:8089，填入 Users=50 / Spawn rate=10

# 3) 无界面压测
.venv/Scripts/python.exe -m locust -f tests/perf/locustfile.py \
    --host=http://127.0.0.1:8002 --headless -u 50 -r 10 -t 60s --csv=perf_report
```

覆盖 9/10 C 端用户 + 1/10 B 端管理员两类流量。**当前基线（2026-10-11，dev + 本机 MySQL，stdlib urllib × 50）**：

| 端点 | avg | p50 | p95 | p99 | max |
|---|---|---|---|---|---|
| `GET /exercises` | 29.8 | 28.5 | **47.9** | 63.0 | 63.0 ms |
| `GET /exercises/filters` | 15.0 | 15.4 | **28.5** | 35.8 | 35.8 ms |
| `GET /exercises/{id}` | 10.7 | 9.4 | **24.1** | 34.2 | 34.2 ms |
| `GET /plan-templates` | 16.7 | 17.3 | **27.5** | 35.2 | 35.2 ms |
| `GET /banners/active` | 11.9 | 13.2 | **21.5** | 26.3 | 26.3 ms |
| `GET /admin/knowledge-bases` | 23.5 | 24.0 | **42.4** | 46.6 | 46.6 ms |
| `GET /admin/dashboard/overview` | 24.1 | 22.9 | **47.3** | 48.2 | 48.2 ms |

全部 p95 < 50ms，远低于 200ms 阈值 ✅。

> Locust 安装慢（PyPI 同步慢）时可先用 stdlib 跑（无需装 locust）：
> ```bash
> PYTHONIOENCODING=utf-8 python tests/perf/locustfile.py
> ```
> 该脚本自带 `quick_benchmark()`，50 次 `GET /exercises?page=1&page_size=24`。

详见 [backend/tests/perf/README.md](./backend/tests/perf/README.md)（含阈值表、瓶颈分析、压测前必做事项）。

---

## 🛡️ 安全

部署前请通读 [SECURITY.md](./SECURITY.md)，关键条目：
- 生产模式启动校验（`config.py:reject_insecure_production_defaults`）：`APP_ENV=production` 但默认密钥 / 默认密码未改时**拒绝启动**
- bcrypt cost=12
- 全局限流 60/分钟/IP，AI 限流 5/分钟 + 50/天/用户
- 所有 B 端写操作记录到 `operation_logs`，所有 LLM 调用记录到 `ai_call_logs`
- HTTPS 反代配置示例、灰度发布 checklist、应急联系人模板

---

## 🛠️ Troubleshooting

开发 / 部署过程中踩过的坑和修复：

### 1. conda 用户用 `python -m venv .venv` 失败

**症状**：`Unable to copy 'C:\Users\xxx\miniconda3\Lib\venv\scripts\nt\venvlauncher.exe' to '.venv\Scripts\python.exe'`

**原因**：conda 自带的 `venv` 模块复制 launcher 失败（conda install 不全 / 杀毒拦截 / 权限）。

**解决**：conda 用户直接用 conda 建环境，**不要**用 venv：
```bash
conda create -n fithub python=3.11 -y
conda activate fithub    # PowerShell 里需要先 `conda init powershell`
pip install -r requirements.txt
```

### 2. Chroma 知识库上传后状态变 `failed`，错误信息 `"'_type'"`

**症状**：B 端「知识库」上传 .txt/.md 后，文档状态显示 `failed`，错误信息为 `"'_type'"`。

**原因**：`chromadb==0.6.3` 的 `_load_config_from_json_str_and_migrate` 是 buggy 的 —— 迁移后的 collection 配置 JSON 缺 `_type` 字段，触发 `KeyError: '_type'`。

**临时修复**：停服务 → 清空 chroma 数据目录 → 重启（让 chroma 重建 collection）：
```powershell
# 1. 停 uvicorn
Stop-Process -Name python -Force   # 或 Ctrl+C / 任务管理器
# 2. 清 chroma
Remove-Item -Recurse -Force backend\data\chroma\*
# 3. 重启
uvicorn app.main:app --reload --port 8000
```

**永久修复**：`requirements.txt` 已锁 `chromadb>=0.5.0,<0.6.0`（避开 0.6.x 的 bug），等上游修 bug 后再放开。

### 3. `pip install -r requirements.txt` 在 PowerShell 报 `UnicodeDecodeError: 'gbk' codec can't decode`

**原因**：PowerShell 默认 GBK 编码读 requirements.txt 失败。

**解决**：临时设 `PYTHONUTF8=1`：
```powershell
$env:PYTHONUTF8=1; pip install -r requirements.txt
```
`requirements.txt` 已全部改为英文注释，新装不会再触发。

### 4. 数据集目录是 `exercises-dataset-zh-master/...`（不是 README 写的 `exercises-dataset-zh/`）

**原因**：GitHub clone 默认加 `-master` 后缀；zip 解压可能产生双层嵌套。

**解决**：无需手动改名。`backend/app/main.py` 启动时会按候选顺序自动探测（`EXERCISES_DATA_DIR` → `data/exercises-dataset-zh` → `data/exercises-dataset-zh-master/exercises-dataset-zh-master` → `data/exercises-dataset-zh-master`），命中 `images/` + `videos/` 即挂载。

### 5. SSE 流式响应客户端断连已自动取消上游 LLM

**症状**（修复前）：浏览器关掉页面后，后端 chat task 还在跑、LLM 账单继续计费。

**修复**（v1.1）：`backend/app/api/v1/chat.py` 的 SSE 生成器在 `asyncio.CancelledError` / `GeneratorExit` 时调用 `llm_service.close_http_client(api_base, api_key)`，强制关闭挂在 AsyncOpenAI 上的 httpx 连接 → 上游 stream 立即被 abort → 不再产生新 token。

副作用：
- 已收到的 delta 仍会作为 partial 消息持久化（带 `client_disconnected: True` 元信息）
- `chat_metrics.stream_stopped` 仍记账（带 `error=True`）
- 下次 chat 请求会重新创建 httpx client（cache miss），首字节延迟 +50~100ms（一次性）

---

## 🔄 Chroma 升级路径（0.5.x → 0.6+）

> 当前 `requirements.txt` 锁 `chromadb>=0.5.0,<0.6.0`，**避开 0.6.3 的 `_type` config 迁移 bug**。
> 等上游修 bug 后（建议先看 [chromadb issue tracker](https://github.com/chroma-core/chroma/issues) 搜 `_type` / `from_json`），可按下面步骤解锁升级。

### 解锁前 checklist

- [ ] 查上游 release notes，确认 `_type` 迁移代码已重写（PR 合并 / issue 关闭）
- [ ] 在 staging 环境跑一遍 KB 文档上传 → ingest → 检索，确认无 `_type` 错误
- [ ] 备份现有 chroma 数据：`cp -r backend/data/chroma backend/data/chroma.bak.$(date +%F)`
- [ ] 跑 Locust 性能回归，看 p95 没有大幅退化

### 升级步骤

```bash
# 1. 改 requirements.txt
#    chromadb>=0.5.0,<0.6.0    →    chromadb>=0.5.0,<1.0.0
sed -i 's/chromadb>=0.5.0,<0.6.0/chromadb>=0.5.0,<1.0.0/' backend/requirements.txt

# 2. 装新版
pip install -U -r backend/requirements.txt

# 3. 保留旧数据试跑（不删 chroma 数据目录）
#    chroma 0.6.x 会自己跑 schema migration；如果失败则降级回 0.5.x
uvicorn app.main:app --reload --port 8000

# 4. 端到端验证
#    - 上传 1 个 KB 文档，确认 ingest status=ready
#    - 检索 1 个 query，确认 sources 返回正确
#    - 查看 B 端「分片可视化」Modal 正常
```

### 回滚（如果升级失败）

```bash
# 1. 卸新版
pip install 'chromadb>=0.5.0,<0.6.0'

# 2. 恢复备份（如果上一步保留）
rm -rf backend/data/chroma
mv backend/data/chroma.bak.* backend/data/chroma
```

### 为什么不直接锁到 0.6.x 最新小版本

- 0.6.x 系列每个小版本都改 schema（`ConfigurationInternal` 的 JSON 字段在变）
- 跨小版本升级可能再次触发迁移 bug
- 等 0.7.x 稳定后再评估是更稳的策略

### 相关 issue / PR（待跟进）

- 现象：`chromadb/api/configuration.py:209 in from_json` 抛 `KeyError: '_type'`
- 触发路径：`get_collections → _load_config_from_json_str_and_migrate → CollectionConfigurationInternal.from_json_str → from_json`
- 上游链接待补（chromadb 仓库搜关键字）

---

## 🤝 贡献指南

### 开发约定
- 前端：CSS Variables + BEM 命名，ES Module 分文件，无构建。
- 后端：所有 API 路由在 `app/api/v1/` 下，按业务模块分文件。
- 数据库：表结构变更必须生成 alembic 迁移，不直接改表。
- LLM：所有调用走 `services/llm_service.py` 统一封装，便于切换模型。
- 路由层只做参数解析和返回，业务逻辑必须放到 `services/`。
- LLM 不得让 C 端直接调用，必须走后端（限流 / 记账 / 审计）。

### 安全规范
- 密码 bcrypt（cost ≥ 12）。
- API Key 加密存储（不要提交到 Git）。
- 用户隐私数据（身高/体重/训练记录）按 GDPR / 个保法要求处理。
- 动作媒体 © Gym visual，UI 固定保留版权声明。
- 生产部署前必读 [SECURITY.md](./SECURITY.md) 全部 13 节。

### Claude 协作
- 启动对话前请 [阅读 CLAUDE.md](./.claude/CLAUDE.md)。
- 数据库变更任务建议使用 `/db-init` 命令。
- 后端开发任务建议用 `@backend-dev` agent。

---

## 📄 License

本项目代码遵循 MIT License。
动作媒体（图片 & GIF）© [Gym visual](https://gymvisual.com/)，二次使用需自行获取授权。
数据集基于 [hasaneyldrm/exercises-dataset](https://github.com/hasaneyldrm/exercises-dataset)，详见原始 LICENSE。

---

## 🙏 致谢

- [wangmuerxiao/exercises-dataset-zh](https://github.com/wangmuerxiao/exercises-dataset-zh) — 中文动作数据集
- [hasaneyldrm/exercises-dataset](https://github.com/hasaneyldrm/exercises-dataset) — 原始英文数据集
- [Gym visual](https://gymvisual.com/) — 动作媒体提供方
