"""本文件定义知识文档上传、列表与详情接口的响应结构。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentUploadResponse(BaseModel):
    """文档被受理进入解析后的响应。"""

    document_id: int
    filename: str
    file_size: int
    oss_url: str
    parse_status: str


class DocumentDetailResponse(BaseModel):
    """文档详情响应。"""

    id: int
    kb_id: int
    filename: str
    file_type: str
    file_size: int
    oss_url: str
    parse_status: str
    embedding_status: str
    embedding_count: int
    embedding_failed_count: int
    error_message: str | None
    chunk_count: int
    version: str | None
    effective_date: int | None
    is_latest: bool
    superseded_by_document_id: int | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentMarkdownResponse(BaseModel):
    """文档 Markdown 原文响应。"""

    document_id: int
    filename: str
    raw_markdown: str | None


class PaginatedDocumentResponse(BaseModel):
    """分页文档列表响应。"""

    items: list[DocumentDetailResponse]
    total: int
    page: int
    page_size: int
