"""B 端管理路由（admin）。

当前只实现系统配置（LLM 设置）。其他管理功能（用户、模板、会话工作台）
将在 M6-M8 实现。

- GET    /api/v1/admin/configs                  列出全部配置
- GET    /api/v1/admin/configs/llm              获取 LLM 配置（api_key 脱敏）
- PUT    /api/v1/admin/configs/llm              更新 LLM 配置
- POST   /api/v1/admin/configs/llm/test         测试 LLM 连接
- GET    /api/v1/admin/configs/ai-limits        获取 AI 限流配置
- PUT    /api/v1/admin/configs/ai-limits        更新 AI 限流配置
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from sqlalchemy import select

from app.api.deps import get_current_user, require_admin
from app.db.models import SystemConfig, User
from app.db.session import get_session
from app.schemas.system_config import (
    AILimitsConfig,
    LLMConfig,
    LLMConfigUpdate,
    SystemConfigListItem,
    SystemConfigOut,
    TestConnectionResult,
)
from app.services import llm_service
from app.services.operation_log import record as log_operation
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


# ============ 配置列表 ============

@router.get("/configs", response_model=list[SystemConfigListItem], summary="全部系统配置")
async def list_configs(
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[SystemConfigListItem]:
    """列出所有配置项（不含 value 详情，避免泄露敏感字段）。"""
    result = await session.execute(select(SystemConfig).order_by(SystemConfig.key))
    rows = result.scalars().all()
    return [
        SystemConfigListItem(
            key=r.key,
            description=r.description,
            updated_by=r.updated_by,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


# ============ LLM 配置 ============

def _mask_llm(value: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """返回 (脱敏后 value, 被遮蔽的字段列表)。"""
    masked: list[str] = []
    out = dict(value)
    # api_key 前端脱敏：仅展示末尾 4 位
    if out.get("api_key"):
        k = str(out["api_key"])
        if len(k) > 4:
            out["api_key"] = "•" * (len(k) - 4) + k[-4:]
        masked.append("api_key")
    return out, masked


@router.get("/configs/llm", response_model=SystemConfigOut, summary="获取 LLM 配置")
async def get_llm_config(
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SystemConfigOut:
    """获取 LLM 配置。api_key 会脱敏返回。"""
    cfg = await _load_cfg(session, "llm")
    if cfg is None:
        # 首次访问 seed 默认（避免空表）
        cfg = SystemConfig(
            key="llm",
            value=llm_service.DEFAULT_SYSTEM_PROMPT and {
                "api_base": "",
                "api_key": "",
                "model_chat": "gpt-4o-mini",
                "model_embed": "text-embedding-3-small",
                "temperature": 0.7,
                "max_tokens": 2048,
                "timeout": 60,
                "system_prompt": llm_service.DEFAULT_SYSTEM_PROMPT,
            },
            description="LLM 模型配置（OpenAI 兼容协议）",
        )
        session.add(cfg)
        await session.commit()
        await session.refresh(cfg)
    # 缺省值兜底
    base = {
        "api_base": "",
        "api_key": "",
        "model_chat": "gpt-4o-mini",
        "model_embed": "text-embedding-3-small",
        "temperature": 0.7,
        "max_tokens": 2048,
        "timeout": 60,
        "system_prompt": "你是 FitHub 的 AI 健身教练 FitCoach。",
    }
    value = dict(base)
    if cfg and isinstance(cfg.value, dict):
        value.update(cfg.value)
    # 兜底：DB 完全为空时，把 .env 的真实 base/key 标记为已脱敏
    masked_list: list[str] = []
    if value.get("api_key"):
        k = str(value["api_key"])
        if len(k) > 4 and not k.startswith("•"):
            value["api_key"] = "•" * (len(k) - 4) + k[-4:]
            masked_list.append("api_key")

    return SystemConfigOut(
        key="llm",
        value=value,
        description=cfg.description if cfg else "LLM 模型配置",
        updated_by=cfg.updated_by if cfg else None,
        updated_at=cfg.updated_at if cfg else None,
        created_at=cfg.created_at if cfg else None,
        masked=masked_list,
    )


@router.put("/configs/llm", response_model=SystemConfigOut, summary="更新 LLM 配置")
async def update_llm_config(
    body: LLMConfigUpdate,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SystemConfigOut:
    """更新 LLM 配置。

    api_key 若为 None 或空，不修改；若以 "•" 开头（脱敏值原样回传），不修改。
    """
    updates = body.model_dump(exclude_none=True)

    # 防止脱敏的 api_key 把真实值覆盖为空
    if "api_key" in updates and str(updates["api_key"]).startswith("•"):
        updates.pop("api_key")

    # 校验温度
    if "temperature" in updates:
        updates["temperature"] = round(float(updates["temperature"]), 2)

    cfg = await _load_cfg(session, "llm")
    if cfg is None:
        cfg = SystemConfig(
            key="llm",
            value=updates,
            description="LLM 模型配置（OpenAI 兼容协议）",
        )
        session.add(cfg)
    else:
        merged = dict(cfg.value or {})
        merged.update(updates)
        cfg.value = merged

    cfg.updated_by = admin.id
    await session.commit()
    await session.refresh(cfg)

    # 清掉 LLM service 的客户端缓存
    llm_service._client_cache.clear()
    logger.info("LLM 配置更新：admin={}, fields={}", admin.id, list(updates.keys()))
    await log_operation(
        session=session,
        operator=admin,
        action="update_llm_config",
        target_type="config",
        target_id="llm",
        summary=f"更新 LLM 配置（{len(updates)} 项：{', '.join(updates.keys())}）",
        details={"updated_fields": list(updates.keys())},
    )

    return await get_llm_config(_admin=admin, session=session)


@router.post("/configs/llm/test", response_model=TestConnectionResult, summary="测试 LLM 连接")
async def test_llm_connection(
    body: LLMConfigUpdate | None = None,
    admin: Annotated[User, Depends(require_admin)] = None,
) -> TestConnectionResult:
    """测试当前（或表单中临时编辑的）LLM 配置连通性。"""
    cfg_override: dict[str, Any] | None = None
    if body:
        cfg_override = body.model_dump(exclude_none=True)
        if "api_key" in cfg_override and str(cfg_override["api_key"]).startswith("•"):
            cfg_override.pop("api_key")

    result = await llm_service.test_connection(cfg_override)
    logger.info("LLM 测试连接 by admin={}: ok={}", admin.id, result.get("ok"))
    await log_operation(
        operator=admin,
        action="test_llm_connection",
        target_type="config",
        target_id="llm",
        summary=f"测试 LLM 连接：{'成功' if result.get('ok') else '失败'}",
        details=result,
    )
    return TestConnectionResult(**result)


# ============ AI 限流配置 ============

@router.get("/configs/ai-limits", response_model=AILimitsConfig, summary="获取 AI 限流配置")
async def get_ai_limits(
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AILimitsConfig:
    cfg = await _load_cfg(session, "ai_limits")
    if cfg is None:
        # 首次访问 seed 默认
        cfg = SystemConfig(
            key="ai_limits",
            value=AILimitsConfig().model_dump(),
            description="AI 调用限流",
        )
        session.add(cfg)
        await session.commit()
        await session.refresh(cfg)
    base = AILimitsConfig().model_dump()
    if isinstance(cfg.value, dict):
        base.update(cfg.value)
    return AILimitsConfig(**base)


@router.put("/configs/ai-limits", response_model=AILimitsConfig, summary="更新 AI 限流配置")
async def update_ai_limits(
    body: AILimitsConfig,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AILimitsConfig:
    cfg = await _load_cfg(session, "ai_limits")
    if cfg is None:
        cfg = SystemConfig(
            key="ai_limits",
            value=body.model_dump(),
            description="AI 调用限流",
        )
        session.add(cfg)
    else:
        cfg.value = body.model_dump()
    cfg.updated_by = admin.id
    await session.commit()
    logger.info("AI 限流更新：admin={}, value={}", admin.id, body.model_dump())
    await log_operation(
        session=session,
        operator=admin,
        action="update_ai_limits",
        target_type="config",
        target_id="ai_limits",
        summary=f"更新 AI 限流（每日 {body.per_user_per_day} / 每分钟 {body.per_user_per_minute}）",
        details=body.model_dump(),
    )
    return body


# ============ 健康检查（admin 域） ============

@router.get("/ping", summary="admin 鉴权探针")
async def admin_ping(
    admin: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """用于前端验证 admin 鉴权是否正常。"""
    return {"ok": True, "user_id": admin.id, "role": admin.role}


# ============ 工具函数 ============

async def _load_cfg(session: AsyncSession, key: str) -> SystemConfig | None:
    result = await session.execute(
        select(SystemConfig).where(SystemConfig.key == key)
    )
    return result.scalar_one_or_none()
