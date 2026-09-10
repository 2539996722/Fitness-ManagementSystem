"""Pydantic 数据校验 schema。"""

from app.schemas.auth import LoginIn, RefreshIn, RegisterIn, TokenOut
from app.schemas.chat import (
    ChatMessageIn,
    ChatMessageOut,
    ConversationCreateIn,
    ConversationListItem,
    ConversationOut,
    MessageOut,
)
from app.schemas.exercise import (
    ExerciseFilterOptions,
    ExerciseListResponse,
    ExerciseOut,
)
from app.schemas.plan import (
    PlanCreate,
    PlanDay,
    PlanExerciseItem,
    PlanListItem,
    PlanOut,
    PlanUpdate,
    PlanWeek,
    TrainingRecordIn,
    TrainingRecordOut,
)
from app.schemas.system_config import (
    AILimitsConfig,
    LLMConfig,
    LLMConfigUpdate,
    SystemConfigListItem,
    SystemConfigOut,
    TestConnectionResult,
)
from app.schemas.user import UserCreate, UserOut

__all__ = [
    "LoginIn",
    "RefreshIn",
    "RegisterIn",
    "TokenOut",
    "ExerciseOut",
    "ExerciseListResponse",
    "ExerciseFilterOptions",
    "UserOut",
    "UserCreate",
    "PlanCreate",
    "PlanUpdate",
    "PlanOut",
    "PlanListItem",
    "PlanWeek",
    "PlanDay",
    "PlanExerciseItem",
    "TrainingRecordIn",
    "TrainingRecordOut",
    "MessageOut",
    "ConversationOut",
    "ConversationCreateIn",
    "ConversationListItem",
    "ChatMessageIn",
    "ChatMessageOut",
    "LLMConfig",
    "LLMConfigUpdate",
    "AILimitsConfig",
    "SystemConfigOut",
    "SystemConfigListItem",
    "TestConnectionResult",
]