"""评估落库（doc 21 §4.2/§5.3）：在线确定性指标 + 离线 LLM-as-Judge 抽样队列。

- record_online：确定性指标（citation_score/coverage），每条请求都算，mode='online'；
- enqueue_offline：按 trace_id 哈希抽样入队（EVALUATION_STREAM），由 worker 消费补 LLM 分；
- record_offline：worker 把 grounded/hallucination 写 mode='offline' 行（幂等 upsert）。
全部 best-effort：任何失败只 warning。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select

from backend.config import settings
from backend.utils.logger import get_logger

from .online import compute_online_scores

logger = get_logger(__name__)


async def record_online(run: Any, shared_state: dict[str, Any]) -> None:
    """为一次 run 计算在线确定性指标并写入 evaluation_result。best-effort。"""
    if not (settings.harness_enabled and settings.evaluation_enabled):
        return

    trace_id = run.trace_id or shared_state.get("trace_id") or ""
    if not trace_id:
        return

    scores = compute_online_scores(run.final_answer or "", list(run.final_citations or []))

    from backend.database import AsyncSessionLocal
    from backend.models.harness import EvaluationResult

    row = EvaluationResult(
        trace_id=trace_id,
        mode="online",
        citation_score=scores["citation_score"],
        coverage=scores["coverage"],
        overall=scores["overall"],
        detail=scores["detail"],
    )
    try:
        async with AsyncSessionLocal() as db:
            db.add(row)
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.warning("[Evaluator] 在线评估落库失败 trace_id=%s", trace_id, exc_info=True)


def _sampled(trace_id: str) -> bool:
    """按 trace_id 哈希稳定抽样（同一 trace 结果恒定）。"""
    rate = settings.evaluation_sample_rate
    if rate <= 0:
        return False
    if rate >= 1:
        return True
    digest = hashlib.md5(trace_id.encode("utf-8")).hexdigest()
    return int(digest, 16) % 1000 < int(rate * 1000)


async def enqueue_offline(trace_id: str, user_id: int | None = None) -> None:
    """按抽样率把 run 入队离线评审。best-effort（Redis 不可用则跳过）。"""
    if not (settings.harness_enabled and settings.evaluation_enabled):
        return
    if not trace_id or not _sampled(trace_id):
        return

    try:
        from backend.database import redis_client
        from backend.worker.task_queue import EVALUATION_STREAM, TaskQueue

        if redis_client is None:
            return
        queue = TaskQueue(redis_client)
        await queue.enqueue(EVALUATION_STREAM, {"trace_id": trace_id, "user_id": user_id})
        logger.info("[Evaluator] 已入队离线评审 trace_id=%s", trace_id)
    except Exception:  # noqa: BLE001
        logger.warning("[Evaluator] 离线评审入队失败 trace_id=%s", trace_id, exc_info=True)


async def record_offline(trace_id: str, user_id: int | None, scores: dict[str, Any]) -> None:
    """把离线评审分数写入 evaluation_result(mode='offline')，按 trace_id 幂等 upsert。"""
    if not trace_id or not scores or scores.get("grounded_score") is None:
        return

    from backend.database import AsyncSessionLocal
    from backend.models.harness import EvaluationResult

    try:
        async with AsyncSessionLocal() as db:
            existing = await db.scalar(
                select(EvaluationResult).where(
                    EvaluationResult.trace_id == trace_id,
                    EvaluationResult.mode == "offline",
                )
            )
            detail = scores.get("detail") or {}
            if existing is not None:
                existing.grounded_score = scores["grounded_score"]
                existing.hallucination = scores["hallucination"]
                existing.overall = scores["overall"]
                existing.detail = detail
            else:
                db.add(
                    EvaluationResult(
                        trace_id=trace_id,
                        mode="offline",
                        grounded_score=scores["grounded_score"],
                        hallucination=scores["hallucination"],
                        overall=scores["overall"],
                        detail=detail,
                    )
                )
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.warning("[Evaluator] 离线评审落库失败 trace_id=%s", trace_id, exc_info=True)
