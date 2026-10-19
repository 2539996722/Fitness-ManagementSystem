"""谭师饮食模块路由。

数据源：从 dataset 的 videos_index.json 提取含"饮食/食物/营养"的视频，
加上对应动作的关联信息（前 2 个 actions 即可）。
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(prefix="/tan-diet", tags=["谭师饮食"])

# ============ 数据加载（模块级缓存） ============
# 优先从 backend/data 读（兼容部署环境）；否则回退到 dataset 原路径
_DATA_PATH = Path(__file__).resolve().parents[3] / "data" / "tan_actions_full.json"
_VIDEOS_PATH = Path(__file__).resolve().parents[3] / "data" / "videos_index.json"
if not _VIDEOS_PATH.exists():
    _VIDEOS_PATH = Path(__file__).resolve().parents[4] / "dataset" / "videos_index.json"
_ACTIONS: list[dict] = []
_VIDEOS: dict = {}
_LOADED = False


def _load() -> None:
    global _ACTIONS, _VIDEOS, _LOADED
    if _LOADED:
        return
    if _DATA_PATH.exists():
        with _DATA_PATH.open("r", encoding="utf-8") as f:
            _ACTIONS = json.load(f)
    if _VIDEOS_PATH.exists():
        with _VIDEOS_PATH.open("r", encoding="utf-8") as f:
            _VIDEOS = json.load(f)
    _LOADED = True


def _extract_diet_videos() -> list[dict]:
    """从 videos_index.json 提取含"饮食/食物/营养"关键词的视频。"""
    _load()
    out = []
    for vid, info in _VIDEOS.items():
        title = info.get("title", "")
        # 严格关键词：只匹配"饮食 / 食物 / 营养 / 减脂"（剔除"增肌"等训练相关）
        if not any(kw in title for kw in ["饮食", "食物", "营养", "减脂"]):
            continue
        url = info.get("url", "")
        if not url:
            if vid.startswith("BV"):
                url = f"https://www.bilibili.com/video/{vid}/"
            else:
                url = f"https://www.douyin.com/video/{vid}"
        # 关联动作（取前 2 个 references 对应的 action_id/name）
        related = []
        for ref in (info.get("references") or [])[:3]:
            aid = ref.get("action_id")
            if not aid: continue
            act = next((a for a in _ACTIONS if a.get("id") == aid), None)
            if act:
                related.append({
                    "action_id": aid,
                    "name": act.get("name", ""),
                    "body": act.get("body", ""),
                })
        # 计算时间戳：从 references 取中位 start
        starts = [r.get("start") for r in (info.get("references") or []) if r.get("start") is not None]
        ts = round(sum(starts) / len(starts)) if starts else None
        # 平台
        platform = "B站" if vid.startswith("BV") else "抖音"
        # 标题摘要（取第一句）
        desc = title.split("，")[0].split(",")[0].strip()[:60]
        out.append({
            "video_id": vid,
            "title": title,
            "platform": platform,
            "url": url + (f"?p={ts}" if ts and platform == "B站" and "?" not in url else ""),
            "timestamp": ts,
            "description": desc,
            "related_actions": related,
        })
    # 稳定排序：抖音优先（看起来更新）
    out.sort(key=lambda v: (v["platform"] != "抖音", v["video_id"]))
    return out


def _extract_diet_topics() -> list[dict]:
    """5 个饮食专题（按用户要求：4 个主要 + 1 个补充）。"""
    _load()
    return [
        {
            "id": "new-plan",
            "title": "新版饮食计划教程",
            "summary": "没脂肪硬减的一天再加胸部训练教学。结合减脂与训练目标，给出全天饮食与训练的整体安排。",
            "video_id": "7660136955972019877",
            "platform": "抖音",
            "url": "https://www.douyin.com/video/7660136955972019877",
            "related_count": 2,
        },
        {
            "id": "daily-log",
            "title": "完整饮食记录",
            "summary": "很多人要的完整饮食记录，可以参考一下；同时讲解胸部训练的动作细节。",
            "video_id": "BV11QLv6EEqd",
            "platform": "B站",
            "url": "https://www.bilibili.com/video/BV11QLv6EEqd/?p=574",
            "related_count": 4,
        },
        {
            "id": "holiday-cut",
            "title": "过年减脂大决战",
            "summary": "过年前的减脂实战指南，给出男女通用参考量。男士目标 7g/kg 碳水 / 5g/kg 蛋白 / 蔬果 500-800g。",
            "video_id": "BV15Di1BkEzE",
            "platform": "B站",
            "url": "https://www.bilibili.com/video/BV15Di1BkEzE/?p=614",
            "related_count": 6,
        },
        {
            "id": "rest-day",
            "title": "休息日饮食训练建议",
            "summary": "休息日的一些饮食和训练建议，讲解激活与主项的区别，以及挺胸但不顶肋等动作细节。",
            "video_id": "BV1cJv6BvEqt",
            "platform": "B站",
            "url": "https://www.bilibili.com/video/BV1cJv6BvEqt/?p=1028",
            "related_count": 11,
        },
        {
            "id": "cut-meal",
            "title": "减脂餐怎么吃",
            "summary": "减脂餐怎么吃一日三餐示例，强调先学会认识食物成分再逐渐形成日常吃法。",
            "video_id": "BV1E6ZVB1Eta",
            "platform": "B站",
            "url": "https://www.bilibili.com/video/BV1E6ZVB1Eta/?p=733",
            "related_count": 6,
        },
    ]


def _topic_with_related(topic: dict) -> dict:
    """丰富专题：补充关联动作 + 时间码。"""
    _load()
    vid = topic["video_id"]
    info = _VIDEOS.get(vid, {})
    refs = (info.get("references") or [])[:5]
    related = []
    for r in refs:
        aid = r.get("action_id")
        if not aid: continue
        act = next((a for a in _ACTIONS if a.get("id") == aid), None)
        if act:
            related.append({
                "action_id": aid,
                "name": act.get("name", ""),
                "body": act.get("body", ""),
                "label": r.get("label", ""),
                "start": r.get("start"),
                "end": r.get("end"),
            })
    starts = [r.get("start") for r in refs if r.get("start") is not None]
    ts = round(sum(starts) / len(starts)) if starts else None
    out = dict(topic)
    out["related_actions"] = related
    out["timestamp"] = ts
    if ts and topic["platform"] == "B站" and "?" not in out["url"]:
        out["url"] = f'{out["url"]}?p={ts}'
    return out


@router.get("", summary="饮食专题列表（侧边栏 4 主 + 1 辅）")
async def list_tan_diet():
    return {
        "topics": [_topic_with_related(t) for t in _extract_diet_topics()],
        "total": 5,
    }


@router.get("/{topic_id}", summary="饮食专题详情（点击专题卡片）")
async def get_tan_diet_topic(topic_id: str):
    for t in _extract_diet_topics():
        if t["id"] == topic_id:
            return _topic_with_related(t)
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail=f"饮食专题不存在：{ topic_id }")
