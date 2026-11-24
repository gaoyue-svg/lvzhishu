"""本文件定义 Retrieval Lab 调试检索、结果列表与历史 Trace 的 API Schema。"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RewriteResult(BaseModel):
    """查询重写的 API 表示。"""

    original_query: str
    legal_query: str
    keyword_query: str
    entity_list: list[str] = Field(default_factory=list)


class QueryIntent(BaseModel):
    """查询意图和动态权重的 API 表示。"""

    intent_type: str
    weights: dict[str, float] = Field(default_factory=dict)
    rerank_weights: dict[str, float] = Field(default_factory=dict)
    filters: dict[str, Any] = Field(default_factory=dict)


class RetrieveDebugRequest(BaseModel):
    """调试检索请求。"""

    query: str = Field(min_length=1, max_length=2000)
    kb_ids: list[str] = Field(min_length=1, max_length=10)
    agent_type: str = Field(default="law_qa", max_length=30)
    top_k: int = Field(default=8, ge=1, le=20)


class ChunkResultItem(BaseModel):
    """包含检索分数、法律 metadata 与原文定位信息的 Chunk 结果。"""

    chunk_id: str
    text: str
    score: float = 0.0
    bm25_score: float | None = None
    milvus_score: float | None = None
    chunk_type: str | None = None
    chunk_subtype: str | None = None
    chunk_level: str | None = None
    article_no: str | None = None
    law_name: str | None = None
    hierarchy_path: str | None = None
    legal_level: str | None = None
    version: str | None = None
    is_latest: bool | None = None
    page_start: int | None = None
    page_end: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    source_uri: str | None = None
    metadata: dict[str, Any] | None = None


class RetrieveDebugResponse(BaseModel):
    """完整调试检索链路响应。"""

    trace_id: str
    original_query: str
    rewritten_query: RewriteResult | None = None
    query_intent: QueryIntent | None = None
    bm25_results: list[ChunkResultItem] = Field(default_factory=list)
    milvus_results: list[ChunkResultItem] = Field(default_factory=list)
    merged_results: list[ChunkResultItem] = Field(default_factory=list)
    reranked_results: list[ChunkResultItem] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    context_text: str | None = None
    latency_ms: dict[str, int] = Field(default_factory=dict)


class RetrieveHistoryItem(BaseModel):
    """法规检索页面的持久化历史记录摘要。"""

    trace_id: str
    query: str
    hit_count: int
    total_latency_ms: int
    intent_type: str | None = None
    created_at: datetime


class RetrieveTraceResponse(BaseModel):
    """从数据库恢复的完整检索链路 Trace。"""

    trace_id: str
    original_query: str
    rewritten_query: RewriteResult | None = None
    query_intent: QueryIntent | None = None
    bm25_raw_query: str | None = None
    bm25_results: list[ChunkResultItem] | None = None
    bm25_latency_ms: int | None = None
    milvus_query_vector_dim: int | None = None
    milvus_filter_expr: str | None = None
    milvus_results: list[ChunkResultItem] | None = None
    milvus_latency_ms: int | None = None
    rrf_weights: dict[str, float] | None = None
    merged_results: list[ChunkResultItem] | None = None
    merge_latency_ms: int | None = None
    rerank_weights: dict[str, float] | None = None
    reranked_results: list[ChunkResultItem] | None = None
    rerank_latency_ms: int | None = None
    citations: list[dict[str, Any]] | None = None
    context_text: str | None = None
    context_token_count: int | None = None
    total_latency_ms: int
    created_at: datetime
