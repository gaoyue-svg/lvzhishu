"""本文件负责把 RouterDecision 映射为后续业务 Agent 可消费的初始状态。"""

from __future__ import annotations

from typing import Any, TypedDict

from agent_service.router.models import LegalMemory, RouterDecision, RouterInput


class LegalAgentState(TypedDict, total=False):
    """业务 Agent 的轻量初始状态定义，后续 LangGraph 节点可继续扩展字段。"""

    query: str
    conversation_id: str
    user_id: str
    tenant_id: str
    kb_ids: list[dict[str, Any]]
    intent: str
    legal_domain: str
    retrieval_scope: dict[str, Any]
    sub_questions: list[str]
    time_context: dict[str, Any]
    legal_context: dict[str, Any]
    execution_mode: str
    risk_level: str
    needs_human_review: bool
    legal_memory: LegalMemory | None
    history_summary: str
    messages: list[dict[str, Any]]
    trace_id: str


def build_initial_state(decision: RouterDecision, router_input: RouterInput) -> LegalAgentState:
    """Router 输出 → Agent 初始 State 映射。"""
    return LegalAgentState(
        query=router_input.user_query,
        conversation_id=router_input.conversation_id,
        user_id=router_input.user_id,
        tenant_id=router_input.tenant_id,
        kb_ids=router_input.available_kbs,
        intent=decision.task_type,
        legal_domain=decision.retrieval_scope.category,
        retrieval_scope=decision.retrieval_scope.model_dump(mode="json"),
        sub_questions=decision.sub_questions,
        time_context=decision.time_context.model_dump(mode="json"),
        legal_context=decision.legal_context.model_dump(mode="json"),
        execution_mode=decision.execution_mode,
        risk_level=decision.risk_level,
        needs_human_review=decision.needs_human_review,
        legal_memory=router_input.legal_memory,
        history_summary=router_input.history_summary or "",
        messages=[],
        trace_id="",
    )

