"""本文件实现风险分析与报告生成 Agent，汇总三源产出结构化风险与报告。

RiskReportAgent 接收前三阶段产出（条款 + 规则风险 + 法条依据），
在 reason 节点用 LLM 输出结构化 JSON 风险数组，每个风险含：
clause、level、title、description、suggestion、law_reference。
同时生成 Markdown 审查报告供前端展示。
"""

from __future__ import annotations

import json
import re
from typing import Any

from agent_service.prompts import format_prompt, get_prompt

from ..base import BaseAgent
from ..state import LegalAgentState


class RiskReportAgent(BaseAgent):
    """风险分析 + 报告生成 Agent：汇总三源，输出结构化风险与报告。"""

    agent_key = "contract_risk_report"
    agent_name = "风险报告"
    answer_temperature = 0.1
    default_top_k = 0
    default_rerank_top_k = 0

    async def retrieve_node(self, state: LegalAgentState) -> dict[str, Any]:
        """报告 Agent 不检索，直接用已有上下文。"""
        return {
            "context_text": state.get("context_text") or "",
            "retrieved_chunks": state.get("retrieved_chunks") or [],
            "retrieval_quality": "sufficient",
            "trace_id": state.get("trace_id") or "",
        }

    async def tool_decide_node(self, state: LegalAgentState) -> dict[str, Any]:
        """报告 Agent 不调用工具。"""
        return {"pending_tool_calls": []}

    def _build_reason_messages(self, state: LegalAgentState) -> list[dict[str, str]]:
        """组装风险分析 Prompt，包含条款、规则风险和法条上下文。"""
        chunks = state.get("retrieved_chunks") or []
        context_text = state.get("context_text") or "（未检索到相关法条）"
        tool_calls = state.get("tool_calls") or []

        # 汇总条款
        clauses_text = "\n".join(
            f"[{c.get('article_no', '')}] {c.get('title', '')}: {(c.get('text') or '')[:300]}"
            for c in chunks[:30]
            if c.get("chunk_level") != "chapter"
        )

        # 汇总规则风险
        rule_risks = []
        for call in tool_calls:
            result = call.get("result") or {}
            for risk in result.get("risks", []):
                rule_risks.append(risk)
        rule_text = json.dumps(rule_risks, ensure_ascii=False) if rule_risks else "无规则命中"

        user_content = (
            "你是合同风险审查专家。请基于以下信息输出结构化风险报告。\n\n"
            f"合同条款：\n{clauses_text}\n\n"
            f"规则检测结果：\n{rule_text}\n\n"
            f"相关法条：\n{context_text[:4000]}\n\n"
            "请输出 JSON 数组，每个风险项包含字段：\n"
            "- clause: 条款位置\n"
            "- level: high/medium/low\n"
            "- title: 风险标题\n"
            "- description: 风险描述\n"
            "- suggestion: 修改建议\n"
            "- law_reference: 法律依据数组\n"
            "只输出 JSON 数组，不要其他文字。"
        )
        return [
            {"role": "system", "content": "你是合同风险审查专家，只输出 JSON 风险数组。"},
            {"role": "user", "content": user_content},
        ]

    def _judge_retrieval_quality(self, context_text: str, chunks: list[dict[str, Any]]) -> str:
        """报告 Agent 始终 sufficient。"""
        return "sufficient"

    @staticmethod
    def parse_risk_json(answer: str) -> list[dict[str, Any]]:
        """从 LLM 答案中解析 JSON 风险数组，兼容 Markdown 代码块包裹。"""
        if not answer:
            return []
        # 去掉 ```json ... ``` 包裹
        cleaned = re.sub(r"```(?:json)?\s*", "", answer).strip().rstrip("```")
        # 尝试提取首个 JSON 数组
        match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if not match:
            return []
        try:
            risks = json.loads(match.group(0))
            return risks if isinstance(risks, list) else []
        except (json.JSONDecodeError, TypeError):
            return []
