"""本文件定义知识库、知识文档与知识 Chunk 的 ORM 模型。"""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, JSON, String, Text, text as sql_text
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from backend.models import Base


class KnowledgeBase(Base):
    """知识库表,映射自 sql/init.sql。"""

    __tablename__ = "knowledge_base"
    __table_args__ = {"comment": "知识库表"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="知识库ID")
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="所属用户ID")
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="知识库名称")
    description: Mapped[str | None] = mapped_column(Text, default=None, comment="描述")
    kb_type: Mapped[str] = mapped_column(String(30), nullable=False, comment="类型: law / case / judicial / contract / enterprise")
    embedding_model: Mapped[str | None] = mapped_column(String(100), server_default=sql_text("'bge-large-zh-v1.5'"), comment="绑定的Embedding模型")
    rerank_model: Mapped[str | None] = mapped_column(String(100), default=None, comment="绑定的Rerank模型")
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("500"), comment="Chunk大小(tokens)")
    chunk_overlap: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("50"), comment="Chunk重叠(tokens)")
    doc_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"), comment="文档数量(冗余计数)")
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"), comment="Chunk数量(冗余计数)")
    total_size: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=sql_text("0"), comment="总文件大小(字节)")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=sql_text("'enabled'"), comment="状态: enabled / disabled")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=sql_text("CURRENT_TIMESTAMP"), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=sql_text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="更新时间")


class KnowledgeDocument(Base):
    """知识库文档表,映射自 sql/init.sql。"""

    __tablename__ = "knowledge_document"
    __table_args__ = {"comment": "知识库文档表"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="文档ID")
    kb_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="所属知识库ID")
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="上传用户ID")
    filename: Mapped[str] = mapped_column(String(255), nullable=False, comment="原始文件名")
    file_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="文件类型: pdf / docx / xlsx / txt / image / html")
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=sql_text("0"), comment="文件大小(字节)")
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, comment="SHA256摘要，用于去重")
    oss_bucket: Mapped[str] = mapped_column(String(100), nullable=False, comment="OSS Bucket名称")
    oss_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True, comment="OSS对象Key（存储路径）")
    oss_url: Mapped[str] = mapped_column(String(500), nullable=False, comment="OSS访问URL")
    raw_markdown: Mapped[str | None] = mapped_column(MEDIUMTEXT, default=None, comment="解析后的Markdown原文")
    parse_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=sql_text("'pending'"), comment="解析状态: pending / parsing / completed / failed")
    embedding_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=sql_text("'pending'"), comment="向量化状态: pending / processing / completed / partial_failed / failed")
    embedding_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"), comment="Embedding成功数量")
    embedding_failed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"), comment="Embedding失败数量")
    error_message: Mapped[str | None] = mapped_column(Text, default=None, comment="失败原因")
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"), comment="Chunk数量")
    version: Mapped[str | None] = mapped_column(String(20), default=None, comment="文档版本号")
    effective_date: Mapped[int | None] = mapped_column(Integer, default=None, comment="生效日期Unix时间戳")
    is_latest: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sql_text("1"), comment="是否最新有效版本")
    superseded_by_document_id: Mapped[int | None] = mapped_column(BigInteger, default=None, comment="替代当前文档的文档ID")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=sql_text("CURRENT_TIMESTAMP"), comment="上传时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=sql_text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="更新时间")


class KnowledgeChunk(Base):
    """知识库 Chunk 表,映射自 sql/init.sql。"""

    __tablename__ = "knowledge_chunk"
    __table_args__ = {"comment": "知识库Chunk表"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="Chunk ID")
    document_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="所属文档ID")
    kb_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="所属知识库ID")
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, comment="Chunk序号(从0开始)")
    parent_chunk_id: Mapped[str | None] = mapped_column(String(128), default=None, comment="父级Chunk稳定ID")
    chunk_type: Mapped[str] = mapped_column(String(30), nullable=False, server_default=sql_text("'law'"), comment="Chunk大类")
    chunk_level: Mapped[str | None] = mapped_column(String(32), default=None, comment="Chunk层级")
    chunk_subtype: Mapped[str | None] = mapped_column(String(64), default=None, comment="Chunk子类型")
    text: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False, comment="Chunk原文")
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"), comment="Token数量")
    vector_id: Mapped[str | None] = mapped_column(String(100), default=None, comment="Milvus向量ID")
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON, default=None, comment="扩展元数据(法条信息、案由、关键词等)")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=sql_text("CURRENT_TIMESTAMP"), comment="创建时间")
Index("uk_doc_chunk", KnowledgeChunk.document_id, KnowledgeChunk.chunk_index, unique=True)
Index("idx_parent_chunk_id", KnowledgeChunk.parent_chunk_id)
