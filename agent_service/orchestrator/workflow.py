"""本文件实现固定流程的预置 Plan 模板（doc 19 §4.6）。

合同审查等流程固定任务不走 LLM 规划，直接载入模板并替换占位符，
避免 LLM 把固定流水线规划错，同时修复合同多阶段子 Agent 数据断链（D2）。
"""

from __future__ import annotations

from typing import Any

from .plan import PlanDAG, PlanStep

# 预置工作流模板。inputs 键为 LegalAgentState 字段名，outputs 键为 AgentResult 字段名。
PRESET_WORKFLOWS: dict[str, list[dict[str, Any]]] = {
    "contract_review": [
        {
            "step_id": "w1",
            "agent": "contract_clause",
            "goal": "读取合同条款并结构化",
            "inputs": {"document_id": "$user.document_id"},
            "outputs": {"chunks": "clauses"},
            "deps": [],
        },
        {
            "step_id": "w2",
            "agent": "contract_rule",
            "goal": "对条款跑确定性规则检测",
            "inputs": {"retrieved_chunks": "slot.clauses"},
            "outputs": {"tool_calls": "rule_risks"},
            "deps": ["w1"],
        },
        {
            "step_id": "w3",
            "agent": "contract_rag",
            "goal": "对高风险条款检索法条依据",
            "inputs": {"retrieved_chunks": "slot.clauses"},
            "outputs": {"chunks": "law_chunks", "citations": "law_cites", "context_text": "law_context"},
            "deps": ["w2"],
        },
        {
            "step_id": "w4",
            "agent": "contract_risk_report",
            "goal": "汇总条款/风险/法条输出风险报告",
            "inputs": {
                "retrieved_chunks": "slot.clauses",
                "tool_calls": "slot.rule_risks",
                "context_text": "slot.law_context",
            },
            "outputs": {"answer": "report"},
            "deps": ["w3"],
        },
        {
            "step_id": "w5",
            "agent": "synthesize",
            "goal": "合并引用并重写最终审查报告",
            "deps": ["w4"],
        },
    ],
    # 会话上传合同模式：条款已由 chat_agent 预解析进 plan_slots.clauses，
    # w1 透传预置条款（ClauseAgent 优先用注入的 retrieved_chunks），
    # w2/w3/w4 并行，w5 汇总三源输出风险报告，w6 合成。
    "contract_review_upload": [
        {
            "step_id": "w1",
            "agent": "contract_clause",
            "goal": "透传会话上传的合同条款并结构化",
            "inputs": {"retrieved_chunks": "slot.clauses"},
            "outputs": {"chunks": "clauses"},
            "deps": [],
        },
        {
            "step_id": "w2",
            "agent": "contract_rule",
            "goal": "对条款跑确定性规则检测",
            "inputs": {"retrieved_chunks": "slot.clauses"},
            "outputs": {"tool_calls": "rule_risks"},
            "deps": ["w1"],
        },
        {
            "step_id": "w3",
            "agent": "contract_elements",
            "goal": "提取合同要素并生成摘要",
            "inputs": {"retrieved_chunks": "slot.clauses"},
            "outputs": {"answer": "elements"},
            "deps": ["w1"],
        },
        {
            "step_id": "w4",
            "agent": "contract_rag",
            "goal": "对高风险条款检索法条依据",
            "inputs": {"retrieved_chunks": "slot.clauses"},
            "outputs": {"chunks": "law_chunks", "citations": "law_cites", "context_text": "law_context"},
            "deps": ["w1"],
        },
        {
            "step_id": "w5",
            "agent": "contract_risk_report",
            "goal": "汇总条款/风险/法条输出风险报告",
            "inputs": {
                "retrieved_chunks": "slot.clauses",
                "tool_calls": "slot.rule_risks",
                "context_text": "slot.law_context",
                "elements": "slot.elements",
            },
            "outputs": {"answer": "report"},
            "deps": ["w2", "w3", "w4"],
        },
        {
            "step_id": "w6",
            "agent": "synthesize",
            "goal": "合并引用并重写最终审查报告",
            "deps": ["w5"],
        },
    ],
}


def build_preset_plan(workflow: str, *, query: str, plan_id: str = "") -> PlanDAG | None:
    """按工作流名载入预置计划；模板不存在时返回 None 由上层走 LLM 规划。"""
    template = PRESET_WORKFLOWS.get(workflow)
    if not template:
        return None
    return PlanDAG(plan_id=plan_id, query=query, steps=[PlanStep(**item) for item in template])


def match_preset_workflow(intent: dict[str, Any], shared_state: dict[str, Any]) -> str | None:
    """判断是否应走预置工作流，返回工作流名或 None。

    当前仅合同审查：需要 document_id 且意图命中 contract_review 的合同子 Agent 链路。
    """
    entry_hint = str(intent.get("entry_hint") or shared_state.get("entry_hint") or "")
    document_id = str(shared_state.get("document_id") or "")
    # 会话上传模式：条款已预解析进 plan_slots.clauses，走上传专用工作流。
    if shared_state.get("uploaded_contracts") or entry_hint == "contract_review_upload":
        return "contract_review_upload"
    if entry_hint == "contract_review" or any(
        entry_hint.startswith(prefix) for prefix in ("contract_clause", "contract_rule", "contract_rag", "contract_risk_report")
    ):
        return "contract_review"
    if document_id and "contract" in (intent.get("category") or ""):
        return "contract_review"
    return None
