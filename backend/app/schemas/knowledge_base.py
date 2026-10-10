"""KB schemas。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeBaseCreate(BaseModel):
    """新建 KB。"""

    name: str = Field(..., min_length=1, max_length=64, description="KB 名称（唯一）")
    description: str | None = Field(None, max_length=255)
    enabled: bool = True
    chunk_size: int = Field(500, ge=100, le=4000)
    chunk_overlap: int = Field(80, ge=0, le=1000)
    top_k: int = Field(5, ge=1, le=20)
    similarity_threshold: float = Field(0.0, ge=0.0, le=1.0)


class KnowledgeBaseUpdate(BaseModel):
    """更新 KB。"""

    name: str | None = Field(None, min_length=1, max_length=64)
    description: str | None = Field(None, max_length=255)
    enabled: bool | None = None
    chunk_size: int | None = Field(None, ge=100, le=4000)
    chunk_overlap: int | None = Field(None, ge=0, le=1000)
    top_k: int | None = Field(None, ge=1, le=20)
    similarity_threshold: float | None = Field(None, ge=0.0, le=1.0)


class KnowledgeBaseOut(BaseModel):
    """KB 响应（含文档数）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None
    enabled: bool
    chunk_size: int
    chunk_overlap: int
    top_k: int
    similarity_threshold: float
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime
    document_count: int = 0
    chunk_count: int = 0


class KnowledgeBaseListOut(BaseModel):
    items: list[KnowledgeBaseOut]
    total: int


class KnowledgeDocumentOut(BaseModel):
    """KB 文档响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    kb_id: int
    filename: str
    ext: str | None = None
    size_bytes: int
    status: str
    chunk_count: int
    error_message: str | None = None
    uploaded_by: int | None = None
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentListOut(BaseModel):
    items: list[KnowledgeDocumentOut]
    total: int


class KnowledgeDocumentUploadOut(BaseModel):
    """上传文档后返回（一次性预览）。"""

    document: KnowledgeDocumentOut
    chunk_count: int
    first_preview: str


class RetrievalTestIn(BaseModel):
    """KB 检索测试（admin 调试用）。"""

    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int | None = Field(None, ge=1, le=20)


class KnowledgeDocumentChunksOut(BaseModel):
    """文档分片预览（KB 调试用）。"""

    doc_id: int
    kb_id: int
    filename: str
    chunks: list[dict]  # [{chunk_index, text, char_count}, ...]
    total_chars: int
    chunk_size: int  # KB 配置的 chunk_size，用于前端算百分比


class RetrievalTestOut(BaseModel):
    query: str
    chunks: list[dict]