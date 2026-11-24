"""本文件实现合同要素提取与摘要 Agent，输出结构化要素表与合同摘要。

ContractElementsAgent 读取已结构化的合同条款（由 ContractParser 产出），
在 reason 节点用 LLM 输出 JSON：
{
  "summary": "合同摘要(markdown)",
  "elements": { contract_name, contract_type, party_a, party_b, amount, payment_terms, ... }
}
该结构化数据是前端要素表渲染与报告导出的数据来源。
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..base import BaseAgent
from ..state import LegalAgentState


class ContractElementsAgent(BaseAgent):
    """合同要素提取 + 摘要 Agent：读取条款，输出结构化 JSON。"""

    agent_key = "contract_elements"
    agent_name = "要素提取"
    answer_temperature = 0.1
    default_top_k = 0
    default_rerank_top_k = 0

    async def retrieve_node(self, state: LegalAgentState) -> dict[str, Any]:
        """要素 Agent 不检索，直接用已有条款上下文。"""
        return {
            "context_text": state.get("context_text") or "",
            "retrieved_chunks": state.get("retrieved_chunks") or [],
            "retrieval_quality": "sufficient",
            "trace_id": state.get("trace_id") or "",
        }

    async def tool_decide_node(self, state: LegalAgentState) -> dict[str, Any]:
        """要素 Agent 不调用工具。"""
        return {"pending_tool_calls": []}

    def _build_reason_messages(self, state: LegalAgentState) -> list[dict[str, str]]:
        """组装要素提取 Prompt，让 LLM 输出结构化 JSON（摘要 + 要素）。"""
        chunks = state.get("retrieved_chunks") or []
        clauses_text = "\n".join(
            f"[{c.get('article_no', '')}] {c.get('title', '')}: {(c.get('text') or '')[:400]}"
            for c in chunks[:40]
            if c.get("chunk_level") != "chapter"
        )

        user_content = (
            "你是合同审阅专家。请阅读以下合同条款，输出合同摘要与关键要素。\n\n"
            f"合同条款：\n{clauses_text}\n\n"
            "只输出一个 JSON 对象，结构如下：\n"
            "{\n"
            '  "summary": "150-300字的合同摘要（含合同性质、核心权利义务、重要期限，可用 Markdown 分点）",\n'
            '  "elements": {\n'
            '    "contract_name": "合同名称",\n'
            '    "contract_type": "合同类型",\n'
            '    "party_a": {"name": "甲方名称", "role": "甲方角色"},\n'
            '    "party_b": {"name": "乙方名称", "role": "乙方角色"},\n'
            '    "amount": "合同金额",\n'
            '    "currency": "币种",\n'
            '    "payment_terms": "付款方式与节奏",\n'
            '    "payment_deadline": "付款期限",\n'
            '    "contract_term": "合同期限",\n'
            '    "effective_date": "生效日期",\n'
            '    "governing_law": "适用法律",\n'
            '    "jurisdiction": "争议解决/管辖",\n'
            '    "breach_liability": "违约责任",\n'
            '    "signing_requirements": "签署与生效条件",\n'
            '    "key_obligations": ["核心义务1", "核心义务2"],\n'
            '    "important_clauses": ["重要条款摘要1", "重要条款摘要2"]\n'
            "  }\n"
            "}\n"
            "无法识别的要素填空字符串，不要编造；列表类型为空数组。只输出 JSON 对象，不要其他文字。"
        )
        return [
            {"role": "system", "content": "你是合同审阅专家，只输出 JSON 对象，不解释。"},
            {"role": "user", "content": user_content},
        ]

    def _judge_retrieval_quality(self, context_text: str, chunks: list[dict[str, Any]]) -> str:
        """要素 Agent 始终 sufficient。"""
        return "sufficient"

    @staticmethod
    def parse_elements_json(answer: str) -> dict[str, Any]:
        """从 LLM 答案中解析 JSON 对象，兼容 Markdown 代码块包裹。"""
        if not answer:
            return {}
        cleaned = re.sub(r"```(?:json)?\s*", "", answer).strip().rstrip("```")
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
