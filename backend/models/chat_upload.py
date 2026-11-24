"""本文件定义会话临时上传文件（合同分析）的 ORM 模型。"""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, Integer, JSON, String, text as sql_text
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from backend.models import Base


class ChatUpload(Base):
    """会话临时上传文件表：聊天中上传的合同等文件经解析后落此表，供多 Agent 分析。

    不写入知识库（knowledge_document / knowledge_chunk），避免污染长期知识库；
    expires_at 到期后由清理逻辑删除。
    """

    __tablename__ = "chat_upload"
    __table_args__ = {"comment": "会话临时上传文件表"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="上传ID")
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="所属用户ID")
    conversation_id: Mapped[int | None] = mapped_column(BigInteger, default=None, comment="关联会话ID")
    filename: Mapped[str] = mapped_column(String(255), nullable=False, comment="原始文件名")
    file_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="文件类型: pdf / docx / txt / html / image")
    doc_type: Mapped[str] = mapped_column(String(30), nullable=False, server_default=sql_text("'contract'"), comment="业务文档类型: contract")
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=sql_text("0"), comment="文件大小(字节)")
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, comment="SHA256摘要")
    oss_bucket: Mapped[str | None] = mapped_column(String(100), default=None, comment="OSS Bucket")
    oss_key: Mapped[str | None] = mapped_column(String(500), default=None, comment="OSS对象Key")
    oss_url: Mapped[str | None] = mapped_column(String(500), default=None, comment="OSS存储地址")
    parse_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=sql_text("'pending'"), comment="解析状态: pending / parsing / completed / failed")
    parse_warnings: Mapped[list[str] | None] = mapped_column(JSON, default=None, comment="解析降级提示")
    raw_markdown: Mapped[str | None] = mapped_column(MEDIUMTEXT, default=None, comment="解析后的Markdown原文")
    clause_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"), comment="合同条款数量")
    analysis_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=sql_text("'pending'"), comment="分析状态: pending / running / completed / failed")
    analysis_report: Mapped[str | None] = mapped_column(MEDIUMTEXT, default=None, comment="分析最终报告(markdown)")
    analysis_summary: Mapped[str | None] = mapped_column(MEDIUMTEXT, default=None, comment="合同摘要")
    analysis_elements: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None, comment="合同要素结构化数据")
    analysis_risks: Mapped[list[Any] | None] = mapped_column(JSON, default=None, comment="风险清单结构化数据")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=sql_text("CURRENT_TIMESTAMP"), comment="创建时间")
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="过期时间(到期自动清理)")


Index("idx_chat_upload_user", ChatUpload.user_id)
Index("idx_chat_upload_conversation", ChatUpload.conversation_id)
