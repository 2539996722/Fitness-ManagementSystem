"""B 端数据看板 schema（PRD §5.2.3）。"""

from pydantic import BaseModel


class MetricsOut(BaseModel):
    """顶部 6 张 KPI 卡。"""

    total_users: int = 0
    today_new_users: int = 0
    dau: int = 0
    ai_total: int = 0
    ai_today: int = 0
    human_total: int = 0
    human_pending: int = 0


class TrendPoint(BaseModel):
    date: str  # YYYY-MM-DD
    count: int


class TrendResponse(BaseModel):
    points: list[TrendPoint]


class NamedCount(BaseModel):
    name: str
    count: int


class DistributionResponse(BaseModel):
    items: list[NamedCount]
