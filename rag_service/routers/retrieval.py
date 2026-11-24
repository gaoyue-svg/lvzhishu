"""本文件提供 Retrieval Lab 全链路调试、BM25 重载与历史 Trace 查询接口。"""

from __future__ import annotations

import json
from time import perf_counter
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_db
from backend.models.knowledge import KnowledgeBase
from backend.models.task import RagTrace
from backend.models.user import User
from backend.schemas.response import ApiResponse
from backend.services.auth import get_current_user
from backend.services.llm_config import resolve_runtime_config
from embedding_service.embedding.embedding import EmbeddingFactory
from rag_service.retrieval.bm25 import BM25Retriever
from rag_service.retrieval.citation import build_citations
from rag_service.retrieval.context_builder import ContextBuilder
from rag_service.retrieval.dependencies import (
    get_bm25,
    get_context_builder,
    get_milvus,
    get_query_rewriter,
    get_query_router,
)
from rag_service.retrieval.milvus_client import MilvusStore
from rag_service.retrieval.query_rewrite import BaseQueryRewriter
from rag_service.retrieval.query_router import QueryRouter
from rag_service.retrieval.reranker import ConfigurableLegalReranker
from rag_service.retrieval.retriever import HybridRetriever
from rag_service.schemas.retrieval import (
    ChunkResultItem,
    RetrieveDebugRequest,
    RetrieveDebugResponse,
    RetrieveHistoryItem,
    RetrieveTraceResponse,
)

router = APIRouter(prefix="/api/retrieve", tags=["检索"])


@router.get("/history", response_model=ApiResponse[list[RetrieveHistoryItem]])
async def list_retrieve_history(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> ApiResponse[list[RetrieveHistoryItem]]:
    """返回当前用户最近的法规检索记录，不混入普通聊天检索。"""
    result = await db.execute(
        select(RagTrace)
        .where(RagTrace.user_id == current_user.id, RagTrace.agent_type == "legal_search")
        .order_by(desc(RagTrace.created_at))
        .limit(limit)
    )
    items: list[RetrieveHistoryItem] = []
    for record in result.scalars().all():
        details = dict(record.expanded_queries or {})
        query_intent = details.get("query_intent") or {}
        items.append(
            RetrieveHistoryItem(
                trace_id=record.trace_id,
                query=record.original_query,
                hit_count=len(record.reranked_results or []),
                total_latency_ms=record.total_latency_ms,
                intent_type=query_intent.get("intent_type"),
                created_at=record.created_at,
            )
        )
    return ApiResponse(data=items)


@router.delete("/history/{trace_id}", response_model=ApiResponse[None])
async def delete_retrieve_history(
    trace_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[None]:
    """删除当前用户的一条法规检索历史记录。"""
    result = await db.execute(
        select(RagTrace).where(
            RagTrace.trace_id == trace_id,
            RagTrace.user_id == current_user.id,
            RagTrace.agent_type == "legal_search",
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到检索记录")
    await db.delete(record)
    await db.commit()
    return ApiResponse(data=None)


@router.post("/debug", response_model=ApiResponse[RetrieveDebugResponse])
async def debug_retrieve(
    body: RetrieveDebugRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    bm25: Annotated[BM25Retriever, Depends(get_bm25)],
    milvus: Annotated[MilvusStore | None, Depends(get_milvus)],
    rewriter: Annotated[BaseQueryRewriter, Depends(get_query_rewriter)],
    query_router: Annotated[QueryRouter, Depends(get_query_router)],
    context_builder: Annotated[ContextBuilder, Depends(get_context_builder)],
) -> ApiResponse[RetrieveDebugResponse]:
    """运行可观察的混合检索闭环并将每一步结果写入 rag_trace。"""
    kb_ids = await _resolve_owned_kb_ids(db, current_user.id, body.kb_ids)
    runtime_embedding = await resolve_runtime_config(db, current_user.id, "embedding")
    embedding = EmbeddingFactory.create(
        runtime_embedding.provider if runtime_embedding else settings.embedding_provider,
        runtime_embedding.model_name if runtime_embedding else settings.embedding_model,
        (runtime_embedding.api_base if runtime_embedding else settings.embedding_api_base) or None,
        (runtime_embedding.api_key if runtime_embedding else settings.embedding_api_key) or None,
        dimension=(runtime_embedding.dimension if runtime_embedding else settings.embedding_dim),
    )
    retriever = HybridRetriever(
        bm25=bm25,
        milvus=milvus,
        embedding=embedding,
        reranker=await _load_user_reranker(db, current_user.id),
        query_rewriter=rewriter,
        query_router=query_router,
        db=db,
    )
    retrieval = await retriever.retrieve(
        body.query,
        kb_ids=kb_ids,
        top_k=15,
        rerank_top_k=body.top_k,
    )
    trace = retrieval.trace
    reranked = [hit.to_dict() for hit in retrieval.chunks]
    if body.agent_type == "legal_search":
        reranked = _filter_relevant_law_results(reranked)
        # Trace/历史命中数必须与页面真正展示的结果一致。
        trace["reranked_results"] = reranked
    citations = await build_citations(reranked)

    context_start = perf_counter()
    if trace["query_intent"]["intent_type"] == "chapter_summary" and any(
        (item.get("metadata") or {}).get("chunk_level") in {"book", "chapter", "section"}
        for item in reranked
    ):
        context_result = await context_builder.build_with_parent_expansion(
            reranked, db, max_tokens=settings.context_max_tokens
        )
    else:
        context_result = await context_builder.build(
            reranked,
            citations,
            max_tokens=settings.context_max_tokens,
        )
    context_latency = int((perf_counter() - context_start) * 1000)
    trace["context_build_latency_ms"] = context_latency
    trace["context_token_count"] = context_result.token_count
    trace["citations"] = citations
    trace["context_text"] = context_result.context_text
    trace["total_latency_ms"] += context_latency

    trace_id = uuid4().hex
    await _save_trace(
        db,
        trace_id=trace_id,
        user_id=current_user.id,
        agent_type=body.agent_type,
        trace=trace,
    )
    response = RetrieveDebugResponse(
        trace_id=trace_id,
        original_query=body.query,
        rewritten_query=trace["rewritten_query"],
        query_intent=trace["query_intent"],
        bm25_results=_result_items(trace["bm25_results"]),
        milvus_results=_result_items(trace["milvus_results"]),
        merged_results=_result_items(trace["merged_results"]),
        reranked_results=_result_items(reranked),
        citations=citations,
        context_text=context_result.context_text,
        latency_ms=_latency_summary(trace),
    )
    return ApiResponse(data=response)


def _filter_relevant_law_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """根据本次查询的最高分自适应过滤法规检索结果。

    top_k 是候选上限，不是要凑满的固定条数。保留达到最佳结果
    78% 且绝对分不低于 0.35 的项；若有候选但全部低于阈值，
    仅保留最佳一项，便于用户判断是否需要改写查询。
    """
    if not results:
        return []
    best_score = max(float(item.get("score") or item.get("final_score") or 0.0) for item in results)
    threshold = max(0.35, best_score * 0.78)
    filtered = [
        item
        for item in results
        if float(item.get("score") or item.get("final_score") or 0.0) >= threshold
    ]
    return (filtered or results[:1])[:8]


@router.post("/bm25/reload", response_model=ApiResponse[dict[str, int]])
async def reload_bm25(
    current_user: Annotated[User, Depends(get_current_user)],
    bm25: Annotated[BM25Retriever, Depends(get_bm25)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[dict[str, int]]:
    """手动从 MySQL 全量重建并持久化 BM25 调试索引。"""
    _ = current_user
    await bm25.rebuild_all(db)
    await bm25.save()
    return ApiResponse(data={"chunk_count": bm25.size})


@router.get("/trace/{trace_id}", response_model=ApiResponse[RetrieveTraceResponse])
async def get_trace(
    trace_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[RetrieveTraceResponse]:
    """查询当前用户拥有的历史检索 Trace。"""
    result = await db.execute(
        select(RagTrace).where(RagTrace.trace_id == trace_id, RagTrace.user_id == current_user.id)
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到 Trace")
    details = dict(record.expanded_queries or {})
    rewritten = None
    if record.rewritten_query:
        try:
            rewritten = json.loads(record.rewritten_query)
        except json.JSONDecodeError:
            rewritten = None
    response = RetrieveTraceResponse(
        trace_id=record.trace_id,
        original_query=record.original_query,
        rewritten_query=rewritten,
        query_intent=details.get("query_intent"),
        bm25_raw_query=details.get("bm25_raw_query"),
        bm25_results=_result_items(record.bm25_results or []),
        bm25_latency_ms=details.get("bm25_latency_ms"),
        milvus_query_vector_dim=details.get("milvus_query_vector_dim"),
        milvus_filter_expr=details.get("milvus_filter_expr"),
        milvus_results=_result_items(record.milvus_results or []),
        milvus_latency_ms=details.get("milvus_latency_ms"),
        rrf_weights=details.get("rrf_weights"),
        merged_results=_result_items(record.merged_results or []),
        merge_latency_ms=details.get("merge_latency_ms"),
        rerank_weights=details.get("rerank_weights"),
        reranked_results=_result_items(record.reranked_results or []),
        rerank_latency_ms=details.get("rerank_latency_ms"),
        citations=details.get("citations"),
        context_text=record.final_context,
        context_token_count=details.get("context_token_count"),
        total_latency_ms=record.total_latency_ms,
        created_at=record.created_at,
    )
    return ApiResponse(data=response)


async def _resolve_owned_kb_ids(
    db: AsyncSession, user_id: int, requested_ids: list[str]
) -> list[str]:
    """兼容数字 ID 和知识库名称，并严格限制为当前用户的知识库。"""
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.user_id == user_id))
    knowledge_bases = list(result.scalars().all())
    by_key = {str(kb.id): kb for kb in knowledge_bases}
    by_key.update({kb.name: kb for kb in knowledge_bases})
    resolved = []
    for requested in requested_ids:
        kb = by_key.get(str(requested))
        if kb is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"未找到知识库: {requested}",
            )
        resolved.append(str(kb.id))
    return list(dict.fromkeys(resolved))


async def _save_trace(
    db: AsyncSession,
    trace_id: str,
    user_id: int,
    agent_type: str,
    trace: dict[str, Any],
) -> None:
    """将完整链路映射到现有 rag_trace 表，扩展字段集中保存在 JSON 列。"""
    details = {
        key: trace.get(key)
        for key in (
            "query_intent", "bm25_raw_query", "bm25_latency_ms", "milvus_query_vector_dim",
            "milvus_filter_expr", "milvus_latency_ms", "rrf_weights", "merge_latency_ms",
            "rerank_weights", "rerank_latency_ms", "citations", "context_token_count",
            "rewrite_latency_ms", "router_latency_ms", "context_build_latency_ms",
        )
    }
    db.add(
        RagTrace(
            trace_id=trace_id,
            user_id=user_id,
            agent_type=agent_type,
            original_query=trace["original_query"],
            rewritten_query=json.dumps(trace.get("rewritten_query"), ensure_ascii=False),
            expanded_queries=details,
            bm25_results=trace.get("bm25_results"),
            milvus_results=trace.get("milvus_results"),
            merged_results=trace.get("merged_results"),
            reranked_results=trace.get("reranked_results"),
            final_context=trace.get("context_text"),
            citation_count=len(trace.get("citations") or []),
            total_latency_ms=int(trace.get("total_latency_ms") or 0),
            retrieval_latency_ms=sum(
                int(trace.get(key) or 0)
                for key in ("bm25_latency_ms", "milvus_latency_ms", "merge_latency_ms", "rerank_latency_ms")
            ),
        )
    )
    await db.commit()


def _result_items(items: list[dict[str, Any]]) -> list[ChunkResultItem]:
    """将不同检索阶段的稀疏字典转换为统一 API 结果。"""
    results = []
    for item in items:
        metadata = dict(item.get("metadata") or {})
        results.append(
            ChunkResultItem(
                chunk_id=str(item.get("chunk_id") or ""),
                text=str(item.get("text") or metadata.get("content") or ""),
                score=float(item.get("final_score") or item.get("rrf_score") or item.get("bm25_score") or item.get("milvus_score") or 0.0),
                bm25_score=item.get("bm25_score"),
                milvus_score=item.get("milvus_score"),
                chunk_type=item.get("chunk_type") or metadata.get("chunk_type"),
                chunk_subtype=item.get("chunk_subtype") or metadata.get("chunk_subtype"),
                chunk_level=item.get("chunk_level") or metadata.get("chunk_level"),
                article_no=item.get("article_no") or metadata.get("article_no") or metadata.get("article"),
                law_name=item.get("law_name") or metadata.get("law_name"),
                hierarchy_path=item.get("hierarchy_path") or metadata.get("hierarchy_path"),
                legal_level=item.get("legal_level") or metadata.get("legal_level"),
                version=item.get("version") or metadata.get("version"),
                is_latest=item.get("is_latest") if item.get("is_latest") is not None else metadata.get("is_latest"),
                page_start=item.get("page_start") or metadata.get("page_start"),
                page_end=item.get("page_end") or metadata.get("page_end"),
                char_start=metadata.get("char_start"),
                char_end=metadata.get("char_end"),
                source_uri=metadata.get("source_uri"),
                metadata=metadata or None,
            )
        )
    return results


def _latency_summary(trace: dict[str, Any]) -> dict[str, int]:
    """按接口约定重命名各步骤耗时字段。"""
    return {
        "rewrite": int(trace.get("rewrite_latency_ms") or 0),
        "router": int(trace.get("router_latency_ms") or 0),
        "bm25": int(trace.get("bm25_latency_ms") or 0),
        "milvus": int(trace.get("milvus_latency_ms") or 0),
        "merge": int(trace.get("merge_latency_ms") or 0),
        "rerank": int(trace.get("rerank_latency_ms") or 0),
        "context_build": int(trace.get("context_build_latency_ms") or 0),
        "total": int(trace.get("total_latency_ms") or 0),
    }


async def _load_user_reranker(db: AsyncSession, user_id: int) -> ConfigurableLegalReranker:
    """按当前用户动态配置创建 Rerank，未配置时使用规则重排。"""
    runtime = await resolve_runtime_config(db, user_id, "rerank")
    if runtime is None:
        return ConfigurableLegalReranker()
    return ConfigurableLegalReranker(
        provider=runtime.provider,
        model_name=runtime.model_name,
        api_base=runtime.api_base,
        api_key=runtime.api_key,
        timeout=runtime.timeout or 30,
    )
