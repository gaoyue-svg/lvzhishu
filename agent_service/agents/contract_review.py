"""本文件实现合同审查 Agent，完成合同文本抽取、条款切分、规则风险与 LLM 审查。"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select

from agent_service.prompts import format_prompt, get_prompt
from backend.models.knowledge import KnowledgeChunk, KnowledgeDocument

from .base import BaseAgent
from .state import LegalAgentState


class ContractReviewAgent(BaseAgent):
    """面向合同审查的业务 Agent。"""

    agent_key = "contract_review"
    agent_name = "合同审查"
    answer_temperature = 0.1
    default_rerank_top_k = 10

    async def retrieve_node(self, state: LegalAgentState) -> dict[str, Any]:
        """合同审查先抽取合同文本，再按合同主题检索相关法条。"""
        contract_text = state.get("contract_text") or await self._load_contract_text(state)
        query = self._contract_retrieval_query(state, contract_text)
        retrieval_state = dict(state)
        retrieval_state["query"] = query
        base_result = await super().retrieve_node(LegalAgentState(**retrieval_state))
        base_result["contract_text"] = contract_text
        return base_result

    async def tool_decide_node(self, state: LegalAgentState) -> dict[str, Any]:
        """调用条款切分和规则风险工具，为 LLM 审查提供结构化输入。"""
        contract_text = state.get("contract_text") or ""
        return {
            "pending_tool_calls": [
                {"name": "contract_clause_parser", "args": {"text": contract_text}},
                {
                    "name": "contract_risk_rules",
                    "args": {
                        "text": contract_text,
                        "dimensions": state.get("review_dimensions") or [],
                    },
                },
            ]
        }

    def _build_reason_messages(self, state: LegalAgentState) -> list[dict[str, str]]:
        """组装合同审查专用 Prompt，包含合同原文、规则风险和法条上下文。"""
        review_dimensions = state.get("review_dimensions") or ["legality", "fairness", "completeness"]
        user_content = format_prompt(
            "contract_review_user",
            review_dimensions=review_dimensions,
            contract_text=(state.get("contract_text") or "")[:12000],
            context_text=state.get("context_text") or "（未检索到相关法条）",
            tool_calls=self._json(state.get("tool_calls") or []),
        )
        return [
            {"role": "system", "content": self.system_prompt()},
            {"role": "user", "content": user_content},
        ]

    def system_prompt(self) -> str:
        """返回合同审查的回答约束。"""
        return get_prompt("contract_review_system")

    async def _load_contract_text(self, state: LegalAgentState) -> str:
        """从已入库文档读取合同文本；OCR 不可用或文本为空时明确报错。"""
        if self.db is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="合同审查缺少数据库会话")
        document_id = state.get("document_id")
        if not document_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先上传需要审查的合同文档")
        result = await self.db.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.id == int(document_id),
                KnowledgeDocument.user_id == int(state.get("user_id") or 0),
            )
        )
        document = result.scalar_one_or_none()
        if document is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="合同文档不存在")
        if document.raw_markdown and document.raw_markdown.strip():
            return document.raw_markdown.strip()
        chunk_result = await self.db.execute(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.document_id == document.id)
            .order_by(KnowledgeChunk.chunk_index)
        )
        text = "\n\n".join(chunk.text for chunk in chunk_result.scalars().all() if chunk.text)
        if not text.strip():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="未能读取合同文本，请上传可复制文本或清晰扫描件后重新解析",
            )
        return text.strip()

    @staticmethod
    def _contract_retrieval_query(state: LegalAgentState, contract_text: str) -> str:
        """从合同开头和审查维度生成检索 query，避免把整份合同塞进检索器。"""
        dimensions = " ".join(state.get("review_dimensions") or [])
        preview = contract_text[:800].replace("\n", " ")
        return f"合同审查 {dimensions} 违约 解除 责任 管辖 {preview}".strip()

