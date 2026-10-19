"""谭师动作库 路由。

数据源：backend/data/tan_actions_full.json（来自 https://fitness.j1exanderspace.cn 的离线副本）。
端点：
- GET /tan-actions              列表（多维过滤）
- GET /tan-actions/{action_id}  单条详情
- GET /tan-actions/meta         元数据（含肌肉分组 / 动作类型）
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Response

router = APIRouter(prefix="/tan-actions", tags=["谭师动作库"])

# ============ 数据加载（模块级缓存） ============
_DATA_PATH = Path(__file__).resolve().parents[3] / "data" / "tan_actions_full.json"
_ACTIONS: list[dict] = []
_META: dict = {"bodies": [], "equipments": [], "muscle_groups": [], "action_types": [], "count": 0}
_LOADED = False

# ============ 一级 Tab 映射（前端 7 标签 → dataset body 枚举）============
BODY_TAB_MAP = {
    "胸部": "胸",
    "背部": "背",
    "肩部": "肩",
    "腿臀": "下肢",
    "手臂": "手臂",
    "腹部": "躯干",
    "全身": None,  # 不做 body 过滤
}
BODY_TABS = [{"key": k, "label": k, "body": v} for k, v in BODY_TAB_MAP.items()]

# ============ 二级 Tab 标签 ============
WARMUP_BODY = "热身与活动度"
WARMUP_TAB = {"key": "all", "label": "全部动作"}
WARMUP_TAB_WARM = {"key": "warmup", "label": "热身"}

# ============ 肌肉分组（细分部位，预定义枚举）============
# 每个组固定 3-5 个标准化子项；每个子项的 matchers 列表匹配所有相关肌肉字符串。
# 计数逻辑：动作的 explicit_muscles 中**任一**字符串包含任一 matcher 即算该子项命中。
MUSCLE_GROUPS = [
    {
        "key": "chest", "label": "胸",
        # 胸动作的细分部位按动作 id 精确分类（替代 matchers 字符串匹配）
        # 上胸=incline 类 + supported-low-cable-upper-chest-fly + incline-machine-chest-fly
        # 下胸=machine-lower-chest-fly + press
        # 中胸=其余胸动作
        "children": [
            {"key": "chest_upper", "label": "上胸", "actions": [
                "incline-machine-press", "incline-smith-machine-press",
                "incline-dumbbell-chest-press", "neutral-grip-incline-dumbbell-press",
                "supported-low-cable-upper-chest-fly", "incline-machine-chest-fly",
            ]},
            {"key": "chest_mid", "label": "中胸", "actions": [
                "cable-chest-fly", "barbell-bench-press", "pec-deck-chest-fly",
                "seated-machine-chest-press", "wall-chest-stretch",
                "cable-chest-activation-thumb-hook", "dumbbell-bench-press",
                "dumbbell-chest-fly",
            ]},
            {"key": "chest_lower", "label": "下胸", "actions": [
                "machine-lower-chest-fly-unconfirmed", "machine-lower-chest-press-unconfirmed",
            ]},
        ],
    },
    {
        "key": "back", "label": "背",
        "children": [
            {"key": "back_lat",    "label": "背阔肌", "matchers": ["背阔"], "hint": "背部外侧"},
            {"key": "back_rhom",   "label": "菱形肌", "matchers": ["菱形"], "hint": "两肩胛之间"},
            {"key": "back_trap_m", "label": "斜方肌中部", "matchers": ["斜方肌中", "斜方"], "hint": "中背"},
            {"key": "back_trap_l", "label": "斜方肌下部", "matchers": ["斜方肌下"], "hint": "中下背"},
            {"key": "back_teres",  "label": "大圆肌", "matchers": ["大圆"], "hint": "腋后侧"},
            {"key": "back_infras", "label": "冈下肌", "matchers": ["冈下"], "hint": "肩胛后侧"},
        ],
    },
    {
        "key": "shoulder", "label": "肩",
        "children": [
            {"key": "shoulder_front", "label": "前束", "matchers": ["三角肌前", "前束", "前肩", "前三角"]},
            {"key": "shoulder_mid",   "label": "中束", "matchers": ["三角肌中", "中束", "侧肩", "肩袖", "中三角", "肩部"]},
            {"key": "shoulder_rear",  "label": "后束", "matchers": ["三角肌后", "后束", "后肩", "后三角", "斜方", "菱形", "冈下", "小圆"]},
        ],
    },
    {
        "key": "leg", "label": "腿臀",
        "children": [
            {"key": "leg_quad",   "label": "股四头", "matchers": ["股四头", "股四"]},
            {"key": "leg_ham",    "label": "腘绳肌", "matchers": ["腘绳", "股二", "国绳"]},
            {"key": "leg_glute",  "label": "臀大肌", "matchers": ["臀大", "臀"]},
            {"key": "leg_adduct", "label": "内收肌", "matchers": ["内收", "耻骨", "大腿内收"]},
            {"key": "leg_calf",   "label": "小腿",   "matchers": ["小腿", "腓肠", "比目鱼", "胫"]},
        ],
    },
    {
        "key": "arm", "label": "手臂",
        "children": [
            {"key": "arm_biceps", "label": "肱二头", "matchers": ["肱二头", "二头"]},
            {"key": "arm_triceps","label": "肱三头", "matchers": ["肱三头", "三头"]},
            {"key": "arm_forearm","label": "前臂",   "matchers": ["前臂", "腕"]},
        ],
    },
    {
        "key": "abs", "label": "腹部",
        "children": [
            {"key": "abs_upper", "label": "上腹", "matchers": ["上腹", "腹直上"]},
            {"key": "abs_lower", "label": "下腹", "matchers": ["下腹"]},
            {"key": "abs_side",  "label": "侧腹", "matchers": ["腹斜", "侧腹", "腹外斜"]},
        ],
    },
]

# ============ 动作类型（力量训练 / 热身激活 / 拉伸放松）============
ACTION_TYPES = [
    {"key": "strength", "label": "力量训练"},   # body ∈ {胸/背/肩/手臂/下肢/躯干}
    {"key": "warmup",   "label": "热身激活"},   # body = 热身与活动度
    {"key": "stretch",  "label": "拉伸放松"},   # training.purpose 含 拉伸/放松
]


def _load() -> None:
    global _ACTIONS, _META, _LOADED
    if _LOADED:
        return
    if not _DATA_PATH.exists():
        raise FileNotFoundError(f"谭师动作库数据未找到：{ _DATA_PATH }")
    with _DATA_PATH.open("r", encoding="utf-8") as f:
        _ACTIONS = json.load(f)

    bodies = sorted({a.get("body", "") for a in _ACTIONS if a.get("body")})
    equipments: set[str] = set()
    for a in _ACTIONS:
        for e in a.get("equipment") or []:
            if e:
                equipments.add(e)

    # 计算肌肉分组计数（每个动作在该组下只算入第一个匹配子项，互斥）
    muscle_groups = []
    for grp in MUSCLE_GROUPS:
        child_hits: dict[str, int] = {c["key"]: 0 for c in grp["children"]}
        for a in _ACTIONS:
            aid = a.get("id")
            muscles = a.get("explicit_muscles") or []
            matched_child = None
            for c in grp["children"]:
                if "actions" in c:
                    if aid in c["actions"]:
                        matched_child = c
                        break
                elif "matchers" in c:
                    if any(any(m in (mm or "") for m in c["matchers"]) for mm in muscles):
                        matched_child = c
                        break
            if matched_child:
                child_hits[matched_child["key"]] += 1
        children_out = [
            {"key": c["key"], "label": c["label"], "hint": c.get("hint", ""), "count": child_hits[c["key"]]}
            for c in grp["children"]
        ]
        muscle_groups.append({
            "key": grp["key"],
            "label": grp["label"],
            "count": sum(child_hits.values()),
            "children": children_out,
        })

    # 动作类型计数
    action_types = []
    for t in ACTION_TYPES:
        if t["key"] == "strength":
            count = sum(
                1 for a in _ACTIONS
                if a.get("body") in {"胸", "背", "肩", "手臂", "下肢", "躯干"}
            )
        elif t["key"] == "warmup":
            count = sum(1 for a in _ACTIONS if a.get("body") == WARMUP_BODY)
        elif t["key"] == "stretch":
            count = sum(
                1 for a in _ACTIONS
                if "拉伸" in ((a.get("training") or {}).get("purpose") or "")
                or "放松" in ((a.get("training") or {}).get("purpose") or "")
            )
        else:
            count = 0
        action_types.append({"key": t["key"], "label": t["label"], "count": count})

    _META = {
        "bodies": bodies,
        "equipments": sorted(equipments),
        "muscle_groups": muscle_groups,
        "action_types": action_types,
        "body_tabs": BODY_TABS,         # 一级 Tab 配置
        "warmup_tabs": [WARMUP_TAB, WARMUP_TAB_WARM],  # 二级 Tab 配置
        "count": len(_ACTIONS),
    }
    _LOADED = True


def _to_card(a: dict) -> dict:
    """列表用：缩略 + 名称 + 部位 + 器械 + 摘要。"""
    media = a.get("media") or {}
    guide = a.get("guide") or {}
    return {
        "id": a.get("id"),
        "name": a.get("name"),
        "body": a.get("body"),
        "equipment": a.get("equipment") or [],
        "thumbnail": media.get("src"),
        "creator": media.get("creator"),
        "summary": guide.get("summary") or "",
        "availability": guide.get("availability"),
    }


def _match_muscle_group(action: dict, group_key: str) -> bool:
    """判断动作是否属于指定肌肉子项（group_key 是子项 key）。"""
    aid = action.get("id")
    for grp in MUSCLE_GROUPS:
        for child in grp["children"]:
            if child["key"] == group_key:
                if "actions" in child:
                    return aid in child["actions"]
                if "matchers" in child:
                    muscles = action.get("explicit_muscles") or []
                    return any(any(m in (mm or "") for m in child["matchers"]) for mm in muscles)
    return False


def _match_action_type(action: dict, type_key: str) -> bool:
    """判断动作是否属于指定动作类型。"""
    if type_key == "strength":
        return action.get("body") in {"胸", "背", "肩", "手臂", "下肢", "躯干"}
    if type_key == "warmup":
        return action.get("body") == WARMUP_BODY
    if type_key == "stretch":
        purpose = (action.get("training") or {}).get("purpose") or ""
        return "拉伸" in purpose or "放松" in purpose
    return False


@router.get("", summary="谭师动作库列表（多维过滤）")
async def list_tan_actions(
    body: Optional[str] = Query(None, description="按 body 过滤（dataset 原值，如 胸/背/肩）"),
    warmup: Optional[bool] = Query(False, description="True 时只返回热身与活动度（忽略 body）"),
    equipment: Optional[str] = Query(None, description="按器械过滤（包含匹配）"),
    q: Optional[str] = Query(None, description="搜索关键字（name + equipment + muscles）"),
    muscle_group: Optional[str] = Query(None, description="肌肉分组 key（chest/back/shoulder/arm/leg/abs/other）"),
    action_type: Optional[str] = Query(None, description="动作类型（strength/warmup/stretch）"),
    limit: int = Query(60, ge=1, le=300),
    offset: int = Query(0, ge=0),
):
    _load()
    items = _ACTIONS

    # warmup 模式覆盖 body 过滤
    if warmup:
        items = [a for a in items if a.get("body") == WARMUP_BODY]
    elif body:
        items = [a for a in items if a.get("body") == body]

    if equipment:
        items = [a for a in items if any(equipment in (e or "") for e in (a.get("equipment") or []))]

    if muscle_group:
        items = [a for a in items if _match_muscle_group(a, muscle_group)]

    if action_type:
        items = [a for a in items if _match_action_type(a, action_type)]

    if q:
        kw = q.strip().lower()
        items = [
            a for a in items
            if kw in (a.get("name") or "").lower()
            or any(kw in (al or "").lower() for al in (a.get("aliases") or []))
            or any(kw in (e or "").lower() for e in (a.get("equipment") or []))
            or any(kw in (m or "").lower() for m in (a.get("explicit_muscles") or []))
        ]

    total = len(items)
    items = items[offset : offset + limit]
    return {
        "total": total,
        "items": [_to_card(a) for a in items],
    }


@router.get("/meta", summary="元数据：bodies/equipments/muscle_groups/action_types + Tab 配置")
async def tan_actions_meta(
    response: Response,
    body: Optional[str] = Query(None, description="按 body 过滤 equipments/action_types 的统计"),
):
    response.headers["Cache-Control"] = "no-store"
    _load()
    # 默认全量
    equipments_full = sorted({
        e for a in _ACTIONS for e in (a.get("equipment") or []) if e
    })
    action_types_full = _META["action_types"]
    if not body:
        return _META

    # 按 body 过滤：equipments 统计每个器械在 body 范围内的出现次数
    body_equip_count: dict[str, int] = {}
    for a in _ACTIONS:
        if a.get("body") != body:
            continue
        for e in (a.get("equipment") or []):
            if e:
                body_equip_count[e] = body_equip_count.get(e, 0) + 1
    equipments_filtered = [
        {"key": e, "label": e, "count": c}
        for e, c in sorted(body_equip_count.items(), key=lambda x: -x[1])
    ]
    # action_types 重新按 body 统计
    action_types_filtered = []
    for t in ACTION_TYPES:
        if t["key"] == "strength":
            count = sum(1 for a in _ACTIONS if a.get("body") == body and a.get("body") in {"胸", "背", "肩", "手臂", "下肢", "躯干"})
        elif t["key"] == "warmup":
            count = sum(1 for a in _ACTIONS if a.get("body") == body and a.get("body") == WARMUP_BODY)
        elif t["key"] == "stretch":
            count = sum(1 for a in _ACTIONS if a.get("body") == body and (
                "拉伸" in ((a.get("training") or {}).get("purpose") or "")
                or "放松" in ((a.get("training") or {}).get("purpose") or "")
            ))
        else:
            count = 0
        action_types_filtered.append({"key": t["key"], "label": t["label"], "count": count})

    # muscle_groups 全数据集统计：每个动作在该 group 下只算入第一个匹配到的子项
    muscle_groups_filtered = []
    for grp in MUSCLE_GROUPS:
        child_hits: dict[str, int] = {c["key"]: 0 for c in grp["children"]}
        for a in _ACTIONS:
            aid = a.get("id")
            muscles = a.get("explicit_muscles") or []
            matched_child = None
            for c in grp["children"]:
                if "actions" in c:
                    # 动作 id 精确分类
                    if aid in c["actions"]:
                        matched_child = c
                        break
                elif "matchers" in c:
                    if any(any(m in (mm or "") for m in c["matchers"]) for mm in muscles):
                        matched_child = c
                        break
            if matched_child:
                child_hits[matched_child["key"]] += 1
        children_out = [
            {
                "key": c["key"],
                "label": c["label"],
                "hint": c.get("hint", ""),
                "count": child_hits[c["key"]],
            }
            for c in grp["children"]
        ]
        muscle_groups_filtered.append({
            "key": grp["key"],
            "label": grp["label"],
            "count": sum(child_hits.values()),
            "children": children_out,
        })

    return {
        **_META,
        "equipments": equipments_filtered,
        "action_types": action_types_filtered,
        "muscle_groups": muscle_groups_filtered,
    }


@router.get("/{action_id}", summary="谭师动作库详情")
async def get_tan_action(action_id: str):
    _load()
    for a in _ACTIONS:
        if a.get("id") == action_id:
            return a
    raise HTTPException(status_code=404, detail=f"动作不存在：{action_id}")
