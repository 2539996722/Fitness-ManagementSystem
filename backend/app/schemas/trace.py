"""链路追踪 schema（M10+）。"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TraceSpanOut(BaseModel):
    """单阶段 span 返回。"""

    id: int
    request_id: str
    conversation_id: int | None = None
    user_id: int | None = None
    stage: str
    intent: str | None = None
    status: str
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    input_preview: str | None = None
    output_preview: str | None = None
    meta: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: datetime


class TraceListItemOut(BaseModel):
    """按 request_id 聚合后的轨迹摘要。"""

    request_id: str
    conversation_id: int | None = None
    user_id: int | None = None
    intent: str | None = None
    status: str = Field(description="全部 span success 才 success")
    total_latency_ms: int
    total_tokens: int
    span_count: int
    stage_names: list[str]
    started_at: datetime
    last_span_at: datetime


class TraceListOut(BaseModel):
    """链路追踪列表（含 total 便于分页）。"""

    items: list[TraceListItemOut]
    total: int
    limit: int
    offset: int


class TraceDetailOut(BaseModel):
    """单次请求的完整 span 时间线。"""

    request_id: str
    spans: list[TraceSpanOut]
    total_latency_ms: int
    total_tokens: int
    status: str