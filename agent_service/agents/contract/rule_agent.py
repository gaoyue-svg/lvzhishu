"""本文件实现规则检测 Agent，对每条合同条款跑确定性规则引擎。

RuleAgent 复用 ContractRiskRuleTool，在 tool_decide 节点对每条条款生成规则检测调用，
在 reason 节点汇总命中结果，输出风险候选清单。
"""

from __future__ import annotations

import json
from typing import Any

from ..base import BaseAgent
from ..state import LegalAgentState


class RuleAgent(BaseAgent):
    """规则检测 Agent：对条款跑确定性规则，输出风险候选。"""

    agent_key = "contract_rule"
    agent_name = "规则检测"
    answer_temperature = 0.0
    default_top_k = 0
    default_rerank_top_k = 0

    async def retrieve_node(self, state: LegalAgentState) -> dict[str, Any]:
        """规则检测不需要检索，直接进入工具阶段。"""
        chunks = state.get("retrieved_chunks") or []
        return {
            "context_text": "",
            "retrieved_chunks": chunks,
            "retrieval_quality": "sufficient" if chunks else "insufficient",
            "trace_id": state.get("trace_id") or "",
        }

    async def tool_decide_node(self, state: LegalAgentState) -> dict[str, Any]:
        """对每条叶子条款生成 contract_risk_rules 工具调用。"""
        chunks = state.get("retrieved_chunks") or []
        calls: list[dict[str, Any]] = []
        for chunk in chunks:
            if chunk.get("chunk_level") == "chapter":
                continue
            text = chunk.get("text") or ""
            if not text.strip():
                continue
            calls.append({
                "name": "contract_risk_rules",
                "args": {"text": text, "dimensions": []},
            })
        return {"pending_tool_calls": calls}

    def _build_reason_messages(self, state: LegalAgentState) -> list[dict[str, str]]:
        """汇总规则命中结果为结构化风险候选清单。"""
        tool_calls = state.get("tool_calls") or []
        risks: list[dict[str, Any]] = []
        for call in tool_calls:
            result = call.get("result") or {}
            for risk in result.get("risks", []):
                risks.append({
                    "code": risk.get("code"),
                    "level": risk.get("level"),
                    "message": risk.get("message"),
                    "excerpt": risk.get("excerpt", "")[:200],
                })

        user_content = (
            f"规则检测命中 {len(risks)} 条风险候选，请汇总为 JSON：\n"
            + json.dumps(risks, ensure_ascii=False)
        )
        return [
            {"role": "system", "content": "你是规则检测汇总器，只输出 JSON 风险数组。"},
            {"role": "user", "content": user_content},
        ]

    def _judge_retrieval_quality(self, context_text: str, chunks: list[dict[str, Any]]) -> str:
        """规则检测不依赖检索质量，始终 sufficient。"""
        return "sufficient"
