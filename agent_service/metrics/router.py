"""Prometheus 指标导出与 RAG 指标聚合端点（doc 21 §4.3/Phase 3）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy.ext.asyncio import AsyncSession

from agent_service.metrics.rag_aggregation import aggregate_rag_metrics
from backend.database import get_db

router = APIRouter(tags=["Metrics"])


@router.get("/metrics", summary="Prometheus 指标导出")
async def metrics() -> Response:
    """返回 Prometheus 文本格式指标。"""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/api/harness/metrics/rag", summary="RAG 检索指标聚合")
async def rag_metrics(
    db: AsyncSession = Depends(get_db),
    since_days: int = 7,
) -> dict:
    """基于 rag_trace 离线聚合近 N 天检索指标（引用率/精度代理/耗时等）。"""
    return await aggregate_rag_metrics(db, since_days=since_days)
