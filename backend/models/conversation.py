"""会话、消息与法律上下文记忆 ORM 模型。"""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Integer, JSON, String, Text, text as sql_text
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from backend.models import Base


class Conversation(Base):
    """会话表,映射自 sql/init.sql。"""

    __tablename__ = "conversation"
    __table_args__ = {"comment": "会话表"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="会话ID")
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="用户ID")
    kb_id: Mapped[int | None] = mapped_column(BigInteger, default=None, comment="关联的知识库ID(可选)")
    title: Mapped[str] = mapped_column(String(200), nullable=False, server_default=sql_text("'新的对话'"), comment="会话标题")
    agent_type: Mapped[str] = mapped_column(String(30), nullable=False, server_default=sql_text("'law_qa'"), comment="Agent类型: law_qa / case_analysis / contract_review / article_locate / document_generate")
    summary: Mapped[str | None] = mapped_column(Text, default=None, comment="AI生成的会话摘要")
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"), comment="消息数(冗余计数)")
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"), comment="累计Token消耗")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=sql_text("'active'"), comment="状态: active / archived")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=sql_text("CURRENT_TIMESTAMP"), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=sql_text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="更新时间")


class Message(Base):
    """消息表,映射自 sql/init.sql。"""

    __tablename__ = "message"
    __table_args__ = {"comment": "消息表"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="消息ID")
    conversation_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="所属会话ID")
    user_id: Mapped[int | None] = mapped_column(BigInteger, default=None, comment="用户ID(系统消息为null)")
    role: Mapped[str] = mapped_column(String(20), nullable=False, comment="角色: user / assistant / system")
    content: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False, comment="消息正文(Markdown)")
    citations: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None, comment="引用列表(assistant消息)")
    feedback: Mapped[str | None] = mapped_column(String(20), default=None, comment="用户反馈: like / dislike")
    feedback_comment: Mapped[str | None] = mapped_column(Text, default=None, comment="反馈备注")
    token_usage: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"), comment="本条Token消耗")
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"), comment="响应耗时(毫秒)")
    retrieval_trace_id: Mapped[str | None] = mapped_column(String(50), default=None, comment="关联检索Trace UUID")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=sql_text("CURRENT_TIMESTAMP"), comment="创建时间")


class LegalMemory(Base):
    """法律上下文记忆表,映射自 sql/init.sql。"""

    __tablename__ = "legal_memory"
    __table_args__ = {"comment": "法律上下文记忆表"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="记忆ID")
    conversation_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True, comment="所属会话ID")
    current_law: Mapped[str | None] = mapped_column(String(200), default=None, comment="当前讨论的法律")
    current_article: Mapped[str | None] = mapped_column(String(50), default=None, comment="当前讨论的法条")
    current_topic: Mapped[str | None] = mapped_column(String(200), default=None, comment="当前讨论的主题")
    mentioned_laws: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None, comment="对话中提及的法律列表")
    mentioned_articles: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None, comment="对话中引用的法条列表")
    user_facts: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None, comment="用户提供的事实要素")
    key_points: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None, comment="关键信息摘要")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=sql_text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="更新时间")
