"""本文件定义异步任务日志与 RAG 检索链路 Trace 的 ORM 模型。"""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Integer, JSON, String, Text, text as sql_text
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from backend.models import Base


class TaskLog(Base):
    """异步任务日志表,映射自 sql/init.sql。"""

    __tablename__ = "task_log"
    __table_args__ = {"comment": "Async task log table"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_type: Mapped[str] = mapped_column(String(30), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(50), default=None)
    resource_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    user_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=sql_text("'pending'"))
    input_params: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    output_result: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=sql_text("CURRENT_TIMESTAMP"))


class RagTrace(Base):
    """记录调试检索接口每一步输入、输出和耗时。"""

    __tablename__ = "rag_trace"
    __table_args__ = {"comment": "RAG检索链路Trace表"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    conversation_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    user_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    agent_type: Mapped[str | None] = mapped_column(String(30), default=None)
    original_query: Mapped[str] = mapped_column(Text, nullable=False)
    rewritten_query: Mapped[str | None] = mapped_column(Text, default=None)
    expanded_queries: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    bm25_results: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, default=None)
    milvus_results: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, default=None)
    merged_results: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, default=None)
    reranked_results: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, default=None)
    final_context: Mapped[str | None] = mapped_column(MEDIUMTEXT, default=None)
    citation_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))
    total_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))
    retrieval_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=sql_text("CURRENT_TIMESTAMP"))
