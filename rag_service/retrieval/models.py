"""本文件定义检索链路内部传递使用的数据对象，与 API Schema 保持解耦。"""

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class RewriteResult:
    """保存查询重写产生的语义查询、关键词查询与实体。"""

    original_query: str
    legal_query: str
    keyword_query: str
    entity_list: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换为可写入 JSON 的字典。"""
        return asdict(self)


@dataclass
class QueryIntent:
    """保存查询意图、检索权重、重排权重与结构化过滤条件。"""

    intent_type: str
    weights: dict[str, float] = field(default_factory=dict)
    rerank_weights: dict[str, float] = field(default_factory=dict)
    filters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为可写入 JSON 的字典。"""
        return asdict(self)


@dataclass
class ChunkHit:
    """表示来自 BM25、Milvus 或融合阶段的一条 Chunk 命中。"""

    chunk_id: str
    text: str
    bm25_score: float | None = None
    milvus_score: float | None = None
    milvus_distance: float | None = None
    rrf_score: float = 0.0
    final_score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """展开 metadata 常用字段并返回可序列化字典。"""
        result = asdict(self)
        result.update(self.metadata)
        result["score"] = self.final_score or self.rrf_score
        return result


@dataclass
class RetrievalResult:
    """保存完整检索结果及调试 Trace。"""

    chunks: list[ChunkHit]
    citations: list[dict[str, Any]] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContextResult:
    """保存结构化上下文、引用编号映射和 token 统计。"""

    context_text: str
    citation_map: dict[int, dict[str, Any]]
    token_count: int
    chunk_count: int


@dataclass
class Citation:
    """表示一条可定位原文的法律引用。"""

    chunk_id: str
    law_name: str | None
    article_no: str | None
    hierarchy_path: str | None
    text: str
    score: float
    version: str | None
    effective_date: int | None
    page_start: int | None
    page_end: int | None
    char_start: int | None
    char_end: int | None
    source_uri: str | None
    # 完整 chunk 原文，供前端弹窗展示；text 为 200 字截断片段。
    full_text: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为可写入接口响应的字典。"""
        return asdict(self)
