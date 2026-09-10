"""系统配置 schema（LLM、限流等运行时参数）。"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class LLMConfig(BaseModel):
    """LLM 模型配置。"""

    api_base: str = Field(default="", description="OpenAI 兼容 API Base URL，留空回退 .env")
    api_key: str = Field(default="", description="API Key，留空回退 .env")
    model_chat: str = Field(default="gpt-4o-mini", description="对话模型名")
    model_embed: str = Field(default="text-embedding-3-small", description="嵌入模型名")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="采样温度")
    max_tokens: int = Field(default=2048, ge=1, le=32000, description="单次回复最大 token")
    timeout: int = Field(default=60, ge=5, le=300, description="单次响应超时（秒）")
    system_prompt: str = Field(
        default="你是 FitHub 的 AI 健身教练 FitCoach，专业、友好、循证。请用简洁的中文回答，必要时给出可执行的训练建议。",
        description="系统提示词",
    )
    pricing: dict[str, float] = Field(
        default_factory=lambda: {"gpt-4o-mini": 0.001, "gpt-4o": 0.05},
        description="每 1k token 的人民币成本（key = 模型名），未匹配回退默认值",
    )

    @field_validator("temperature")
    @classmethod
    def _round_temp(cls, v: float) -> float:
        return round(v, 2)


class LLMConfigUpdate(BaseModel):
    """LLM 配置更新（所有字段可选）。"""

    api_base: str | None = None
    api_key: str | None = None
    model_chat: str | None = None
    model_embed: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=32000)
    timeout: int | None = Field(default=None, ge=5, le=300)
    system_prompt: str | None = None
    pricing: dict[str, float] | None = None


class AILimitsConfig(BaseModel):
    """AI 限流配置。"""

    per_user_per_day: int = Field(default=50, ge=1, le=10000)
    per_user_per_minute: int = Field(default=5, ge=1, le=1000)
    max_context_rounds: int = Field(default=5, ge=1, le=50)


class SystemConfigOut(BaseModel):
    """单个配置项返回。"""

    key: str
    value: dict[str, Any]
    description: str | None = None
    updated_by: int | None = None
    updated_at: datetime | None = None
    created_at: datetime | None = None

    # 标记敏感字段是否被遮蔽
    masked: list[str] = Field(default_factory=list)


class SystemConfigListItem(BaseModel):
    """配置列表项。"""

    key: str
    description: str | None = None
    updated_by: int | None = None
    updated_at: datetime | None = None


class TestConnectionResult(BaseModel):
    """测试连接结果。"""

    ok: bool
    message: str
    latency_ms: int | None = None
    model: str | None = None
