"""ORM 模型集合。

新增模型时：
1. 在本目录下创建新文件，定义类继承 `Base`
2. 在本文件导入（alembic 通过 `Base.metadata` 自动发现）
3. 在 `app/schemas/` 下添加对应的 Pydantic schema
4. 在 `app/api/v1/` 下添加路由
"""

from app.db.models.ai_call_log import AiCallLog
from app.db.models.banner import Banner
from app.db.models.conversation import Conversation
from app.db.models.exercise import Exercise
from app.db.models.exercise_review import ExerciseReview
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.knowledge_document import KnowledgeDocument
from app.db.models.message import Message
from app.db.models.operation_log import OperationLog
from app.db.models.plan import Plan
from app.db.models.plan_template import PlanTemplate
from app.db.models.system_config import SystemConfig
from app.db.models.training_record import TrainingRecord
from app.db.models.trace_span import TraceSpan
from app.db.models.user import User
from app.db.models.weight_log import WeightLog

__all__ = [
    "AiCallLog",
    "Banner",
    "Conversation",
    "Exercise",
    "ExerciseReview",
    "KnowledgeBase",
    "KnowledgeDocument",
    "Message",
    "OperationLog",
    "Plan",
    "PlanTemplate",
    "SystemConfig",
    "TrainingRecord",
    "TraceSpan",
    "User",
    "WeightLog",
]