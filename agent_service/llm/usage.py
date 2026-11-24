"""LLM 调用用量采集（doc 21 §4.3/§5.2）：provider 层把每次调用的 token/耗时写入请求级 Collector，
run 结束时统一冲刷到 llm_usage 表。全部 best-effort，绝不抛错影响主链路。

采集点：
- 非流式 chat / chat_with_tools：读 OpenAI 兼容响应里的 usage（真实 token 数）；
- 流式 stream：用 tiktoken 估算（provider 兼容考虑，不引入 stream_options）；
- purpose 由编排层用 usage_purpose() 上下文标记（router/agent/synthesize/review/general）。
"""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterator

from backend.config import settings
from backend.utils.logger import get_logger

logger = get_logger(__name__)

# 轻量单价表：{model: (输入每 1k token 成本, 输出每 1k token 成本)}，单位元；未知模型按 0 计。
# 后续可改为配置驱动；当前仅为估算，非计费依据。
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "deepseek-chat": (0.001, 0.002),
    "deepseek-reasoner": (0.004, 0.008),
}


@dataclass
class LlmUsageRecord:
    """一次 LLM 调用的用量记录。"""

    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    purpose: str = "general"


@dataclass
class UsageCollector:
    """请求级用量收集器：把一次请求内所有 LLM 调用暂存，结束统一落库。"""

    records: list[LlmUsageRecord] = field(default_factory=list)

    def add(self, record: LlmUsageRecord) -> None:
        """追加一条用量记录。"""
        self.records.append(record)

    @property
    def total_tokens(self) -> int:
        """本次请求累计 token 数。"""
        return sum(r.prompt_tokens + r.completion_tokens for r in self.records)


# ---- 请求级 contextvar：provider 通过它把用量写进当前请求的 collector ----
_collector: ContextVar[UsageCollector | None] = ContextVar("llm_usage_collector", default=None)
_purpose: ContextVar[str] = ContextVar("llm_usage_purpose", default="general")


def set_usage_collector(collector: UsageCollector) -> Any:
    """绑定当前任务的用量收集器，返回用于恢复的 Token。"""
    return _collector.set(collector)


def reset_usage_collector(token: Any) -> None:
    """解除用量收集器绑定。"""
    _collector.reset(token)


def get_current_collector() -> UsageCollector | None:
    """返回当前任务绑定的收集器；未绑定时返回 None。"""
    return _collector.get()


@contextmanager
def usage_purpose(purpose: str) -> Iterator[None]:
    """在 LLM 调用周围标记用途（router/agent/synthesize/review 等）。"""
    token = _purpose.set(purpose)
    try:
        yield
    finally:
        _purpose.reset(token)


def record_usage(
    *,
    provider: str,
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    latency_ms: int = 0,
    purpose: str | None = None,
) -> None:
    """provider 层采集入口：把一次调用写入当前 collector（未绑定或已关闭则忽略）。

    best-effort：任何异常只 warning，不影响 LLM 调用本身。
    """
    if not settings.llm_usage_enabled:
        return
    collector = get_current_collector()
    if collector is None:
        return
    try:
        record = LlmUsageRecord(
            provider=provider,
            model=model,
            prompt_tokens=int(prompt_tokens or 0),
            completion_tokens=int(completion_tokens or 0),
            latency_ms=int(latency_ms or 0),
            purpose=purpose or _purpose.get() or "general",
        )
        collector.add(record)
        _update_metrics(record)
    except Exception:  # noqa: BLE001
        logger.warning("LLM 用量采集失败，已忽略", exc_info=True)


def _update_metrics(record: LlmUsageRecord) -> None:
    """实时累加 LLM 调用/Token/成本指标（prometheus 全局收集器，进程内安全）。"""
    try:
        from agent_service.metrics.registry import LLM_CALLS, LLM_COST, LLM_TOKENS

        labels = {"provider": record.provider, "model": record.model}
        LLM_CALLS.labels(**labels, purpose=record.purpose).inc()
        LLM_TOKENS.labels(**labels, purpose=record.purpose).inc(record.prompt_tokens + record.completion_tokens)
        cost = estimate_cost(record.model, record.prompt_tokens, record.completion_tokens)
        if cost:
            LLM_COST.labels(**labels).inc(cost)
    except Exception:  # noqa: BLE001
        logger.warning("LLM 指标更新失败，已忽略", exc_info=True)


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """按内置单价表估算单次调用成本（元）；未知模型返回 0。"""
    pricing = _MODEL_PRICING.get(model)
    if pricing is None:
        return 0.0
    in_price, out_price = pricing
    return round((prompt_tokens / 1000) * in_price + (completion_tokens / 1000) * out_price, 6)


@asynccontextmanager
async def _usage_session(db: Any | None = None) -> AsyncIterator[Any]:
    """优先复用调用方传入的会话；否则自建（与 RagTraceRouterRecorder 一致）。"""
    if db is not None:
        yield db
        return
    from backend.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        yield session


async def flush_usage(
    collector: UsageCollector | None,
    *,
    trace_id: str,
    user_id: int | None = None,
    message_id: int | None = None,
    db: Any | None = None,
) -> None:
    """把收集器中的用量记录批量写入 llm_usage 表。best-effort，失败仅 warning。"""
    if not collector or not collector.records:
        return
    if not settings.llm_usage_enabled:
        return

    from backend.models.harness import LlmUsage

    rows: list[LlmUsage] = []
    for record in collector.records:
        rows.append(
            LlmUsage(
                trace_id=trace_id,
                message_id=message_id,
                user_id=user_id,
                provider=record.provider,
                model=record.model,
                prompt_tokens=record.prompt_tokens,
                completion_tokens=record.completion_tokens,
                total_tokens=record.prompt_tokens + record.completion_tokens,
                latency_ms=record.latency_ms,
                cost=estimate_cost(record.model, record.prompt_tokens, record.completion_tokens),
                purpose=record.purpose,
            )
        )
    if not rows:
        return

    try:
        async with _usage_session(db) as session:
            session.add_all(rows)
            await session.commit()
    except Exception:  # noqa: BLE001
        logger.warning("llm_usage 落库失败 records=%s", len(rows), exc_info=True)
