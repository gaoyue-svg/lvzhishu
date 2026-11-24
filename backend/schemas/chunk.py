"""本文件定义知识 Chunk 列表与详情接口的响应结构。"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChunkDetailResponse(BaseModel):
    """Chunk 详情响应。"""

    id: int
    document_id: int
    kb_id: int
    chunk_index: int
    parent_chunk_id: str | None
    chunk_type: str
    chunk_level: str | None
    chunk_subtype: str | None
    text: str
    token_count: int
    metadata: dict[str, Any] | None = Field(
        default=None,
        validation_alias="metadata_",
        serialization_alias="metadata",
    )
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class PaginatedChunkResponse(BaseModel):
    """分页 Chunk 列表响应。"""

    items: list[ChunkDetailResponse]
    total: int
    page: int
    page_size: int
