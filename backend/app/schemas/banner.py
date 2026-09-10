"""banners Pydantic schema。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BannerBase(BaseModel):
    title: str = Field(min_length=1, max_length=64)
    content: str = Field(min_length=1, max_length=500)
    link_url: str | None = Field(default=None, max_length=255)
    is_active: bool = True
    sort_order: int = Field(default=0, ge=0, le=999)
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class BannerCreate(BannerBase):
    pass


class BannerUpdate(BaseModel):
    """部分更新 - 所有字段可选。"""
    title: str | None = Field(default=None, min_length=1, max_length=64)
    content: str | None = Field(default=None, min_length=1, max_length=500)
    link_url: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=999)
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class BannerOut(BannerBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime | None = None
    updated_at: datetime | None = None