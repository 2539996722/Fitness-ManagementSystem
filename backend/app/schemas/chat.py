"""AI 助手 / 会话相关 schema。"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ConversationCreateIn(BaseModel):
    """新建会话请求体。"""

    title: Optional[str] = Field(None, max_length=64, description="会话标题（可空，后续自动生成）")


class MessageOut(BaseModel):
    """单条消息响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    sender_type: str = Field(..., description="user / ai / customer_service / trainer")
    sender_id: int | None = None
    content: str
    intent: str | None = None
    extra: dict = Field(default_factory=dict)
    created_at: datetime


class ConversationOut(BaseModel):
    """会话响应（含最新一条消息）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    title: str
    conversation_type: str
    status: str
    assigned_cs_id: int | None = None
    created_at: datetime
    updated_at: datetime


class ConversationListItem(BaseModel):
    """会话列表项（含最近一条消息预览）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    title: str
    status: str
    conversation_type: str
    created_at: datetime
    updated_at: datetime
    last_message: str | None = Field(None, description="最近一条消息的内容预览")
    unread: int = Field(0, description="未读消息数（M5 转人工后用）")


class ChatMessageIn(BaseModel):
    """发送消息请求。"""

    conversation_id: int | None = Field(None, description="空 = 新建会话")
    content: str = Field(..., min_length=1, max_length=4000)
    use_kb: bool = Field(default=True, description="是否启用知识库检索")


class ChatMessageOut(BaseModel):
    """AI 回复（流式输出场景下每 chunk 一条）。"""

    conversation_id: int
    message_id: int | None = None
    sender_type: str = "ai"
    content: str = ""
    intent: str | None = None
    done: bool = Field(False, description="是否本条流式结束")
    sources: list[dict] = Field(default_factory=list, description="RAG 引用源")
    extra: dict = Field(default_factory=dict, description="额外数据（如模板推荐列表）")