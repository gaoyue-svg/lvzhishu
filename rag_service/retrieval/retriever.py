"""本文件编排 Query Rewrite、BM25、Milvus、RRF、MySQL 回查与规则重排。"""

from __future__ import annotations

import asyncio
from time import perf_counter
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.knowledge import KnowledgeChunk
from backend.utils.logger import get_logger
from .models import ChunkHit, RetrievalResult
from .query_rewrite import BaseQueryRewriter
from .reranker import RuleLegalReranker

logger = get_logger(__name__)


def _count_milvus_fallback() -> None:
    """统计 Milvus 降级为 BM25 的次数（Prometheus 埋点，best-effort）。"""
    try:
        from agent_service.metrics.registry import MILVUS_FALLBACK

        MILVUS_FALLBACK.inc()
    except Exception:  # noqa: BLE001
        pass


class EmbeddingClient(Protocol):
    """Retriever 需要的最小向量化接口，避免依赖具体 Embedding 服务实现。"""

    @property
    def dimension(self) -> int:
        """返回向量维度。"""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """将查询文本向量化。"""


class HybridRetriever:
    """实现文档规定的双路召回、RRF 融合、权威 metadata 回查和重排。"""

    def __init__(
        self,
        bm25,
        milvus,
        embedding: EmbeddingClient,
        reranker: RuleLegalReranker,
        query_rewriter: BaseQueryRewriter,
        query_router,
        db: AsyncSession,
    ):
        """注入所有可替换组件与当前数据库会话。"""
        self.bm25 = bm25
        self.milvus = milvus
        self.embedding = embedding
        self.reranker = reranker
        self.query_rewriter = query_rewriter
        self.query_router = query_router
        self.db = db

    async def retrieve(
        self,
        user_query: str,
        kb_ids: list[str] | None,
        top_k: int = 15,
        rerank_top_k: int = 8,
    ) -> RetrievalResult:
        """执行完整检索链路并返回最终 Chunk 与逐步 Trace。"""
        trace: dict[str, Any] = {"original_query": user_query}
        total_start = perf_counter()

        step_start = perf_counter()
        rewritten = await self.query_rewriter.rewrite(user_query)
        trace["rewrite_latency_ms"] = self._elapsed(step_start)
        trace["rewritten_query"] = rewritten.to_dict()

        step_start = perf_counter()
        intent = await self.query_router.route(user_query)
        trace["router_latency_ms"] = self._elapsed(step_start)
        trace["query_intent"] = intent.to_dict()

        source_top_k = max(15, min(top_k, 50))
        bm25_task = asyncio.create_task(
            self._search_bm25(rewritten.keyword_query, source_top_k, kb_ids, intent.filters)
        )
        milvus_task = asyncio.create_task(
            self._search_milvus(rewritten.legal_query, source_top_k, kb_ids, intent.filters)
        )
        (bm25_results, bm25_ms), (milvus_results, milvus_ms) = await asyncio.gather(
            bm25_task, milvus_task
        )
        trace["bm25_raw_query"] = rewritten.keyword_query
        trace["bm25_results"] = bm25_results
        trace["bm25_latency_ms"] = bm25_ms
        trace["milvus_results"] = milvus_results
        trace["milvus_latency_ms"] = milvus_ms
        trace["milvus_query_vector_dim"] = self.embedding.dimension
        trace["milvus_filter_expr"] = self._build_filter(kb_ids, intent.filters)

        step_start = perf_counter()
        merged = self._rrf_merge(bm25_results, milvus_results, intent.weights, limit=50)
        trace["merge_latency_ms"] = self._elapsed(step_start)
        trace["rrf_weights"] = intent.weights

        step_start = perf_counter()
        hydrated = await self._hydrate_from_mysql(merged, kb_ids)
        hydrated = self._deduplicate_legal_candidates(hydrated)
        trace["mysql_lookup_latency_ms"] = self._elapsed(step_start)
        trace["merged_results"] = hydrated

        step_start = perf_counter()
        ranked = await self.reranker.rerank(
            user_query,
            hydrated,
            top_k=rerank_top_k,
            context={
                "intent_type": intent.intent_type,
                "historical": intent.filters.get("is_latest") is None,
                "query_keywords": rewritten.entity_list,
                "legal_domain": intent.filters.get("legal_domain"),
            },
        )
        trace["rerank_latency_ms"] = self._elapsed(step_start)
        trace["rerank_weights"] = self.reranker.pipeline.weights
        trace["reranked_results"] = ranked
        trace["total_latency_ms"] = self._elapsed(total_start)
        return RetrievalResult(chunks=[self._to_hit(item) for item in ranked], trace=trace)

    async def _search_bm25(
        self,
        query: str,
        top_k: int,
        kb_ids: list[str] | None,
        filters: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], int]:
        """执行 BM25 并补做版本过滤。"""
        start = perf_counter()
        results = await self.bm25.search(query, top_k=top_k * 2, filter_kb_ids=kb_ids)
        filtered = [item for item in results if self._matches_filters(item.get("metadata") or {}, filters)]
        return filtered[:top_k], self._elapsed(start)

    async def _search_milvus(
        self,
        query: str,
        top_k: int,
        kb_ids: list[str] | None,
        filters: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], int]:
        """生成查询向量并在线程中执行同步 Milvus SDK；失败时允许 BM25 降级。"""
        start = perf_counter()
        try:
            vectors = await self.embedding.embed([query])
            if not vectors:
                return [], self._elapsed(start)
            raw_hits = await asyncio.to_thread(
                self.milvus.search,
                vectors[0],
                top_k,
                self._build_filter(kb_ids, filters),
            )
        except Exception as exc:
            logger.warning("Milvus语义检索降级: %s", exc.__class__.__name__)
            _count_milvus_fallback()
            return [], self._elapsed(start)
        results = []
        for hit in raw_hits:
            entity = dict(hit.get("entity") or {})
            similarity = max(0.0, min(1.0, float(hit.get("distance", 0.0))))
            results.append(
                {
                    **entity,
                    "chunk_id": str(entity.get("chunk_id") or ""),
                    "milvus_score": similarity,
                    "milvus_distance": 1.0 - similarity,
                }
            )
        return results, self._elapsed(start)

    @staticmethod
    def _rrf_merge(
        bm25_results: list[dict[str, Any]],
        milvus_results: list[dict[str, Any]],
        weights: dict[str, float],
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """按 `Σ weight/(60+rank)` 融合两路结果并保留各路分数。"""
        merged: dict[str, dict[str, Any]] = {}
        for source, results in (("bm25", bm25_results), ("semantic", milvus_results)):
            weight = float(weights.get(source, 0.5))
            for rank, item in enumerate(results, start=1):
                chunk_id = str(item.get("chunk_id") or "")
                if not chunk_id:
                    continue
                target = merged.setdefault(chunk_id, {"chunk_id": chunk_id, "rrf_score": 0.0})
                target.update({key: value for key, value in item.items() if value is not None})
                target["rrf_score"] += weight / (60 + rank)
        return sorted(merged.values(), key=lambda item: item["rrf_score"], reverse=True)[:limit]

    async def _hydrate_from_mysql(
        self, candidates: list[dict[str, Any]], kb_ids: list[str] | None
    ) -> list[dict[str, Any]]:
        """按 Milvus/BM25 业务 ID 批量回查 MySQL，完整 metadata 以 MySQL 为准。"""
        numeric_ids = [int(item["chunk_id"]) for item in candidates if str(item["chunk_id"]).isdigit()]
        if not numeric_ids:
            return []
        stmt = select(KnowledgeChunk).where(KnowledgeChunk.id.in_(numeric_ids))
        if kb_ids:
            stmt = stmt.where(KnowledgeChunk.kb_id.in_([int(item) for item in kb_ids]))
        result = await self.db.execute(stmt)
        by_id = {str(chunk.id): chunk for chunk in result.scalars().all()}
        hydrated = []
        for candidate in candidates:
            chunk = by_id.get(str(candidate["chunk_id"]))
            if chunk is None:
                continue
            metadata = dict(chunk.metadata_ or {})
            hydrated.append(
                {
                    **candidate,
                    "text": chunk.text,
                    "document_id": chunk.document_id,
                    "kb_id": chunk.kb_id,
                    "chunk_index": chunk.chunk_index,
                    "metadata": metadata,
                    "chunk_type": chunk.chunk_type,
                    "chunk_subtype": chunk.chunk_subtype,
                    "chunk_level": chunk.chunk_level,
                    "parent_chunk_id": chunk.parent_chunk_id,
                    **{key: value for key, value in metadata.items() if key not in {"text", "content"}},
                }
            )
        return hydrated

    @staticmethod
    def _deduplicate_legal_candidates(
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """按文档、条号与层级合并重复法条，保留信息最完整的正文。

        历史数据可能由旧解析器把正文中每次出现的“第×条”都切成独立 Chunk。
        这些 Chunk ID 不同，RRF 无法去重；这里使用法律语义键二次去重，并优先
        选择文本最长的候选，避免把只有半句话的引用片段展示为条款原文。
        """
        grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
        order: list[tuple[str, str, str]] = []
        passthrough: list[dict[str, Any]] = []
        for item in candidates:
            metadata = dict(item.get("metadata") or {})
            document_id = str(item.get("document_id") or metadata.get("document_id") or "")
            article_no = str(item.get("article_no") or metadata.get("article_no") or metadata.get("article") or "").strip()
            hierarchy_path = str(item.get("hierarchy_path") or metadata.get("hierarchy_path") or "").strip()
            if not document_id or not article_no:
                passthrough.append(item)
                continue
            key = (document_id, article_no, hierarchy_path)
            current = grouped.get(key)
            if current is None:
                grouped[key] = dict(item)
                order.append(key)
                continue
            # 同条款存在多个误切片段时，最长文本通常是完整法条；检索分数则取组内最大值。
            representative = dict(item) if len(str(item.get("text") or "")) > len(str(current.get("text") or "")) else current
            for score_key in ("rrf_score", "bm25_score", "milvus_score"):
                values = [value for value in (current.get(score_key), item.get(score_key)) if value is not None]
                if values:
                    representative[score_key] = max(float(value) for value in values)
            grouped[key] = representative
        return [grouped[key] for key in order] + passthrough

    @staticmethod
    def _build_filter(kb_ids: list[str] | None, filters: dict[str, Any]) -> str:
        """构建只含受控值的 Milvus 标量过滤表达式。"""
        parts = []
        if kb_ids:
            values = ", ".join(f'"{HybridRetriever._escape(item)}"' for item in kb_ids)
            parts.append(f"kb_id in [{values}]")
        if filters.get("is_latest") is True:
            parts.append("is_latest == true")
        if filters.get("version"):
            parts.append(f'version == "{HybridRetriever._escape(str(filters["version"]))}"')
        if filters.get("chunk_level"):
            parts.append(f'chunk_level == "{HybridRetriever._escape(str(filters["chunk_level"]))}"')
        return " and ".join(parts)

    @staticmethod
    def _matches_filters(metadata: dict[str, Any], filters: dict[str, Any]) -> bool:
        """让 BM25 通路使用与 Milvus 一致的版本与层级过滤。"""
        if filters.get("is_latest") is True and metadata.get("is_latest") is False:
            return False
        if filters.get("version") and str(metadata.get("version") or "") != str(filters["version"]):
            return False
        if filters.get("chunk_level") and metadata.get("chunk_level") != filters["chunk_level"]:
            return False
        return True

    @staticmethod
    def _to_hit(item: dict[str, Any]) -> ChunkHit:
        """将重排字典转换为内部 ChunkHit。"""
        return ChunkHit(
            chunk_id=str(item["chunk_id"]),
            text=str(item.get("text") or ""),
            bm25_score=item.get("bm25_score"),
            milvus_score=item.get("milvus_score"),
            milvus_distance=item.get("milvus_distance"),
            rrf_score=float(item.get("rrf_score") or 0.0),
            final_score=float(item.get("final_score") or 0.0),
            metadata=dict(item.get("metadata") or {}),
        )

    @staticmethod
    def _elapsed(start: float) -> int:
        """将 perf_counter 时间差转换为毫秒。"""
        return int((perf_counter() - start) * 1000)

    @staticmethod
    def _escape(value: str) -> str:
        """转义 Milvus 过滤表达式字符串。"""
        return str(value).replace("\\", "\\\\").replace('"', '\\"')
