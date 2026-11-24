"""run/step 级 Trace 落库（doc 21 §4.5/§5.1）：把 MultiAgentRun + StepTrace 持久化到 agent_run_trace。

接入点：pipeline.run() 的 finally 块调用 finalize_run()，确保正常结束/异常中断/前端断连都落库。
全部 best-effort：失败只 warning，不抛异常，不拖垮用户请求。
"""

from __future__ import annotations

from dataclasses import asdict
from time import perf_counter
from typing import Any

from backend.config import settings
from backend.utils.logger import get_logger

from .hooks import AFTER_PIPELINE, get_hook_bus

logger = get_logger(__name__)

_RESULT_SUMMARY_ANSWER_LIMIT = 200


def _derive_status(*, error: str, needs_human_review: bool) -> str:
    """推导 run 状态：失败 → failed；需人工复核 → hitl；否则 success。"""
    if error:
        return "failed"
    if needs_human_review:
        return "hitl"
    return "success"


def _summarize_agent_results(agent_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把各 Agent 全文产出压缩为摘要（不含 context_text/chunks 全文，控制 JSON 体积）。"""
    summary: list[dict[str, Any]] = []
    for result in agent_results:
        summary.append(
            {
                "agent": result.get("agent"),
                "_step_id": result.get("_step_id"),
                "output_summary": result.get("output_summary") or "",
                "answer": (result.get("answer") or "")[:_RESULT_SUMMARY_ANSWER_LIMIT],
            }
        )
    return summary


async def persist_run_trace(
    run: Any,
    shared_state: dict[str, Any],
    *,
    started: float,
    status: str,
    error: str,
) -> None:
    """把一次 run 写入 agent_run_trace 表。best-effort。"""
    if not (settings.harness_enabled and settings.harness_trace_enabled):
        return

    from backend.database import AsyncSessionLocal
    from backend.models.harness import AgentRunTrace

    trace_id = run.trace_id or shared_state.get("trace_id") or ""
    if not trace_id:
        logger.warning("[Trace] 无可用 trace_id，跳过 run 落库")
        return

    row = AgentRunTrace(
        trace_id=trace_id,
        plan_id=run.plan_id or "",
        conversation_id=_safe_int(shared_state.get("conversation_id")),
        user_id=_safe_int(shared_state.get("user_id")),
        query=run.query or "",
        intent=run.intent or {},
        plan=run.plan or {},
        step_traces=[asdict(t) for t in run.step_traces],
        agent_results_summary=_summarize_agent_results(run.agent_results),
        review=run.review or {},
        final_answer=run.final_answer or "",
        final_citations=run.final_citations or [],
        needs_human_review=1 if run.needs_human_review else 0,
        total_latency_ms=int((perf_counter() - started) * 1000),
        status=status,
        error=error or None,
        experiment_variant=shared_state.get("experiment_variant") or None,
    )
    try:
        async with AsyncSessionLocal() as db:
            db.add(row)
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.warning("[Trace] agent_run_trace 落库失败 trace_id=%s", trace_id, exc_info=True)


async def finalize_run(
    run: Any,
    shared_state: dict[str, Any],
    *,
    started: float,
    error: str = "",
) -> None:
    """pipeline.run() finally 的统一收尾：先发 after_pipeline hook（指标），再落 run trace，随后在线评估。

    全程 best-effort；任一环节失败只 warning。
    """
    if not settings.harness_enabled:
        return

    status = _derive_status(error=error, needs_human_review=bool(run.needs_human_review))
    await get_hook_bus().emit(
        AFTER_PIPELINE,
        {
            "run": run,
            "shared_state": shared_state,
            "status": status,
            "error": error,
            "total_latency_ms": int((perf_counter() - started) * 1000),
        },
    )

    await persist_run_trace(run, shared_state, started=started, status=status, error=error)

    if settings.evaluation_enabled:
        try:
            from agent_service.evaluator.recorder import enqueue_offline, record_online

            await record_online(run, shared_state)
            trace_id = run.trace_id or shared_state.get("trace_id") or ""
            await enqueue_offline(trace_id, _safe_int(shared_state.get("user_id")))
        except Exception:  # noqa: BLE001
            logger.warning("[Trace] 在线评估失败，已忽略", exc_info=True)


def _safe_int(value: Any) -> int | None:
    """安全转换为 int；无法转换返回 None。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
