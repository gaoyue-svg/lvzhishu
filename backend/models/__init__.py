"""本文件集中导出 SQLAlchemy ORM 基类和全部数据模型。"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


from backend.models.chat_upload import ChatUpload  # noqa: E402
from backend.models.conversation import Conversation, LegalMemory, Message  # noqa: E402
from backend.models.contract import ContractRisk  # noqa: E402
from backend.models.harness import AgentRunTrace, EvaluationResult, LlmUsage  # noqa: E402
from backend.models.knowledge import KnowledgeBase, KnowledgeChunk, KnowledgeDocument  # noqa: E402
from backend.models.llm_config import UserLlmConfig  # noqa: E402
from backend.models.task import RagTrace, TaskLog  # noqa: E402
from backend.models.user import User  # noqa: E402

__all__ = [
    "AgentRunTrace",
    "Base",
    "ChatUpload",
    "ContractRisk",
    "Conversation",
    "EvaluationResult",
    "KnowledgeBase",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "LegalMemory",
    "LlmUsage",
    "Message",
    "RagTrace",
    "TaskLog",
    "User",
    "UserLlmConfig",
]
