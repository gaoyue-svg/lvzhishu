"""Harness 运营监控聚合 API（doc 21 Phase 3）：面向前端监控控制台的只读查询端点。

数据源：
- agent_run_trace   : pipeline run 次数 / 状态 / 延迟 / 链路追踪
- llm_usage         : LLM 调用 token / 成本 / 用途
- evaluation_result : online / offline 质量评分
- rag_trace         : 检索链路指标
- Prometheus REGISTRY : 进程内护栏 / 降级 / LLM 实时计数器（自进程启动累计）

约定：全部只读；空表返回零值不抛错；端点均以 ApiResponse 包装供前端 httpGet 解包。
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from prometheus_client import REGISTRY
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_service.metrics.rag_aggregation import aggregate_rag_metrics
from backend.database import get_db
from backend.models.harness import AgentRunTrace, EvaluationResult, LlmUsage, QuestionTrace
from backend.models.task import RagTrace
from backend.schemas.response import ApiResponse

router = APIRouter(tags=["Harness Monitor"])


def _since_dt(days: int) -> datetime:
    """返回 N 天前的时间点（与 DB 存储的 naive datetime 对齐）。"""
    return datetime.now() - timedelta(days=days)


def _round(value: float | None, digits: int = 2) -> float:
    """安全取整：None 视为 0。"""
    if value is None:
        return 0.0
    return round(float(value), digits)


# ======================= Pipeline（agent_run_trace）=======================

async def _pipeline_stats(db: AsyncSession, since_days: int) -> tuple[dict[str, Any], dict[str, dict[str, int]]]:
    """聚合 pipeline run 次数 / 状态分布 / 平均与 P95 延迟，并返回逐日桶。"""
    rows = (
        await db.execute(
            select(AgentRunTrace.status, AgentRunTrace.total_latency_ms, AgentRunTrace.created_at).where(
                AgentRunTrace.created_at >= _since_dt(since_days)
            )
        )
    ).all()

    by_status: dict[str, int] = defaultdict(int)
    latencies: list[int] = []
    buckets: dict[str, dict[str, int]] = {}
    for status, latency, created_at in rows:
        status = status or "unknown"
        by_status[status] += 1
        if latency:
            latencies.append(int(latency))
        day = created_at.strftime("%Y-%m-%d")
        bucket = buckets.setdefault(day, {"total": 0, "success": 0, "failed": 0, "hitl": 0})
        bucket["total"] += 1
        bucket[status] = bucket.get(status, 0) + 1

    latencies.sort()
    total = len(latencies)
    avg_latency_ms = round(sum(latencies) / total, 1) if total else 0
    p95_latency_ms = latencies[min(total - 1, int(total * 0.95))] if total else 0
    run_total = sum(by_status.values())

    stats = {
        "total_runs": run_total,
        "success": by_status.get("success", 0),
        "failed": by_status.get("failed", 0),
        "hitl": by_status.get("hitl", 0),
        "success_rate": round(by_status.get("success", 0) / max(run_total, 1), 4),
        "avg_latency_ms": avg_latency_ms,
        "p95_latency_ms": p95_latency_ms,
    }
    return stats, buckets


# ======================= LLM 用量（llm_usage）=======================

def _merge_entry(
    target: dict[str, dict[str, Any]],
    key: str,
    calls: int,
    tokens: int,
    cost: float,
    avg_latency: float,
) -> None:
    """把一组聚合记录合并进某个维度（provider/model/purpose）。"""
    entry = target.setdefault(key, {"calls": 0, "tokens": 0, "cost": 0.0, "lat_sum": 0.0, "lat_n": 0})
    entry["calls"] += calls
    entry["tokens"] += tokens
    entry["cost"] += cost
    if avg_latency and calls:
        entry["lat_sum"] += avg_latency * calls  # avg * count ≈ 分组总耗时
        entry["lat_n"] += calls


def _finalize_entries(mapping: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """把合并后的维度条目转为输出列表（按成本降序）。"""
    out: list[dict[str, Any]] = []
    for key, entry in mapping.items():
        out.append(
            {
                "name": key,
                "calls": entry["calls"],
                "tokens": entry["tokens"],
                "cost": round(entry["cost"], 4),
                "avg_latency_ms": round(entry["lat_sum"] / entry["lat_n"], 1) if entry["lat_n"] else 0,
            }
        )
    out.sort(key=lambda x: x["cost"], reverse=True)
    return out


async def _llm_stats(db: AsyncSession, since_days: int) -> tuple[dict[str, Any], dict[str, dict[str, int | float]]]:
    """聚合 LLM 用量：总量 + provider/model/purpose 维度 + 逐日桶。"""
    group_rows = (
        await db.execute(
            select(
                LlmUsage.provider,
                LlmUsage.model,
                LlmUsage.purpose,
                func.count(LlmUsage.id),
                func.sum(LlmUsage.total_tokens),
                func.sum(LlmUsage.cost),
                func.avg(LlmUsage.latency_ms),
            )
            .where(LlmUsage.created_at >= _since_dt(since_days))
            .group_by(LlmUsage.provider, LlmUsage.model, LlmUsage.purpose)
        )
    ).all()

    provider_rows: dict[str, dict[str, Any]] = {}
    model_rows: dict[str, dict[str, Any]] = {}
    purpose_rows: dict[str, dict[str, Any]] = {}
    for provider, model, purpose, calls, tokens, cost, avg_latency in group_rows:
        _merge_entry(
            provider_rows,
            provider or "unknown",
            int(calls or 0),
            int(tokens or 0),
            float(cost or 0.0),
            float(avg_latency or 0.0),
        )
        _merge_entry(model_rows, model or "unknown", int(calls or 0), int(tokens or 0), float(cost or 0.0), float(avg_latency or 0.0))
        _merge_entry(purpose_rows, purpose or "general", int(calls or 0), int(tokens or 0), float(cost or 0.0), float(avg_latency or 0.0))

    trend_rows = (
        await db.execute(
            select(LlmUsage.created_at, LlmUsage.total_tokens, LlmUsage.cost).where(
                LlmUsage.created_at >= _since_dt(since_days)
            )
        )
    ).all()
    buckets: dict[str, dict[str, int | float]] = {}
    for created_at, tokens, cost in trend_rows:
        day = created_at.strftime("%Y-%m-%d")
        bucket = buckets.setdefault(day, {"calls": 0, "tokens": 0, "cost": 0.0})
        bucket["calls"] = int(bucket["calls"]) + 1
        bucket["tokens"] = int(bucket["tokens"]) + int(tokens or 0)
        bucket["cost"] = float(bucket["cost"]) + float(cost or 0.0)

    stats = {
        "total_calls": sum(entry["calls"] for entry in provider_rows.values()),
        "total_tokens": sum(entry["tokens"] for entry in provider_rows.values()),
        "total_cost": round(sum(entry["cost"] for entry in provider_rows.values()), 4),
        "by_provider": _finalize_entries(provider_rows),
        "by_model": _finalize_entries(model_rows),
        "by_purpose": _finalize_entries(purpose_rows),
    }
    return stats, buckets


# ======================= 质量评估（evaluation_result）=======================

_EMPTY_MODE = {"count": 0, "citation_score": 0.0, "coverage": 0.0, "grounded_score": 0.0, "hallucination": 0.0, "overall": 0.0}


async def _eval_stats(db: AsyncSession, since_days: int) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """聚合 online/offline 质量评分、最近评估列表与逐日均值桶。"""
    group_rows = (
        await db.execute(
            select(
                EvaluationResult.mode,
                func.count(EvaluationResult.id),
                func.avg(EvaluationResult.citation_score),
                func.avg(EvaluationResult.coverage),
                func.avg(EvaluationResult.grounded_score),
                func.avg(EvaluationResult.hallucination),
                func.avg(EvaluationResult.overall),
            )
            .where(EvaluationResult.created_at >= _since_dt(since_days))
            .group_by(EvaluationResult.mode)
        )
    ).all()
    per_mode: dict[str, dict[str, Any]] = {}
    for mode, count, citation, coverage, grounded, hallucination, overall in group_rows:
        per_mode[mode] = {
            "count": int(count or 0),
            "citation_score": _round(citation, 4),
            "coverage": _round(coverage, 4),
            "grounded_score": _round(grounded, 4),
            "hallucination": _round(hallucination, 4),
            "overall": _round(overall, 4),
        }

    recent_rows = (
        (
            await db.execute(
                select(EvaluationResult)
                .where(EvaluationResult.created_at >= _since_dt(since_days))
                .order_by(EvaluationResult.created_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    recent = [
        {
            "trace_id": row.trace_id,
            "mode": row.mode,
            "citation_score": row.citation_score,
            "coverage": row.coverage,
            "grounded_score": row.grounded_score,
            "hallucination": row.hallucination,
            "overall": row.overall,
            "created_at": row.created_at.isoformat(timespec="seconds") if row.created_at else None,
        }
        for row in recent_rows
    ]

    trend_rows = (
        await db.execute(
            select(
                EvaluationResult.created_at,
                EvaluationResult.citation_score,
                EvaluationResult.coverage,
                EvaluationResult.grounded_score,
                EvaluationResult.hallucination,
                EvaluationResult.overall,
            ).where(EvaluationResult.created_at >= _since_dt(since_days))
        )
    ).all()
    buckets: dict[str, dict[str, Any]] = {}
    for created_at, citation, coverage, grounded, hallucination, overall in trend_rows:
        day = created_at.strftime("%Y-%m-%d")
        bucket = buckets.setdefault(
            day,
            {"count": 0, "citation_sum": 0.0, "coverage_sum": 0.0, "grounded_sum": 0.0, "hallucination_sum": 0.0, "overall_sum": 0.0},
        )
        bucket["count"] += 1
        bucket["citation_sum"] += float(citation or 0)
        bucket["coverage_sum"] += float(coverage or 0)
        bucket["grounded_sum"] += float(grounded or 0)
        bucket["hallucination_sum"] += float(hallucination or 0)
        bucket["overall_sum"] += float(overall or 0)
    for bucket in buckets.values():
        n = max(bucket["count"], 1)
        bucket["citation_score"] = _round(bucket["citation_sum"] / n, 4)
        bucket["coverage"] = _round(bucket["coverage_sum"] / n, 4)
        bucket["grounded_score"] = _round(bucket["grounded_sum"] / n, 4)
        bucket["hallucination"] = _round(bucket["hallucination_sum"] / n, 4)
        bucket["overall"] = _round(bucket["overall_sum"] / n, 4)

    stats = {
        "online": per_mode.get("online", dict(_EMPTY_MODE)),
        "offline": per_mode.get("offline", dict(_EMPTY_MODE)),
        "recent": recent,
    }
    return stats, buckets


# ======================= 检索健康（rag_trace）=======================

async def _rag_buckets(db: AsyncSession, since_days: int) -> dict[str, dict[str, Any]]:
    """逐日引用率桶，供总览趋势图与检索健康 Tab 复用。"""
    rows = (
        await db.execute(
            select(RagTrace.created_at, RagTrace.citation_count).where(RagTrace.created_at >= _since_dt(since_days))
        )
    ).all()
    buckets: dict[str, dict[str, Any]] = {}
    for created_at, citation_count in rows:
        day = created_at.strftime("%Y-%m-%d")
        bucket = buckets.setdefault(day, {"total": 0, "with_citation": 0})
        bucket["total"] += 1
        if int(citation_count or 0) > 0:
            bucket["with_citation"] += 1
    for bucket in buckets.values():
        bucket["citation_rate"] = round(bucket["with_citation"] / max(bucket["total"], 1), 4)
    return buckets


# ======================= 提问执行链路（question_trace）=======================

async def _question_stats(db: AsyncSession, since_days: int) -> dict[str, Any]:
    """聚合提问级执行链路：总量 + 引擎/状态分布。"""
    rows = (
        await db.execute(
            select(QuestionTrace.status, QuestionTrace.engine).where(
                QuestionTrace.created_at >= _since_dt(since_days)
            )
        )
    ).all()
    by_engine: dict[str, int] = defaultdict(int)
    by_status: dict[str, int] = defaultdict(int)
    for status, engine in rows:
        by_status[status or "unknown"] += 1
        by_engine[engine or "unknown"] += 1
    return {
        "total": sum(by_status.values()),
        "by_engine": dict(by_engine),
        "by_status": dict(by_status),
    }


def _question_meta(row: QuestionTrace) -> dict[str, Any]:
    """把一条提问执行链路压缩成列表可用的轻量元信息（含 agent/工具名摘要）。"""
    agents = row.agents if isinstance(row.agents, list) else []
    agent_names: list[str] = []
    tool_names: list[str] = []
    for agent in agents:
        name = agent.get("agent") or ""
        if name and name not in agent_names:
            agent_names.append(name)
        for tool in agent.get("tools") or []:
            tool_name = tool.get("name") or ""
            if tool_name and tool_name not in tool_names:
                tool_names.append(tool_name)
    return {
        "trace_id": row.trace_id,
        "conversation_id": row.conversation_id,
        "user_id": row.user_id,
        "query": (row.query or "")[:160],
        "intent": row.intent,
        "engine": row.engine,
        "status": row.status,
        "agent_count": len(agents),
        "tool_count": sum(len(agent.get("tools") or []) for agent in agents),
        "agents": agent_names,
        "tools": tool_names,
        "total_latency_ms": row.total_latency_ms,
        "answer_snippet": (row.answer_snippet or "")[:200],
        "error": (row.error or "")[:200],
        "created_at": row.created_at.isoformat(timespec="seconds") if row.created_at else None,
    }


# ======================= 运行时计数器（Prometheus，自进程启动）=======================

def _runtime_stats() -> dict[str, Any]:
    """读取 Prometheus REGISTRY 快照，汇总护栏/降级/LLM/Agent 进程内累计值。"""
    snapshot: dict[str, list[tuple[dict[str, str], float]]] = {}
    for metric_family in REGISTRY.collect():
        snapshot[metric_family.name] = [(sample.labels, float(sample.value)) for sample in metric_family.samples]

    def _pick(name: str) -> list[tuple[dict[str, str], float]]:
        return snapshot.get(name, [])

    guard_by_check: dict[str, int] = {}
    for labels, value in _pick("lawagent_guard_blocked_total"):
        check = labels.get("check", "unknown")
        guard_by_check[check] = guard_by_check.get(check, 0) + int(value)

    pipeline_runs: dict[str, int] = {}
    for labels, value in _pick("lawagent_pipeline_runs_total"):
        status = labels.get("status", "unknown")
        pipeline_runs[status] = pipeline_runs.get(status, 0) + int(value)

    web_search_fallback: dict[str, int] = {}
    for labels, value in _pick("lawagent_web_search_fallback_total"):
        reason = labels.get("reason", "unknown")
        web_search_fallback[reason] = web_search_fallback.get(reason, 0) + int(value)

    agent_calls: dict[str, int] = {}
    for labels, value in _pick("lawagent_agent_calls_total"):
        key = f"{labels.get('agent', '?')}:{labels.get('status', '?')}"
        agent_calls[key] = agent_calls.get(key, 0) + int(value)

    return {
        "since_process_start": True,
        "guard": {"total_blocked": sum(guard_by_check.values()), "by_check": guard_by_check},
        "pipeline": pipeline_runs,
        "web_search_fallback": web_search_fallback,
        "milvus_fallback": int(sum(value for _, value in _pick("lawagent_milvus_fallback_total"))),
        "llm": {
            "calls": int(sum(value for _, value in _pick("lawagent_llm_calls_total"))),
            "tokens": int(sum(value for _, value in _pick("lawagent_llm_tokens_total"))),
            "cost": round(sum(value for _, value in _pick("lawagent_llm_cost_total")), 4),
        },
        "agent_calls": agent_calls,
    }


# ======================= 逐日趋势合成 ========================

def _build_trend(
    since_days: int,
    pipeline_buckets: dict[str, dict[str, int]],
    llm_buckets: dict[str, dict[str, int | float]],
    eval_buckets: dict[str, dict[str, Any]],
    rag_buckets: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """把四类逐日桶对齐成完整的日期序列（缺日补零）。"""
    dates = [(datetime.now().date() - timedelta(days=i)).isoformat() for i in range(since_days - 1, -1, -1)]
    trend: list[dict[str, Any]] = []
    for day in dates:
        pb = pipeline_buckets.get(day, {})
        lb = llm_buckets.get(day, {})
        eb = eval_buckets.get(day, {})
        rb = rag_buckets.get(day, {})
        trend.append(
            {
                "date": day,
                "runs": pb.get("total", 0),
                "success": pb.get("success", 0),
                "failed": pb.get("failed", 0),
                "hitl": pb.get("hitl", 0),
                "llm_calls": lb.get("calls", 0),
                "tokens": lb.get("tokens", 0),
                "cost": round(float(lb.get("cost", 0.0)), 4),
                "citation_rate": rb.get("citation_rate", 0.0),
                "overall": eb.get("overall"),
            }
        )
    return trend


# ======================= Trace 列表/详情 ========================

def _trace_meta(row: AgentRunTrace) -> dict[str, Any]:
    """把一条 run trace 压缩成列表可用的轻量元信息。"""
    intent = row.intent if isinstance(row.intent, dict) else {}
    return {
        "trace_id": row.trace_id,
        "plan_id": row.plan_id,
        "conversation_id": row.conversation_id,
        "user_id": row.user_id,
        "query": (row.query or "")[:160],
        "intent": intent.get("name"),
        "intent_confidence": intent.get("confidence"),
        "status": row.status,
        "total_latency_ms": row.total_latency_ms,
        "step_count": len(row.step_traces or []),
        "needs_human_review": bool(row.needs_human_review),
        "experiment_variant": row.experiment_variant,
        "error": (row.error or "")[:200],
        "created_at": row.created_at.isoformat(timespec="seconds") if row.created_at else None,
    }


# ======================= 端点 =======================

@router.get("/api/harness/overview", summary="Harness 运营总览", response_model=ApiResponse[dict])
async def harness_overview(
    db: AsyncSession = Depends(get_db),
    since_days: int = Query(7, ge=1, le=90),
) -> dict[str, Any]:
    """聚合 pipeline / LLM / 质量 / 检索 / 运行时指标与逐日趋势，供总览 Tab 渲染。"""
    pipeline_stats, pipeline_buckets = await _pipeline_stats(db, since_days)
    llm_stats, llm_buckets = await _llm_stats(db, since_days)
    eval_stats, eval_buckets = await _eval_stats(db, since_days)
    rag_stats = await aggregate_rag_metrics(db, since_days=since_days)
    rag_buckets = await _rag_buckets(db, since_days)

    return ApiResponse(
        data={
            "since_days": since_days,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "pipeline": pipeline_stats,
            "questions": await _question_stats(db, since_days),
            "llm": llm_stats,
            "evaluation": eval_stats,
            "rag": rag_stats,
            "runtime": _runtime_stats(),
            "trend": _build_trend(since_days, pipeline_buckets, llm_buckets, eval_buckets, rag_buckets),
        }
    )


@router.get("/api/harness/traces", summary="Harness run 追踪列表", response_model=ApiResponse[dict])
async def harness_traces(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None, description="按状态过滤：success/failed/hitl"),
    intent: str | None = Query(None, description="按意图过滤（intent.name）"),
    q: str | None = Query(None, description="按 query 模糊搜索"),
    since_days: int = Query(7, ge=1, le=90),
) -> dict[str, Any]:
    """分页返回 run 追踪列表，支持状态/意图/关键词过滤。"""
    stmt = select(AgentRunTrace).where(AgentRunTrace.created_at >= _since_dt(since_days))
    if status:
        stmt = stmt.where(AgentRunTrace.status == status)
    if intent:
        # MySQL JSON 取值转字符串后比较，避免 JSON 引号导致不匹配。
        stmt = stmt.where(AgentRunTrace.intent["name"].as_string() == intent)
    if q:
        stmt = stmt.where(AgentRunTrace.query.like(f"%{q}%"))

    total = int(await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = (
        (
            await db.execute(
                stmt.order_by(AgentRunTrace.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return ApiResponse(
        data={
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [_trace_meta(row) for row in rows],
        }
    )


@router.get("/api/harness/traces/intents", summary="Harness run 意图候选", response_model=ApiResponse[dict])
async def harness_trace_intents(
    db: AsyncSession = Depends(get_db),
    since_days: int = Query(7, ge=1, le=90),
) -> dict[str, Any]:
    """返回时间窗内出现过的去重意图名，供追踪页筛选下拉使用。"""
    rows = (
        await db.execute(select(AgentRunTrace.intent).where(AgentRunTrace.created_at >= _since_dt(since_days)))
    ).all()
    names = sorted(
        {
            str(row[0].get("name"))
            for row in rows
            if isinstance(row[0], dict) and row[0].get("name")
        }
    )
    return ApiResponse(data={"intents": names})


@router.get("/api/harness/traces/{trace_id}", summary="Harness run 追踪详情", response_model=ApiResponse[dict])
async def harness_trace_detail(trace_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """返回单条 run 全量快照，附带 online/offline 评估分。"""
    row = await db.scalar(select(AgentRunTrace).where(AgentRunTrace.trace_id == trace_id))
    if row is None:
        raise HTTPException(status_code=404, detail=f"未找到 trace: {trace_id}")

    eval_rows = (
        (await db.execute(select(EvaluationResult).where(EvaluationResult.trace_id == trace_id))).scalars().all()
    )
    evaluation: dict[str, Any] = {"online": None, "offline": None}
    for eval_row in eval_rows:
        evaluation[eval_row.mode] = {
            "citation_score": eval_row.citation_score,
            "coverage": eval_row.coverage,
            "grounded_score": eval_row.grounded_score,
            "hallucination": eval_row.hallucination,
            "overall": eval_row.overall,
            "detail": eval_row.detail,
        }

    return ApiResponse(
        data={
            **_trace_meta(row),
            "query": row.query,
            "intent": row.intent,
            "plan": row.plan,
            "step_traces": row.step_traces,
            "agent_results_summary": row.agent_results_summary,
            "review": row.review,
            "final_answer": row.final_answer,
            "final_citations": row.final_citations,
            "error": row.error,
            "evaluation": evaluation,
        }
    )


@router.get("/api/harness/questions", summary="提问级执行链路列表", response_model=ApiResponse[dict])
async def harness_questions(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    engine: str | None = Query(None, description="按引擎过滤：supervisor/pipeline_v2/single_agent"),
    status: str | None = Query(None, description="按状态过滤：success/failed/hitl"),
    q: str | None = Query(None, description="按 query 模糊搜索"),
    since_days: int = Query(7, ge=1, le=90),
) -> dict[str, Any]:
    """分页返回提问级执行链路列表（每个提问一行，含 agent/工具名摘要）。"""
    stmt = select(QuestionTrace).where(QuestionTrace.created_at >= _since_dt(since_days))
    if engine:
        stmt = stmt.where(QuestionTrace.engine == engine)
    if status:
        stmt = stmt.where(QuestionTrace.status == status)
    if q:
        stmt = stmt.where(QuestionTrace.query.like(f"%{q}%"))

    total = int(await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = (
        (
            await db.execute(
                stmt.order_by(QuestionTrace.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return ApiResponse(
        data={
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [_question_meta(row) for row in rows],
        }
    )


@router.get("/api/harness/questions/{trace_id}", summary="提问级执行链路详情", response_model=ApiResponse[dict])
async def harness_question_detail(trace_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """返回单个提问的完整执行链路（agents JSON 含嵌套 tools）。"""
    row = await db.scalar(select(QuestionTrace).where(QuestionTrace.trace_id == trace_id))
    if row is None:
        raise HTTPException(status_code=404, detail=f"未找到 question trace: {trace_id}")
    return ApiResponse(
        data={
            **_question_meta(row),
            "query": row.query,
            "agents": row.agents,
            "answer_snippet": row.answer_snippet,
            "error": row.error,
        }
    )


@router.get("/api/harness/llm", summary="Harness LLM 用量聚合", response_model=ApiResponse[dict])
async def harness_llm(
    db: AsyncSession = Depends(get_db),
    since_days: int = Query(7, ge=1, le=90),
) -> dict[str, Any]:
    """返回 LLM 用量聚合（provider/model/purpose 维度 + 逐日趋势）。"""
    stats, buckets = await _llm_stats(db, since_days)
    return ApiResponse(data={"since_days": since_days, **stats, "trend": _llm_series(since_days, buckets)})


@router.get("/api/harness/evaluation", summary="Harness 质量评估聚合", response_model=ApiResponse[dict])
async def harness_evaluation(
    db: AsyncSession = Depends(get_db),
    since_days: int = Query(7, ge=1, le=90),
) -> dict[str, Any]:
    """返回在线/离线质量评分聚合与最近评估列表。"""
    stats, buckets = await _eval_stats(db, since_days)
    return ApiResponse(data={"since_days": since_days, **stats, "trend": _eval_series(since_days, buckets)})


@router.get("/api/harness/rag", summary="Harness 检索健康聚合", response_model=ApiResponse[dict])
async def harness_rag(
    db: AsyncSession = Depends(get_db),
    since_days: int = Query(7, ge=1, le=90),
) -> dict[str, Any]:
    """返回检索链路指标（含逐日引用率趋势）。"""
    stats = await aggregate_rag_metrics(db, since_days=since_days)
    buckets = await _rag_buckets(db, since_days)
    return ApiResponse(
        data={
            **stats,
            "trend": [
                {"date": day, "citation_rate": bucket.get("citation_rate", 0.0), "total": bucket.get("total", 0)}
                for day, bucket in _aligned_series(since_days, buckets)
            ],
        }
    )


@router.get("/api/harness/runtime", summary="Harness 进程运行时计数器", response_model=ApiResponse[dict])
async def harness_runtime() -> dict[str, Any]:
    """返回 Prometheus 进程内累计计数器快照（护栏/降级/LLM/Agent）。"""
    return ApiResponse(data=_runtime_stats())


# ======================= 序列辅助 ========================

def _aligned_series(
    since_days: int, buckets: dict[str, dict[str, Any]]
) -> list[tuple[str, dict[str, Any]]]:
    """把逐日桶对齐成完整日期序列（缺日补空桶）。"""
    dates = [(datetime.now().date() - timedelta(days=i)).isoformat() for i in range(since_days - 1, -1, -1)]
    return [(day, buckets.get(day, {})) for day in dates]


def _llm_series(since_days: int, buckets: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """按日序列输出 LLM 调用数 / token / 成本。"""
    return [
        {
            "date": day,
            "calls": bucket.get("calls", 0),
            "tokens": bucket.get("tokens", 0),
            "cost": round(float(bucket.get("cost", 0.0)), 4),
        }
        for day, bucket in _aligned_series(since_days, buckets)
    ]


def _eval_series(since_days: int, buckets: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """按日序列输出评估均分。"""
    return [
        {
            "date": day,
            "overall": bucket.get("overall"),
            "citation_score": bucket.get("citation_score", 0.0),
            "coverage": bucket.get("coverage", 0.0),
            "grounded_score": bucket.get("grounded_score", 0.0),
            "hallucination": bucket.get("hallucination", 0.0),
        }
        for day, bucket in _aligned_series(since_days, buckets)
    ]
