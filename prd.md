# FitHub 健身管理系统 · 产品需求文档（PRD）

> **版本**：v1.1
> **状态**：活跃（living document）
> **更新日期**：2026-10-18
> **所有者**：产品 / 工程 共同维护
>
> 本文档是 FitHub 项目的**单一事实来源**（single source of truth）。所有功能决策、里程碑状态、API 约定、数据模型都以本文档为准。
>
> 相关文档：
> - [README.md](./README.md) — 快速启动 + 部署 + 测试 + Troubleshooting
> - [CLAUDE.md](./.claude/CLAUDE.md) — Claude 协作时的工作约定与技术栈锁定
> - [SECURITY.md](./SECURITY.md) — 生产部署前安全自检清单（13 节）

---

## 📋 目录

1. [产品定位](#1-产品定位)
2. [目标用户与场景](#2-目标用户与场景)
3. [角色与权限矩阵](#3-角色与权限矩阵)
4. [核心数据](#4-核心数据)
5. [功能模块](#5-功能模块)
6. [关键决策（D1~D10）](#6-关键决策d1d10)
7. [技术栈](#7-技术栈)
8. [数据模型（16 张表）](#8-数据模型16-张表)
9. [API 路由总览](#9-api-路由总览)
10. [前端页面索引](#10-前端页面索引)
11. [里程碑与 MVP 范围](#11-里程碑与-mvp-范围)
12. [LLM 集成规范](#12-llm-集成规范)
13. [已知约束与待办](#13-已知约束与待办)

---

## 1. 产品定位

FitHub 是一款**全栈 Web 应用**，围绕"健身动作"这一核心数据资产，向 C 端健身爱好者提供浏览/计划/对话体验，向 B 端运营团队提供数据/会员/内容管理后台。

### 一句话定位

> **1,324 个健身动作库 + 198 个谭师库动作 + AI 健身教练** —— 一个面向健身爱好者与运营团队的 C 端 + B 端一体化管理系统。

### 产品差异化

- **数据厚度**：1,324 个动作 × 10 语言步骤说明 = 完整结构化训练知识图谱
- **教练原创内容**：198 个谭师库动作 + 三/四分化训练计划 + 5 个饮食原理原片（教练谭成义）
- **AI 兜底**：4 大 LLM 场景（问答/计划/替代/饮食），失败时 RAG 检索相似动作重生成
- **私有部署友好**：单端口 8000 出入口、Docker Compose 一键起、零前端构建步骤

---

## 2. 目标用户与场景

### C 端用户（`role=user`）

| 场景 | 关键路径 |
|---|---|
| 浏览健身动作 | `/c/` → 筛选 → `/c/detail.html?id=0001` |
| 学习训练计划 | `/c/tan-library.html` → 三/四分化 → `/c/tan-plan.html` |
| 计算每日摄入 | `/c/tan-diet.html` → 填写表单 → 静态克数建议 |
| 用 AI 助手做计划 | `/c/plan-create.html` → 选 AI 生成 → 异步轮询 |
| 与 AI 教练对话 | `/c/chat.html` → 4 场景问答 |
| 转人工 | AI 对话 → "转人工" → 等待 `trainer` 接入 |
| 评论动作 | 动作详情页 → 1-5 星 + 文字评论 |
| 训练打卡 | 计划详情 → 完成项勾选 |

### B 端管理员（`role=admin`）

| 场景 | 关键路径 |
|---|---|
| 数据看板 | `/admin/dashboard.html` → overview / AI 成本 / 用户趋势 |
| 会员管理 | `/admin/users.html` → CRUD / 禁用 / 角色分配 |
| 模板审核 | `/admin/templates.html` → 队列 → approve / reject |
| 评论审核 | `/admin/reviews.html` |
| 公告管理 | `/admin/banners.html` |
| 系统配置 | `/admin/system-config.html` → LLM 限流 / 提示词模板 |
| 知识库管理 | `/admin/knowledge-base.html` → 上传 / ingest / 检索测试 / 分片可视化 |
| 操作日志 | `/admin/operation-logs.html` |
| 链路追踪 | `/admin/traces.html` → RequestId 串联 |

### B 端教练（`role=trainer`，**M4 起兼客服**）

| 场景 | 关键路径 |
|---|---|
| 发布训练计划模板 | `/admin/workbench.html` → "我的模板" → 新建 |
| 接入人工会话 | `/admin/workbench.html` → "教练队列" → claim → 收发消息 → close |
| 模板 CRUD | `/admin/workbench.html` → 模板列表 |

---

## 3. 角色与权限矩阵

### 3.1 角色定义

D2 决策：**3 种活跃角色**（`users.role` 字段）。M4 合并后 trainer 兼原 customer_service 全部职责。

| 枚举值 | 含义 | 备注 |
|---|---|---|
| `user` | 普通 C 端用户 | 默认角色 |
| `trainer` | 教练，**兼原客服** | M4 合并起，会话工作台统一处理 `trainer` 人工会话（历史 `customer_service` 记录已在 M12 迁移中归一为 `trainer`） |
| `admin` | 管理员，全权 | 含系统配置/会员/审核/日志/链路追踪 |

> **历史数据**：M12 (#122) 迁移 `0017_drop_cs_legacy` 已把 DB 中残留的 `customer_service` 字符串归一为 `trainer`。新代码不再签发也不再接受此枚举值。

### 3.2 权限矩阵（路由级）

| 路由前缀 | 公开 | user | trainer | admin |
|---|---|---|---|---|
| `/api/v1/auth/*` | ✅ | ✅ | ✅ | ✅ |
| `/api/v1/users/me` | — | ✅ | ✅ | ✅ |
| `/api/v1/exercises/*` | ✅ | ✅ | ✅ | ✅ |
| `/api/v1/reviews/*` | ✅ | ✅ | ✅ | ✅ |
| `/api/v1/plans/*` | — | ✅ | ✅ | ✅ |
| `/api/v1/plan-templates/*` | ✅ | ✅ | ✅ | ✅ |
| `/api/v1/chat/*` | — | ✅ | ✅ | ✅ |
| `/api/v1/trainer/*` | — | — | ✅ | ✅ |
| `/api/v1/admin/*` | — | — | — | ✅ |
| `/api/v1/tan-actions` | ✅ | ✅ | ✅ | ✅ |
| `/api/v1/tan-plans` | ✅ | ✅ | ✅ | ✅ |
| `/api/v1/tan-diet` | ✅ | ✅ | ✅ | ✅ |
| `/api/v1/banners/active` | ✅ | ✅ | ✅ | ✅ |
| `/api/v1/admin/banners` | — | — | — | ✅ |
| `/api/v1/health` | ✅ | ✅ | ✅ | ✅ |
| `/static/*` | ✅ | ✅ | ✅ | ✅ |

> RBAC 在路由层用 `Depends(require_role(...))` 校验；`require_trainer` 即覆盖历史 `customer_service`（别名兼容）。

---

## 4. 核心数据

### 4.1 健身动作库（公开数据集）

- **数据源**：[wangmuerxiao/exercises-dataset-zh](https://github.com/wangmuerxiao/exercises-dataset-zh)
- **规模**：1,324 个动作
- **中文名覆盖率**：1,319/1,324 = **99.6%**
- **字段**：`id` / `name_en` / `name_zh` / `category` / `equipment` / `mechanic` / `force` / `difficulty` / `instructions`（10 语言 JSON） / `images` / `videos`
- **媒体版权**：© [Gym visual](https://gymvisual.com/)，C 端必须保留版权声明
- **数据流**：MySQL 存结构化元数据 + Chroma 存动作步骤子块 embedding

### 4.2 谭师库（教练原创内容）

- **动作数**：198 个
- **子模块**：
  - **动作库**（`/tan-actions`）— 198 个教练原创动作（筛选 / 详情）
  - **训练计划**（`/tan-plans`）— 三分化 / 四分化
  - **饮食专题**（`/tan-diet`）— 5 个视频列表 + 详情 + 每日克数计算器
- **数据源**：仓库内 `dataset/actions_full.json`（扫描 `training_profile.arrangements` 自动构建）

### 4.3 父块/子块策略（RAG）

每个动作的 10 语言步骤说明会切分为：
- **父块（parent chunk）**：完整动作某个语言完整说明 → 存 MySQL `exercises.instructions`
- **子块（child chunk）**：每一步动作 → 单独成块 → 嵌入向量 → 存 Chroma

检索时按子块相似度匹配，命中后**回溯父块**返回完整说明（粒度细、回答粗）。

---

## 5. 功能模块

### 5.1 C 端模块

| 模块 | 说明 | 状态 |
|---|---|---|
| 动作浏览 | 1324 + 198 个动作，分页 / 筛选 / 详情 | ✅ |
| 训练计划 | 手动 / AI 生成 / 模板采用 / 三分化四分化预设 | ✅ |
| AI 对话 | 4 场景（问答/计划/替代/饮食）SSE 流式 | ✅ |
| 动作评论 | 1-5 星 + 文字评论 | ✅ |
| 训练打卡 | 计划详情勾选完成项 | ✅ |
| 个人中心 | 资料 / 头像 / 训练曲线 | ✅ |
| 饮食计算 | 克数计算器 + 5 个原片 | ✅ |
| 转人工 | AI → trainer 队列 | ✅ M4 |

### 5.2 B 端模块

| 模块 | 角色 | 状态 |
|---|---|---|
| 教练工作台 | trainer | ✅ M4 |
| 模板审核 | admin | ✅ |
| 会员管理 | admin | ✅ |
| 评论审核 | admin | ✅ |
| 公告管理 | admin | ✅ M9 |
| 数据看板 | admin | ✅ |
| 系统配置 | admin | ✅ |
| 知识库 | admin | ✅ |
| 操作日志 | admin | ✅ |
| 链路追踪 | admin | ✅ |

### 5.3 独立 CS / 客服角色

**不存在**（M4 合并）：原 `customer_service` 角色被 `trainer` 吸收；会话工作台处理两类历史会话（`conversation_type IN ('trainer', 'customer_service')`）。详见 [§6 关键决策 D2](#6-关键决策d1d10)。

---

## 6. 关键决策（D1~D10）

> 这是 FitHub 项目的**核心决策清单**。修改前必须先讨论并更新本节。

| # | 决策 | 选择 | 理由 / 备注 |
|---|---|---|---|
| D1 | C 端登录 | JWT + 账号密码，预留扩展 | 短期不接入第三方 OAuth；账号密码够用 |
| D2 | 角色 | **3 个**（`user` / `trainer` / `admin`）；M12 迁移后 `customer_service` 已从 DB 清理 | M4 合并：trainer 兼客服；CS 独立角色废除 |
| D3 | LLM 功能 | 问答 + 计划 + 替代 + 饮食（4 场景） | 覆盖 C 端全部高频需求 |
| D4 | 技术栈 | FastAPI + MySQL + Chroma，前端纯 HTML/CSS/JS | 见 [§7 技术栈](#7-技术栈) |
| D5 | 动作数据源 | wangmuerxiao/exercises-dataset-zh | 中文名覆盖率 99.6% |
| D6 | 付费会员 | MVP 不实现，预留扩展 | 不阻塞核心功能 |
| D7 | 动作社区化 | 允许评论 + 1-5 星打分 | MVP+1 |
| D8 | AI 兜底 | RAG 检索相似动作重生成 | 不用模板库；保证可解释性 |
| D9 | 客服排班 | **不需要**（M4 起 trainer 接管） | 原"客服排班"改为"会话接管" |
| D10 | 国际化 | 仅中文 | UI 文本硬编码中文 |

### 6.1 M4 合并决策详情

- **废除独立 CS 用户**：不再签发 `role=customer_service`；B 端 `/admin/workbench.html` 不再有 CS Tab
- **路由统一**：`cs.py` 删除，CS 业务合并到 `trainer.py`
- **会话状态机**：
  ```
  ai_active ──(用户点"转人工")──> waiting_trainer
  waiting_trainer ──(trainer claim)──> trainer_active
  trainer_active ──(trainer close)──> ai_active
  ```
- **DB 兼容**：`conversations.conversation_type` 允许 `trainer` 和 `customer_service` 两个值；`messages.sender_type` 同理
- **B 端会话工作台**：只看 `waiting_trainer` / `trainer_active` 状态的会话，类型不限

---

## 7. 技术栈

### 7.1 锁定选型

| 层 | 选型 | ❌ 不要 |
|---|---|---|
| 前端 | 纯 HTML + CSS + 原生 JS（无构建步骤） | React / Vue / Tailwind / 打包工具 |
| 后端 | Python 3.11+ / FastAPI | Flask / Django |
| ORM | SQLAlchemy 2.x async + Alembic | 裸 SQL / SQLModel |
| 数据库 | MySQL 8（utf8mb4） | SQLite / PostgreSQL（除测试） |
| 鉴权 | JWT（HS256，python-jose） | Session |
| LLM | OpenAI 兼容协议（`openai` SDK） | 锁定单一厂商 |
| 向量库 | Chroma（嵌入式） | MVP 不用 Milvus / Qdrant |
| 密码哈希 | bcrypt（passlib，cost=12） | md5 / sha256 |
| 缓存 | Redis 7（async） | 无（仅 M1-M3 兼容） |
| 限流 | slowapi | 无 |
| 日志 | loguru | print |
| 图表 | Chart.js（CDN） | ECharts / D3 |
| Markdown | marked.js（CDN） | 其他 |

### 7.2 存储架构（三层）

| 层 | 存储 | 用途 |
|---|---|---|
| 结构化 | MySQL 8 | 用户、训练计划、全量会话历史、知识库台账、系统配置 |
| 向量层 | Chroma（嵌入式） | 子块向量（RAG 检索，零部署，Windows 友好） |
| 缓存层 | Redis | 最近 5 轮短期会话缓存，加速 AI 响应 |

### 7.3 数据流（AI 对话场景）

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

## 8. 数据模型（16 张表）

> 表结构详见 `backend/app/db/models/` 和 `backend/alembic/versions/`。
> **约定**：所有表都有 `created_at` / `updated_at`，所有外键都建了索引。

| # | 表 | 模型文件 | 用途 |
|---|---|---|---|
| 1 | `users` | `user.py` | C/B 端账号（`role` 3 活跃枚举 + 1 历史 `customer_service`） |
| 2 | `exercises` | `exercise.py` | 1,324 个动作主数据（含 10 语言 `instructions`） |
| 3 | `exercise_reviews` | `exercise_review.py` | 动作评论 + 1-5 星打分 |
| 4 | `plans` | `plan.py` | 用户训练计划（含 `weeks` JSON） |
| 5 | `training_records` | `training_record.py` | 训练打卡记录 |
| 6 | `plan_templates` | `plan_template.py` | 教练发布的计划模板（市场 + 审核流） |
| 7 | `conversations` | `conversation.py` | AI / 人工会话聚合（`assigned_trainer_id` 字段） |
| 8 | `messages` | `message.py` | 会话消息流（`sender_type`: user / ai / trainer + 历史 `customer_service`） |
| 9 | `system_configs` | `system_config.py` | 系统配置 KV（限流、模型名、提示词模板） |
| 10 | `ai_call_logs` | `ai_call_log.py` | 每次 LLM 调用记录（tokens / cost_cny / latency / intent） |
| 11 | `operation_logs` | `operation_log.py` | B 端写操作审计（`operator` / `action` / `target_type` / `target_id`） |
| 12 | `banners` | `banner.py` | C 端公告 + B 端公告管理 |
| 13 | `trace_spans` | `trace_span.py` | 全链路追踪 span（与 RequestIdMiddleware 联动） |
| 14 | `knowledge_base` | `knowledge_base.py` | RAG 知识库台账（标题/来源/状态） |
| 15 | `knowledge_documents` | `knowledge_document.py` | 知识库文档子块（向量 + 原文） |
| 16 | `alembic_version` | — | Alembic 版本号 |

---

## 9. API 路由总览

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
| `/trainer` | `trainer.py` | trainer | 教练工作台：模板 CRUD + 会话队列（M4 合并 CS） |
| `/chat` | `chat.py` | user | AI 对话（4 场景：问答/计划/替代/饮食，SSE 流式） |
| `/admin` | `admin.py` | admin | 系统配置 |
| `/admin` | `admin_member.py` | admin | 会员管理 |
| `/admin` | `admin_dashboard.py` | admin | 数据看板（overview / ai-cost / user-trend / chat-metrics） |
| `/admin` | `admin_templates.py` | admin | 模板审核队列（approve / reject / offline） |
| `/admin` | `admin_log.py` | admin | 操作日志查询 |
| `/admin` | `admin_trace.py` | admin | 链路追踪查询 |
| `/admin/knowledge-bases` | `admin_knowledge_base.py` | admin | RAG 知识库 CRUD |
| `/admin/knowledge-bases/{kb_id}/documents/{doc_id}/chunks` | `admin_knowledge_base.py` | admin | 文档分片原文可视化（调试） |
| `/admin/knowledge-bases/{kb_id}/retrieval-test` | `admin_knowledge_base.py` | admin | KB 检索测试 |
| `/banners` | `admin_banner.py` | 公开 | C 端公告 |
| `/admin/banners` | `admin_banner.py` | admin | 公告管理 |
| `/tan-actions` | `tan_actions.py` | 公开 | 谭师库：198 个教练动作（筛选 / 详情 / meta） |
| `/tan-plans` | `tan_plans.py` | 公开 | 训练计划：三分化 / 四分化 |
| `/tan-diet` | `tan_diet.py` | 公开 | 饮食专题：5 个视频列表 + 详情 |
| `/static/images`、`/static/videos` | `main.py` | 公开 | 动作 GIF / 缩略图（数据集直挂） |

> **M4 合并后**：`cs.py` 已删除；原 CS 业务合并到 `trainer.py`。`api_router.include_router(cs.router)` 在 `__init__.py` 已注释。

完整 schema：`http://localhost:8000/docs`（Swagger UI）或 `/openapi.json`。

---

## 10. 前端页面索引

### 10.1 C 端（`web/c/`，挂在 `/c/`）

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
| AI 聊天 | `chat.html` | AI 教练对话入口（含转人工） |
| 个人中心 | `profile.html` | 资料 / 头像 / 训练曲线 |

### 10.2 B 端（`web/admin/`，挂在 `/admin/`）

| 页面 | 文件 | 角色 | 说明 |
|---|---|---|---|
| 入口 | `index.html` | 公开 | B 端首页 |
| 登录 | `login.html` | 公开 | B 端登录（按角色路由） |
| 工作台 | `workbench.html` | trainer / admin | 角色感知快捷入口（含教练队列 + 模板管理） |
| 数据看板 | `dashboard.html` | admin | overview / AI 成本 / 用户趋势 |
| 会员管理 | `users.html` | admin | C 端用户 CRUD + 禁用 |
| 模板审核 | `templates.html` | admin | 模板队列审核 |
| 动作评论管理 | `reviews.html` | admin | 评论审核 / 删除 |
| 公告管理 | `banners.html` | admin | 公告发布 + 上下线 |
| 系统配置 | `system-config.html` | admin | 全局配置 |
| 操作日志 | `operation-logs.html` | admin | `operation_logs` 查询 |
| 知识库 | `knowledge-base.html` | admin | RAG 知识库管理（含文档分片可视化） |
| 链路追踪 | `traces.html` | admin | `trace_spans` 查询（RequestId 串联） |

---

## 11. 里程碑与 MVP 范围

| 阶段 | 时间 | 内容 | 状态 |
|---|---|---|---|
| M1 | 1-2 周 | 数据集导入、FastAPI 骨架、数据库 | ✅ 完成 |
| M2 | 3-4 周 | C 端基础（浏览、登录）+ 训练计划 | ✅ 完成 |
| M3 | 5-6 周 | AI 助手（RAG + 4 场景） | ✅ 完成 |
| M4 | 7-8 周 | 转人工（trainer 兼客服） | ✅ 完成（合并 CS） |
| M5 | 9-10 周 | B 端会员管理 + 教练工作台 | ✅ 完成 |
| M6 | 11 周 | 动作评论 + 教练模块（队列接管） | ✅ 完成 |
| M7 | 12-14 周 | B 端完整 + 系统配置 + 操作日志 + 知识库 + 公告 | ✅ 完成 |
| M8 | 15-16 周 | 测试（Locust 压测）+ 上线 | 🚧 进行中 |
| M9 | 17 周 | 公告管理 | ✅ 完成 |

**MVP 建议范围**：M1 + M2 + M3 + M4（共 8 周）。

> M4 合并后，"客服工作台"作为独立 M5 任务已并入"教练工作台"。

---

## 12. LLM 集成规范

### 12.1 4 大场景

| 场景 | 入口 | 兜底 |
|---|---|---|
| 问答 | `/api/v1/chat/send` (intent=qa) | RAG 检索相似动作重生成 |
| 计划 | `/api/v1/chat/send` (intent=plan) | RAG 检索 + 模板重生成 |
| 动作替代 | `/api/v1/chat/send` (intent=substitute) | 相似度 Top-K |
| 饮食 | `/api/v1/chat/send` (intent=diet) | 克数计算器静态兜底 |

### 12.2 协议

OpenAI 兼容：`/v1/chat/completions`、`/v1/embeddings`。

### 12.3 限流

- 全局：60/分钟/IP
- AI：5/分钟 + 50/天/每用户

### 12.4 审计

每次 LLM 调用记录到 `ai_call_logs`（tokens / cost_cny / latency / intent）。

### 12.5 关键约束

- ❌ 不让 C 端直接调 LLM API（必须走后端，便于限流、记账、审计）
- ❌ 不在路由里直接调 SDK（必须走 `services/llm_service.py`）
- ✅ 计划生成失败时 RAG 检索相似动作 + 重生成，**不用**模板库
- ✅ 所有调用记录到 `ai_call_logs` 表

---

## 13. 已知约束与待办

### 13.1 已知约束

1. **动作媒体版权**：© Gym visual，C 端必须保留版权声明，商业化前需获取书面授权
2. **数据集覆盖**：1,324 个动作，中文动作名翻译 1,319/1,324（99.6%）
3. **JWT 过期**：Access 2h，Refresh 7d；前端用 Refresh 自动续期
4. **LLM 限流**：单用户每日 50 次、每分钟 5 次
5. **MVP 范围**：M1+M2+M3+M4 共 8 周，评论/教练/模板作为 MVP+1
6. **Windows 端口僵尸**：偶发 netstat LISTENING 但 PID 找不到，taskkill 失效，需重启系统或改端口
7. **Chroma 0.6.x 已知 bug**：当前 `requirements.txt` 锁 `chromadb>=0.5.0,<0.6.0` 避开 `_type` config 迁移 bug

### 13.2 M8 进行中

- Locust 压测基线已建立（p95 < 50ms，详见 [backend/tests/perf/README.md](./backend/tests/perf/README.md)）
- 上线前需补：admin_* 5 个 router 单测、SSE 断连取消上游 LLM 请求

### 13.3 文档维护约定

- 本文件（prd.md）变更后，在文件头更新日期
- 所有跨多个文件的功能变更，建议同步更新本文件 + [CLAUDE.md](./.claude/CLAUDE.md) + [README.md](./README.md) 的对应章节
- 关键决策（D1~D10）修改前**必须先讨论**

---

## 📄 更新历史

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-10-18 | v1.1 | 落地 v1.1 正式版：汇编 README + CLAUDE.md；M4 合并 CS 反映到 D2/§3.1/§5.3/§6.1/§9；里程碑 M4-M7 状态统一；新增 §13 已知约束与待办 |
| 2026-10-18 之前 | v1.0 草案 | 散落在 README + CLAUDE.md，未独立成文 |
