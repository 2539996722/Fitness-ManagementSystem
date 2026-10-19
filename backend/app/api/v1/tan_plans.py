"""谭师训练计划路由（三分化 / 四分化）。

数据源：backend/data/tan_plans.json（从 dataset/actions_full.json
的 training_profile.arrangements 字段反推生成）。
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/tan-plans", tags=["谭师训练计划"])

# ============ 数据加载（模块级缓存） ============
_DATA_PATH = Path(__file__).resolve().parents[3] / "data" / "tan_plans.json"
_PLANS: dict = {}
_LOADED = False


def _load() -> None:
    global _PLANS, _LOADED
    if _LOADED:
        return
    if not _DATA_PATH.exists():
        raise FileNotFoundError(f"谭师训练计划数据未找到：{ _DATA_PATH }")
    with _DATA_PATH.open("r", encoding="utf-8") as f:
        _PLANS = json.load(f)
    _LOADED = True


def _plan_summary(p: dict) -> dict:
    """返回不含完整 actions 列表的摘要（用于侧边栏列表）。"""
    return {
        "name": p["name"],
        "days_count": len(p["days"]),
        "total_actions": p["total_actions"],
        "days": [
            {"day": d["day"], "count": d["count"]}
            for d in p["days"]
        ],
    }


@router.get("", summary="所有训练计划列表（侧边栏用）")
async def list_tan_plans():
    _load()
    return {"plans": [_plan_summary(p) for p in _PLANS.values()]}


@router.get("/{plan_name}", summary="单个计划完整内容（含每天动作）")
async def get_tan_plan(plan_name: str):
    _load()
    if plan_name not in _PLANS:
        raise HTTPException(status_code=404, detail=f"训练计划不存在：{ plan_name }")
    return _PLANS[plan_name]
