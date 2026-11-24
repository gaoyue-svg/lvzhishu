"""本文件提供 Router 决策 Trace 记录器，复用 rag_trace 表保存可观测信息。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from agent_service.router.models import RouterDecision, RouterInput
from backend.models.task import RagTrace
from backend.utils.logger import get_logger

logger = get_logger(__name__)


class RagTraceRouterRecorder:
    """将 Router Trace 写入现有 rag_trace 表，避免阶段四修改 init.sql。"""

    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        """保存异步数据库 Session 工厂。"""
        self.session_factory = session_factory

    async def record(self, trace: dict[str, Any]) -> None:
        """写入 Router Trace；失败只记录日志，不阻塞用户请求。"""
        decision: RouterDecision = trace["final_decision"]
        router_input: RouterInput = trace["router_input"]
        expanded = {
            "trace_type": "router",
            "history_summary_hash": _hash_text(router_input.history_summary),
            "legal_memory_snapshot": (
                router_input.legal_memory.model_dump(mode="json") if router_input.legal_memory else None
            ),
            "rule_candidates": trace.get("rule_candidates") or [],
            "llm_called": trace.get("llm_called", False),
            "llm_raw_output": trace.get("llm_raw_output"),
            "llm_latency_ms": trace.get("llm_latency_ms", 0),
            "router_latency_ms": trace.get("total_latency_ms", 0),
            "final_decision": decision.model_dump(mode="json"),
        }
        try:
            async with self.session_factory() as db:
                db.add(
                    RagTrace(
                        trace_id=trace["trace_id"],
                        conversation_id=_safe_int(router_input.conversation_id),
                        user_id=_safe_int(router_input.user_id),
                        agent_type=decision.agent,
                        original_query=router_input.user_query,
                        rewritten_query=json.dumps(decision.model_dump(mode="json"), ensure_ascii=False),
                        expanded_queries=expanded,
                        total_latency_ms=int(trace.get("total_latency_ms") or 0),
                        retrieval_latency_ms=0,
                    )
                )
                await db.commit()
        except Exception as exc:
            logger.warning("Router Trace 写入失败: %s", exc.__class__.__name__)


def _safe_int(value: str) -> int | None:
    """把字符串 ID 安全转成数据库可接受的整数 ID。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _hash_text(value: str | None) -> str | None:
    """对摘要做哈希，避免 Trace 中重复保存长上下文。"""
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

