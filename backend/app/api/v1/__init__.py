"""API v1 路由聚合。

新增路由：
1. 在本目录下创建文件，定义 `router = APIRouter(...)`
2. 在本文件导入并 `api_router.include_router(...)`
"""

from fastapi import APIRouter

from app.api.v1 import (
    admin,
    admin_banner,
    admin_dashboard,
    admin_knowledge_base,
    admin_log,
    admin_member,
    admin_templates,
    admin_trace,
    auth,
    chat,
    exercises,
    health,
    plan_templates,
    plans,
    reviews,
    tan_actions,
    tan_diet,
    tan_plans,
    trainer,
    users,
)

api_router = APIRouter()

# 健康检查（不需要鉴权）
api_router.include_router(health.router, prefix="/health", tags=["健康检查"])

# 鉴权
api_router.include_router(auth.router, prefix="/auth", tags=["鉴权"])

# 当前用户（/users/me）
api_router.include_router(users.router, prefix="/users", tags=["用户"])

# 动作
api_router.include_router(exercises.router, prefix="/exercises", tags=["动作"])

# 动作评论（M7）
api_router.include_router(reviews.router, prefix="", tags=["动作评论"])

# 训练计划 + 打卡
api_router.include_router(plans.router, prefix="/plans", tags=["训练计划"])

# 计划模板（C 端市场 + 采用）
api_router.include_router(plan_templates.router, prefix="/plan-templates", tags=["计划模板"])

# B 端教练工作台（模板 CRUD + 队列）
api_router.include_router(trainer.router, prefix="/trainer", tags=["教练工作台"])

# AI 助手 / 会话（M4）
api_router.include_router(chat.router, prefix="", tags=["AI 助手"])

# B 端管理（M5+，当前仅含系统配置）
api_router.include_router(admin.router, prefix="/admin", tags=["管理后台"])

# B 端会员管理（M6）
api_router.include_router(admin_member.router, prefix="/admin", tags=["会员管理"])

# B 端数据看板（M6）
api_router.include_router(admin_dashboard.router, prefix="/admin", tags=["数据看板"])

# B 端模板审核（M8）
api_router.include_router(admin_templates.router, prefix="/admin", tags=["模板审核"])

# B 端操作日志（M9）
api_router.include_router(admin_log.router, prefix="/admin", tags=["操作日志"])

# C 端公告 + B 端公告管理（M9）
api_router.include_router(admin_banner.public_router, prefix="", tags=["公告"])
api_router.include_router(admin_banner.admin_router, prefix="", tags=["公告管理"])

# B 端链路追踪（M10+）
api_router.include_router(admin_trace.router, prefix="/admin", tags=["链路追踪"])

# B 端知识库（M10+ RAG）
api_router.include_router(admin_knowledge_base.admin_router, prefix="", tags=["知识库"])

# 谭师动作库（外部内容合集，C 端只读）
api_router.include_router(tan_actions.router, prefix="", tags=["谭师动作库"])

# 谭师训练计划（三分化 / 四分化）
api_router.include_router(tan_plans.router, prefix="", tags=["谭师训练计划"])

# 谭师饮食
api_router.include_router(tan_diet.router, prefix="", tags=["谭师饮食"])