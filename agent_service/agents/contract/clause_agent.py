"""本文件实现合同理解 Agent，负责条款结构化读取与 LLM 补充分类。

ClauseAgent 从 knowledge_chunk 读取已结构化的合同条款（由 ContractParser 产出），
在 reason 节点用 LLM 对 other 类条款做精分类，并补充实体抽取。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import select

from backend.models.knowledge import KnowledgeChunk
from backend.utils.logger import get_logger

from ..base import BaseAgent
from ..state import LegalAgentState

logger = get_logger(__name__)


def _clauses_to_context(chunks: list[dict]) -> str:
    """把条款 dict 列表拼接为上下文文本，供 LLM 分类/要素提取使用。"""
    return "\n\n".join(
        f"{c['article_no']} {c['title']}\n{c['text']}" for c in chunks if c.get("chunk_level") != "chapter"
    )[:8000]


class ClauseAgent(BaseAgent):
    """合同理解 Agent：读取结构化条款，LLM 补充分类与实体。"""

    agent_key = "contract_clause"
    agent_name = "合同理解"
    answer_temperature = 0.1
    default_top_k = 0
    default_rerank_top_k = 0

    async def retrieve_node(self, state: LegalAgentState) -> dict[str, Any]:
        """读取合同条款：优先使用编排器注入的预置条款（会话上传模式），否则查 knowledge_chunk。"""
        # 会话上传模式：executor 把 plan_slots.clauses 作为 retrieved_chunks 覆盖注入，
        # 直接透传，无需查库（该模式不写入知识库）。
        supplied = state.get("retrieved_chunks")
        if supplied:
            return {
                "retrieved_chunks": supplied,
                "context_text": _clauses_to_context(supplied),
                "retrieval_quality": "sufficient",
                "trace_id": state.get("trace_id") or "",
            }
        if self.db is None:
            return {"context_text": "", "retrieved_chunks": [], "retrieval_quality": "sufficient"}

        document_id = state.get("document_id")
        if not document_id:
            return {"context_text": "", "retrieved_chunks": [], "retrieval_quality": "insufficient"}

        result = await self.db.execute(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.document_id == int(document_id))
            .order_by(KnowledgeChunk.chunk_index)
        )
        chunks = []
        for chunk in result.scalars().all():
            metadata = chunk.metadata_ or {}
            chunks.append({
                "chunk_id": str(chunk.id),
                "text": chunk.text or "",
                "article_no": metadata.get("article_no", ""),
                "title": metadata.get("title", ""),
                "clause_type": metadata.get("clause_type", "other"),
                "chunk_level": chunk.chunk_level or "section",
                "entities": metadata.get("entities", {}),
            })

        return {
            "retrieved_chunks": chunks,
            "context_text": _clauses_to_context(chunks),
            "retrieval_quality": "sufficient" if chunks else "insufficient",
            "trace_id": state.get("trace_id") or "",
        }

    async def tool_decide_node(self, state: LegalAgentState) -> dict[str, Any]:
        """ClauseAgent 不调用外部工具，分类由 LLM 在 reason 节点完成。"""
        return {"pending_tool_calls": []}

    @staticmethod
    def _needs_llm(state: LegalAgentState) -> bool:
        """是否存在规则未能分类（clause_type=other）且有正文的条款，需要 LLM 补充分类。

        会话上传模式条款由 ContractParser 规则预分类，通常全部命中，此时无需再调 LLM，
        避免无谓 token 消耗，也避免无 LLM 配置时整条链路在第一步就失败。
        """
        chunks = state.get("retrieved_chunks") or []
        return any(c.get("clause_type") == "other" and c.get("text") for c in chunks)

    async def reason_node(self, state: LegalAgentState) -> dict[str, Any]:
        """条款全部已分类时跳过 LLM，直接透传结构化条款。"""
        if not self._needs_llm(state):
            return {"answer": "合同条款已自动分类，无需 LLM 补充。"}
        return await super().reason_node(state)

    async def reason_stream(self, state: LegalAgentState) -> AsyncIterator[str]:
        """条款全部已分类时跳过 LLM 流式生成，透传结构化条款。"""
        if not self._needs_llm(state):
            state["answer"] = "合同条款已自动分类，无需 LLM 补充。"
            yield state["answer"]
            return
        async for piece in super().reason_stream(state):
            yield piece

    async def _chat_answer(self, state: LegalAgentState) -> str:
        """条款全部已分类时跳过 LLM，返回结构化提示文本。"""
        if not self._needs_llm(state):
            return "合同条款已自动分类，无需 LLM 补充。"
        return await super()._chat_answer(state)

    def _build_reason_messages(self, state: LegalAgentState) -> list[dict[str, str]]:
        """组装合同理解 Prompt，让 LLM 对 other 类条款补充分类。"""
        chunks = state.get("retrieved_chunks") or []
        other_clauses = [c for c in chunks if c.get("clause_type") == "other" and c.get("text")]
        user_content = (
            "以下是合同中未能自动分类的条款，请为每条识别 clause_type（payment/delivery/liability/"
            "termination/confidentiality/jurisdiction/term/ip/warranty/force_majeure/other）"
            "并补充 entities（金额、天数、比例等），输出 JSON 数组：\n\n"
        )
        for c in other_clauses[:30]:
            user_content += f"[{c.get('article_no', '')}] {c.get('text', '')[:500]}\n\n"

        if not other_clauses:
            user_content = "所有条款已自动分类，无需 LLM 补充。"

        return [
            {"role": "system", "content": "你是合同条款分类专家，只输出 JSON 数组，不解释。"},
            {"role": "user", "content": user_content},
        ]
