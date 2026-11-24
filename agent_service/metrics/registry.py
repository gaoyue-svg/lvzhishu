"""Prometheus 指标定义与 Hook 处理器注册。

关键约束：label 只用固定枚举（agent/tool/purpose/status/provider/model），
绝不把 trace_id / query / 用户输入作为 label，避免指标基数爆炸。
"""

from __future__ import annotations

from typing import Any

from prometheus_client import Counter, Histogram

from agent_service.orchestrator.hooks import AFTER_PIPELINE, AFTER_STEP, get_hook_bus
from backend.config import settings
from backend.utils.logger import get_logger

logger = get_logger(__name__)

# ===== Agent / Pipeline 指标 =====
AGENT_CALLS = Counter(
    "lawagent_agent_calls_total",
    "Agent 调用次数（按 Agent 与结果状态）",
    ["agent", "status"],
)
AGENT_STEP_LATENCY = Histogram(
    "lawagent_agent_step_latency_seconds",
    "Agent 单步耗时（秒）",
    ["agent"],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, float("inf")),
)
PIPELINE_RUNS = Counter(
    "lawagent_pipeline_runs_total",
    "v2 pipeline run 次数（按结果状态 success/failed/hitl）",
    ["status"],
)
PIPELINE_LATENCY = Histogram(
    "lawagent_pipeline_latency_seconds",
    "v2 pipeline run 总耗时（秒）",
    ["status"],
    buckets=(1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, float("inf")),
)

# ===== LLM 指标（provider 采集时实时累加）=====
LLM_CALLS = Counter(
    "lawagent_llm_calls_total",
    "LLM 调用次数（按提供方/模型/用途）",
    ["provider", "model", "purpose"],
)
LLM_TOKENS = Counter(
    "lawagent_llm_tokens_total",
    "LLM 累计 token 数（按提供方/模型/用途）",
    ["provider", "model", "purpose"],
)
LLM_COST = Counter(
    "lawagent_llm_cost_total",
    "LLM 累计估算成本（元，按提供方/模型）",
    ["provider", "model"],
)

# ===== 降级 / 护栏指标 =====
MILVUS_FALLBACK = Counter("lawagent_milvus_fallback_total", "Milvus 检索降级为 BM25 的次数")
WEB_SEARCH_FALLBACK = Counter(
    "lawagent_web_search_fallback_total",
    "WebSearch 降级次数（按原因 not_configured/error/timeout/mcp_unavailable）",
    ["reason"],
)
GUARD_BLOCKED = Counter(
    "lawagent_guard_blocked_total",
    "Input Guard 拦截次数（按检查项 query/kb/budget/injection/sensitive/concurrency）",
    ["check"],
)


def _on_after_step(_event: str, ctx: dict[str, Any]) -> None:
    """after_step hook：记录 Agent 调用与单步耗时。"""
    trace = ctx.get("trace")
    if trace is None:
        return
    agent = ctx.get("step", None).agent if ctx.get("step") is not None else (trace.agent or "unknown")
    status = ctx.get("status") or trace.status or "unknown"
    AGENT_CALLS.labels(agent=agent, status=status).inc()
    if trace.latency_ms:
        AGENT_STEP_LATENCY.labels(agent=agent).observe(trace.latency_ms / 1000.0)


def _on_after_pipeline(_event: str, ctx: dict[str, Any]) -> None:
    """after_pipeline hook：记录 run 次数与总耗时。"""
    status = ctx.get("status") or "unknown"
    latency_ms = ctx.get("total_latency_ms") or 0
    PIPELINE_RUNS.labels(status=status).inc()
    if latency_ms:
        PIPELINE_LATENCY.labels(status=status).observe(latency_ms / 1000.0)


_initialized: bool = False


def init_metrics() -> None:
    """幂等地把指标处理器注册到 HookBus。"""
    global _initialized
    if _initialized:
        return
    if not settings.harness_metrics_enabled:
        _initialized = True
        return
    hook_bus = get_hook_bus()
    hook_bus.register(AFTER_STEP, _on_after_step)
    hook_bus.register(AFTER_PIPELINE, _on_after_pipeline)
    _initialized = True
    logger.info("Harness Prometheus 指标处理器已注册")
