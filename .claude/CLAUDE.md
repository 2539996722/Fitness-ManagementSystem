# FitHub 健身管理系统 · Claude 协作指南

> 当 Claude 进入本项目时，请先读这份文档。它定义了项目的工作约定、技术栈、关键约束。

## 🎯 项目本质

这是一个**全栈 Web 应用**：
- **C 端**：用户浏览健身动作、生成训练计划、与 AI 对话
- **B 端**：管理员 + 教练 + 客服三级管理后台
- **核心数据**：1,324 个健身动作（来自 wangmuerxiao/exercises-dataset-zh）

**最重要的文档**：[prd.md](../prd.md)（v1.1）。所有功能决策的源头，**先读 PRD 再动手**。

---

## 🛠️ 技术栈（已锁死）

| 层 | 选型 | 不要 |
|---|---|---|
| 前端 | 纯 HTML + CSS + 原生 JS（无构建） | ❌ 不要引入 React/Vue/Tailwind/打包工具 |
| 后端 | Python 3.11+ / FastAPI | ❌ 不要用 Flask / Django |
| ORM | SQLAlchemy 2.x async + Alembic | ❌ 不要裸 SQL 或 SQLModel |
| 数据库 | MySQL 8（utf8mb4） | ❌ 不要 SQLite / PostgreSQL（除非测试） |
| 鉴权 | JWT（HS256，python-jose） | ❌ 不要用 Session |
| LLM | OpenAI 兼容协议（`openai` SDK） | ❌ 不要锁定单一厂商 |
| 向量库 | Chroma（嵌入式） | ❌ MVP 不用 Milvus/Qdrant |
| 密码哈希 | bcrypt（passlib，cost=12） | ❌ 不要 md5/sha256 |

---

## 📁 关键路径

```
/健身管理
├── prd.md                 # 产品需求（先读）
├── 数据库使用.md          # MySQL 详细指南
├── /web                   # 前端
│   ├── /c                 # C 端页面
│   └── /admin             # B 端页面
├── /backend               # FastAPI
│   └── /app
│       ├── /api/v1        # 路由（按业务模块分文件）
│       ├── /core          # 配置、JWT、安全
│       ├── /db            # SQLAlchemy session、models
│       ├── /schemas       # Pydantic
│       └── /services      # 业务逻辑（LLM、Plan、Auth）
└── /data/exercises-dataset-zh   # 原始数据集（git clone 进来）
```

---

## 📐 工作约定

### 前端
- CSS 用 CSS Variables + BEM 命名。
- JS 用 ES Module，文件按功能拆分。
- Markdown 渲染用 `marked.js`（已确认），图表用 `Chart.js`（已确认）。
- **不引入 npm 依赖**，所有第三方库用 CDN 或本地静态文件。
- 不做 i18n，UI 文本硬编码中文（PRD D10）。

### 后端
- 所有路由必须在 `app/api/v1/` 下，按模块分文件（`auth.py` / `users.py` / `exercises.py` ...）。
- 数据库表用 SQLAlchemy 2.x **Declarative + mapped_column** 风格，不要用老式 `Column`。
- 所有 schema 用 Pydantic v2，不要用 v1 语法。
- 业务逻辑放 `services/`，路由层只做参数解析和返回。
- LLM 调用必须走 `services/llm_service.py`，不在路由里直接调 SDK。
- 长耗时任务（计划生成、批量导入）走异步任务 + 轮询。

### 数据库
- 所有表必须有 `created_at` / `updated_at`。
- 所有外键必须有索引。
- JSON 字段仅用于"结构固定但 schema 演进快"的场景（如 `plans.weeks`）。
- 表结构变更**必须**走 alembic 迁移，不要直接 `ALTER TABLE`。
- 数据库详细使用见 [数据库使用.md](../数据库使用.md)。

### 角色与权限（D2）
系统有 4 种角色（`users.role` 字段）：
- `user`：普通 C 端用户
- `customer_service`：客服，仅人工会话
- `trainer`：教练，模板 + 专业咨询
- `admin`：管理员，全权

权限矩阵见 PRD §3.2。RBAC 在路由层用 `Depends(require_role(...))` 校验。

### LLM（D3, D8）
- 4 大场景：问答、计划、动作替代、饮食建议。
- 协议：OpenAI 兼容（`/v1/chat/completions`、`/v1/embeddings`）。
- 计划生成失败兜底：**RAG 检索相似动作 + 重生成**，不用模板库。
- 所有调用记录到 `ai_call_logs` 表（tokens、cost、latency）。

---

## ⚠️ 不要做的事

- ❌ 不要修改 PRD 中已确认的决策（D1~D10），如有新需求先讨论再更新 PRD。
- ❌ 不要在前端引入任何 npm 构建工具链。
- ❌ 不要在代码中硬编码 API Key、密码、Token。
- ❌ 不要在路由层写复杂业务逻辑，必须抽到 `services/`。
- ❌ 不要让 C 端直接调 LLM API（必须走后端，便于限流、记账、审计）。
- ❌ 不要忘记标注动作媒体版权 © Gym visual。
- ❌ 不要在生产环境用 DEBUG 模式或默认密钥。
- ❌ 不要提交 `.env`、`__pycache__`、`*.db` 等敏感/临时文件（参考 `.gitignore`）。

---

## ✅ 常用命令

### 数据库
- 启动 MySQL（Docker）：见 [数据库使用.md §本地启动](../数据库使用.md)
- 生成迁移：`alembic revision --autogenerate -m "msg"`
- 应用迁移：`alembic upgrade head`
- 回滚：`alembic downgrade -1`
- 导入动作数据：`python -m app.db.seed_exercises`

### 后端
- 开发：`uvicorn app.main:app --reload --port 8000`
- 测试：`pytest`
- 代码格式化：`ruff check --fix . && ruff format .`

### 前端
- 本地服务：`cd web && python -m http.server 8080`
- C 端访问：`http://localhost:8080/c/`
- B 端访问：`http://localhost:8080/admin/`

### Claude 协作
- 看产品问题 → 读 `prd.md`
- 看数据库问题 → 读 `数据库使用.md`
- 看后端架构 → 读 `.claude/agents/backend-dev.md`
- 初始化数据库 → 用 `/db-init` slash command

---

## 🔍 已知约束

1. **动作媒体版权**：© Gym visual，C 端必须保留版权声明，商业化前需获取书面授权。
2. **数据集覆盖**：1,324 个动作，中文动作名翻译 1,319/1,324（99.6%）。
3. **JWT 过期**：Access 2h，Refresh 7d；前端用 Refresh 自动续期。
4. **LLM 限流**：单用户每日 50 次、每分钟 5 次。
5. **MVP 范围**：M1+M2+M3+M4 共 8 周，评论/教练/模板作为 MVP+1。

---

## 📝 修改约定

修改本文件后，请在文件头更新日期。所有跨多个文件的功能变更，建议同步更新 PRD。