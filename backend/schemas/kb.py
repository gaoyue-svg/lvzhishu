"""知识库请求与响应相关 Schema。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CreateKBRequest(BaseModel):
    """创建知识库的请求体。"""

    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    kb_type: str = Field(pattern="^(law|case|judicial|contract|enterprise)$")
    embedding_model: str = "bge-large-zh-v1.5"
    chunk_size: int = Field(default=500, ge=100, le=2000)
    chunk_overlap: int = Field(default=50, ge=0, le=200)


class UpdateKBRequest(BaseModel):
    """更新知识库配置的请求体。"""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    chunk_size: int | None = Field(default=None, ge=100, le=2000)
    chunk_overlap: int | None = Field(default=None, ge=0, le=200)
    status: str | None = Field(default=None, pattern="^(enabled|disabled)$")


class KnowledgeBaseResponse(BaseModel):
    """知识库接口响应。"""

    id: int
    user_id: int
    name: str
    description: str | None
    kb_type: str
    embedding_model: str | None
    chunk_size: int
    chunk_overlap: int
    doc_count: int
    chunk_count: int
    total_size: int
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
