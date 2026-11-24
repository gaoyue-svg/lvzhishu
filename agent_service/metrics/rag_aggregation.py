"""RAG 指标聚合（doc 21 Phase 3）：基于 rag_trace 表离线计算召回/精度相关指标。

说明：rag_trace 无 ground-truth 相关文档集，真正的 Recall/Precision 无法精确计算；
这里给出可推导的代理指标（precision_proxy 等）与基础统计，供运营看板参考。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from backend.models.task import RagTrace
from backend.utils.logger import get_logger

logger = get_logger(__name__)


async def aggregate_rag_metrics(db: Any, *, since_days: int = 7) -> dict[str, Any]:
    """聚合近 N 天 rag_trace 数据，返回检索链路指标摘要。"""
    since = datetime.now() - timedelta(days=since_days)
    result = await db.execute(
        select(
            RagTrace.total_latency_ms,
            RagTrace.retrieval_latency_ms,
            RagTrace.citation_count,
            RagTrace.merged_results,
        ).where(RagTrace.created_at >= since)
    )
    rows = result.all()

    total = len(rows)
    if total == 0:
        return {
            "since_days": since_days,
            "total_retrievals": 0,
            "avg_total_latency_ms": 0,
            "avg_retrieval_latency_ms": 0,
            "citation_rate": 0.0,
            "avg_citation_count": 0.0,
            "avg_retrieved_count": 0.0,
            "precision_proxy": 0.0,
        }

    with_citation = sum(1 for row in rows if int(row.citation_count or 0) > 0)
    total_citation = sum(int(row.citation_count or 0) for row in rows)
    total_latency = sum(int(row.total_latency_ms or 0) for row in rows)
    retrieval_latency = sum(int(row.retrieval_latency_ms or 0) for row in rows)

    retrieved_counts = [
        len(list(row.merged_results or [])) for row in rows if isinstance(row.merged_results, list)
    ]
    avg_retrieved = (sum(retrieved_counts) / len(retrieved_counts)) if retrieved_counts else 0.0

    # precision_proxy：平均引用数 / 平均检索返回数（检索返回中真正被引用的比例）
    avg_citation = total_citation / max(total, 1)
    precision_proxy = round(avg_citation / max(avg_retrieved, 1), 4)

    return {
        "since_days": since_days,
        "total_retrievals": total,
        "avg_total_latency_ms": round(total_latency / max(total, 1), 1),
        "avg_retrieval_latency_ms": round(retrieval_latency / max(total, 1), 1),
        "citation_rate": round(with_citation / total, 4),
        "avg_citation_count": round(avg_citation, 2),
        "avg_retrieved_count": round(avg_retrieved, 2),
        "precision_proxy": precision_proxy,
    }
