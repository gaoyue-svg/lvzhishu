"""本文件实现案例分析 Agent，组合本地法条检索和 Tavily 联网来源。"""

from __future__ import annotations

from typing import Any

from agent_service.prompts import get_prompt
from rag_service.retrieval.citation import build_citations

from .base import BaseAgent
from .state import LegalAgentState


class CaseAnalysisAgent(BaseAgent):
    """面向类案分析和裁判规则归纳的业务 Agent。"""

    agent_key = "case_analysis"
    agent_name = "案例分析"
    default_top_k = 20
    default_rerank_top_k = 10

    async def retrieve_node(self, state: LegalAgentState) -> dict[str, Any]:
        """按 Router 拆出的 sub_questions 多路检索，再统一构建上下文。"""
        kb_ids = self._extract_kb_ids(state)
        queries = [state.get("query") or ""]
        queries.extend(str(item) for item in state.get("sub_questions") or [] if item)
        merged: dict[str, dict[str, Any]] = {}
        trace_id = state.get("trace_id") or ""
        for query in list(dict.fromkeys(queries)):
            retrieval = await self.retriever.retrieve(
                query,
                kb_ids=kb_ids,
                top_k=self.default_top_k,
                rerank_top_k=self.default_rerank_top_k,
            )
            trace_id = trace_id or str((retrieval.trace or {}).get("trace_id") or "")
            for hit in retrieval.chunks:
                data = hit.to_dict()
                old = merged.get(data["chunk_id"])
                if old is None or float(data.get("score") or 0) > float(old.get("score") or 0):
                    merged[data["chunk_id"]] = data
        chunks = sorted(merged.values(), key=lambda item: float(item.get("score") or 0), reverse=True)[
            : self.default_rerank_top_k
        ]
        citations = await build_citations(chunks)
        context = await self.context_builder.build(chunks, citations, max_tokens=self._context_tokens())
        return {
            "retrieved_chunks": chunks,
            "citations": citations,
            "context_text": context.context_text,
            "retrieval_quality": self._judge_retrieval_quality(context.context_text, chunks),
            "trace_id": trace_id,
        }

    async def tool_decide_node(self, state: LegalAgentState) -> dict[str, Any]:
        """案例分析需要联网搜索类案；Tavily 不可用时工具内部降级。"""
        return {
            "pending_tool_calls": [
                {
                    "name": "web_search",
                    "args": {
                        "query": f"{state.get('query')} 类似案例 裁判规则",
                        "max_results": 5,
                    },
                }
            ]
        }

    def system_prompt(self) -> str:
        """返回案例分析的回答约束。"""
        return get_prompt("case_analysis_system")

    @staticmethod
    def _context_tokens() -> int:
        """案例分析保留稍长上下文，便于容纳多争点法条。"""
        return 5000

