"""本文件实现法条定位 Agent，聚焦具体条文查找、条款树整理与原文引用。"""

from __future__ import annotations

from typing import Any

from agent_service.prompts import get_prompt

from .base import BaseAgent
from .state import LegalAgentState


class ArticleLocateAgent(BaseAgent):
    """面向法条定位和条文解释的业务 Agent。"""

    agent_key = "article_locate"
    agent_name = "法条定位"
    default_top_k = 20
    default_rerank_top_k = 10
    answer_temperature = 0.1

    async def tool_decide_node(self, state: LegalAgentState) -> dict[str, Any]:
        """对已召回法条执行条款树整理，辅助前端展示上下位结构。"""
        return {
            "pending_tool_calls": [
                {
                    "name": "article_tree",
                    "args": {"chunks": state.get("retrieved_chunks") or []},
                }
            ]
        }

    def _retrieval_query(self, state: LegalAgentState) -> str:
        """法条定位优先叠加法律名和条号，提高 BM25 命中率。"""
        context = state.get("legal_context") or {}
        parts = [state.get("query") or ""]
        if context.get("law_name"):
            parts.append(str(context["law_name"]))
        if context.get("article_no"):
            parts.append(str(context["article_no"]))
        return " ".join(part for part in parts if part).strip()

    def system_prompt(self) -> str:
        """返回法条定位的回答约束。"""
        return get_prompt("article_locate_system")

