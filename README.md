# FitHub 健身管理系统

> 一款面向健身爱好者与运营团队的 C 端 + B 端一体化健身管理系统。
> 1,324 个健身动作库 · AI 健身教练（OpenAI 协议）· 三级 B 端权限（管理员/教练/客服）

## 📋 文档导航

| 文档 | 说明 |
|---|---|
| [prd.md](./prd.md) | 产品需求文档（v1.1），所有功能决策的源头 |
| [数据库使用.md](./数据库使用.md) | MySQL 数据库详细使用指南（配置、迁移、备份、调优） |
| [.claude/CLAUDE.md](./.claude/CLAUDE.md) | Claude 协作时的项目级指令 |
| [.claude/agents/backend-dev.md](./.claude/agents/backend-dev.md) | 后端开发专属 agent |
| [.claude/commands/db-init.md](./.claude/commands/db-init.md) | 数据库初始化 slash command |

---

## 🎯 产品定位

### C 端（用户侧）
- 浏览 1,324 个健身动作（含中文名、GIF 演示、10 语言步骤说明）
- 创建训练计划（手动 / AI 生成 / 教练模板）
- 与 AI 健身教练对话（问答 / 计划 / 动作替代 / 饮食建议）
- 动作评论打分、训练打卡、个人中心

### B 端（管理侧）
- **管理员**：会员管理、教练/客服账号、模板审核、数据看板、系统配置
- **教练**：发布计划模板、审核流程、接管专业训练咨询
- **客服**：基础人工会话接入、可一键升级到教练

---

## 🛠️ 技术栈

### 存储架构（三层）

| 层 | 存储 | 用途 |
|---|---|---|
| **结构化** | MySQL 8 | 用户、训练计划、全量会话历史、知识库台账、系统配置 |
| **向量层** | Milvus Lite（嵌入式） | 子块向量（RAG 检索，零部署） |
| **缓存层** | Redis | 最近 5 轮短期会话缓存，加速 AI 响应 |

### 应用栈

| 层 | 选型 |
|---|---|
| 前端 | 纯 HTML + CSS + 原生 JS（无构建步骤） |
| 后端 | Python 3.11+ / FastAPI |
| 数据库 | MySQL 8 + SQLAlchemy 2.x（async）+ Alembic 迁移 |
| 向量库 | Milvus Lite（pymilvus ≥ 2.4，嵌入式模式） |
| 缓存 | Redis（redis-py ≥ 5.0，async） |
| 鉴权 | JWT（Access 2h + Refresh 7d） |
| LLM | OpenAI 兼容协议（GPT-4o / GPT-4o-mini / DeepSeek / Qwen 等） |
| 数据源 | [wangmuerxiao/exercises-dataset-zh](https://github.com/wangmuerxiao/exercises-dataset-zh) |

### 数据流（AI 对话场景）

```
用户消息 → Redis 取最近 5 轮上下文 → 拼接 Prompt
   ↓
   ├─ MySQL：拉取用户画像、计划、长期会话摘要
   └─ Milvus：用当前问题检索 Top-K 相似动作子块
   ↓
LLM（OpenAI 协议）→ 流式响应
   ↓
   ├─ Redis：追加本轮到短期缓存
   └─ MySQL：持久化完整会话 + 摘要
```

---

## 📁 目录结构

```
/健身管理
├── README.md                # 本文件
├── prd.md                   # 产品需求文档
├── 数据库使用.md            # MySQL 使用指南
│
├── /web                     # 前端（HTML + CSS + JS）
│   ├── /c                   # C 端
│   │   ├── /pages           # 页面
│   │   ├── /components      # 组件
│   │   ├── /assets          # 图片、动作 GIF、缩略图
│   │   ├── /utils           # 工具函数
│   │   └── app.js           # 入口
│   ├── /admin               # B 端
│   │   ├── /pages
│   │   └── ...
│   └── /shared              # 共享静态资源
│
├── /backend                 # FastAPI 后端
│   ├── /app
│   │   ├── /api             # 路由
│   │   │   └── /v1
│   │   ├── /core            # 配置、安全、JWT
│   │   ├── /db              # SQLAlchemy session、models
│   │   ├── /schemas         # Pydantic schemas
│   │   ├── /services        # 业务逻辑（LLM、Plan、Auth）
│   │   └── main.py
│   ├── /data                # 动作 JSON、向量库持久化
│   ├── /alembic             # 数据库迁移
│   ├── requirements.txt
│   └── .env.example
│
├── /data                    # 原始数据集
│   └── /exercises-dataset-zh
│       ├── data/exercises.json
│       ├── data/name_zh.json
│       └── images/, videos/
│
└── /.claude                 # Claude 协作配置
    ├── CLAUDE.md
    ├── settings.local.json
    ├── /agents
    └── /commands
```

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
```

### 1. 启动 MySQL

参见 [数据库使用.md](./数据库使用.md) §"本地启动 MySQL"。

```bash
# Docker 方式（推荐）
docker run -d --name fithub-mysql \
  -e MYSQL_ROOT_PASSWORD=rootpass \
  -e MYSQL_DATABASE=fithub \
  -p 3306:3306 \
  mysql:8.0 --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci
```

### 2. 启动后端（同时托管前端）

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 复制环境变量
cp .env.example .env
# 编辑 .env，填入 MySQL 连接串、LLM API Key、JWT_SECRET 等
#   MYSQL_DSN=mysql+aiomysql://root:Lb403706@localhost:3306/fithub?charset=utf8mb4
#   JWT_SECRET=$(openssl rand -hex 32)
#   LLM_API_KEY=sk-xxx

# 数据库迁移 + 数据导入
alembic upgrade head
python -m app.db.seed_exercises
python -m app.db.create_default_admin

# 启动（单端口）
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

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
> **⚠️ ChromaDB 已默认排除**：requirements.txt 中 chromadb 默认不安装，因为它捆绑了 chroma-hnswlib（C++ 扩展），在 Windows + Python 3.13 上需要 Visual Studio Build Tools。**M1-M3 阶段不需要 chromadb**。M4（RAG 检索）阶段再安装，见下方"可选依赖"。

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

### Redis 与 Milvus 部署

**M1 阶段**不强制启动这两个服务（业务暂未用到）。M4 阶段（AI 助手）必须：

```bash
# 启动 Redis（Docker 方式）
docker run -d --name fithub-redis -p 6379:6379 redis:7-alpine

# 启动 Milvus Lite（嵌入式，零部署）
# 直接用 requirements.txt 中的 pymilvus 即可，无需独立容器
# 数据文件持久化到 ./data/milvus_lite.db
```

> **Windows 注意**：Milvus Lite 嵌入式模式官方仅支持 Linux/macOS。Windows 用户有两个选择：
> 1. **WSL 2**：在 WSL 里跑后端（推荐）
> 2. **Milvus Standalone Docker**：
>    ```bash
>    docker run -d --name fithub-milvus -p 19530:19530 milvusdb/milvus:latest
>    ```
>    然后修改 `.env`：`MILVUS_URI=http://host.docker.internal:19530`
>
> M1-M3 阶段用不到 Milvus（不强制启动）。

### 父块/子块策略（RAG 文档分块）

每个动作的 10 语言步骤说明会被切分为：

- **父块（parent chunk）**：完整动作的某个语言完整说明 → 存 MySQL（`exercises.instructions`）
- **子块（child chunk）**：每一步动作 → 单独成块 → 嵌入向量 → 存 Milvus

检索时按子块相似度匹配，命中后**回溯父块**返回完整说明。这样检索粒度细、回答粒度粗。

---

## 🔑 关键决策（D1~D10）

详见 [prd.md §1](./prd.md) 和 [§12.2](./prd.md)：

| # | 决策 | 选择 |
|---|---|---|
| D1 | C 端登录 | JWT + 账号密码，预留扩展 |
| D2 | B 端角色 | 管理员 + 教练 + 客服（三级） |
| D3 | LLM 功能 | 问答 + 计划 + 替代 + 饮食 |
| D4 | 技术栈 | FastAPI + MySQL，前端 HTML/CSS/JS |
| D5 | 动作数据源 | wangmuerxiao/exercises-dataset-zh |
| D6 | 付费会员 | MVP 不实现，预留扩展 |
| D7 | 动作社区化 | 允许评论 + 1-5 星打分 |
| D8 | AI 兜底 | RAG 检索相似动作重生成 |
| D9 | 客服排班 | 不需要 |
| D10 | 国际化 | 仅中文 |

---

## 📅 里程碑

| 阶段 | 时间 | 内容 | 状态 |
|---|---|---|---|
| M1 | 1-2 周 | 数据集导入、FastAPI 骨架、数据库 | ✅ 完成 |
| M2 | 3-4 周 | C 端基础（浏览、登录）+ 训练计划 | ✅ 完成 |
| M3 | 5-6 周 | AI 助手（RAG + 4 场景） | 🚧 下一步 |
| M4 | 7-8 周 | 转人工（客服/教练） |
| M5 | 9-10 周 | B 端会员管理 |
| M6 | 11 周 | 动作评论 + 教练模块 |
| M7 | 12-14 周 | B 端完整 + 系统配置 |
| M8 | 15-16 周 | 测试与上线 |

**MVP 建议范围**：M1 + M2 + M3 + M4（共 8 周）。

---

## 🤝 贡献指南

### 开发约定
- 前端：CSS Variables + BEM 命名，ES Module 分文件，无构建。
- 后端：所有 API 路由在 `app/api/v1/` 下，按业务模块分文件。
- 数据库：表结构变更必须生成 alembic 迁移，不直接改表。
- LLM：所有调用走 `services/llm_service.py` 统一封装，便于切换模型。

### 安全规范
- 密码 bcrypt（cost ≥ 12）。
- API Key 加密存储（不要提交到 Git）。
- 用户隐私数据（身高/体重/训练记录）按 GDPR / 个保法要求处理。
- 动作媒体 © Gym visual，UI 固定保留版权声明。

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