"""本文件实现法律 RAG Agent，对高风险合同条款检索相关法条。

LegalRAGAgent 复用 HybridRetriever，针对规则检测命中的高风险条款构造检索 query，
检索民法典、合同编等相关法条，作为风险分析的法律依据。
"""

from __future__ import annotations

import asyncio
from typing import Any

from backend.config import settings
from backend.utils.logger import get_logger

from ..base import BaseAgent
from ..state import LegalAgentState


logger = get_logger(__name__)


class LegalRAGAgent(BaseAgent):
    """法律 RAG Agent：对高风险条款查相关法条。"""

    agent_key = "contract_rag"
    agent_name = "法律检索"
    answer_temperature = 0.2
    default_top_k = 10
    default_rerank_top_k = 5

    async def retrieve_node(self, state: LegalAgentState) -> dict[str, Any]:
        """对规则检测命中的高风险条款逐条检索法条。"""
        # 从 state 获取规则检测结果或原始条款
        chunks = state.get("retrieved_chunks") or []
        high_risk_clauses = [
            c for c in chunks
            if c.get("chunk_level") != "chapter" and c.get("text")
        ]
        # 优先检索有风险关键词的条款
        risk_keywords = ("违约", "解除", "管辖", "付款", "保密", "期限", "赔偿")
        priority_clauses = [
            c for c in high_risk_clauses
            if any(kw in (c.get("text") or "") for kw in risk_keywords)
        ]
        candidates = priority_clauses or high_risk_clauses
        target_clauses: list[dict[str, Any]] = []
        seen_queries: set[str] = set()
        for clause in candidates:
            query = self._build_legal_query(clause)
            if query in seen_queries:
                continue
            seen_queries.add(query)
            target_clauses.append(clause)
            if len(target_clauses) >= max(1, settings.contract_rag_max_queries):
                break

        all_chunks: list[dict[str, Any]] = []
        context_parts: list[str] = []
        for clause in target_clauses:
            query = self._build_legal_query(clause)
            try:
                retrieval = await asyncio.wait_for(
                    self.retriever.retrieve(
                        query,
                        kb_ids=self._extract_kb_ids(state),
                        top_k=self.default_top_k,
                        rerank_top_k=self.default_rerank_top_k,
                    ),
                    timeout=settings.contract_rag_query_timeout,
                )
            except TimeoutError:
                logger.warning("合同法条单查询超时，跳过并保留其他结果 query=%r", query[:120])
                continue
            except Exception as exc:  # noqa: BLE001
                logger.warning("合同法条单查询失败，跳过并保留其他结果 error=%s", exc.__class__.__name__)
                continue
            for hit in retrieval.chunks:
                chunk_dict = hit.to_dict()
                if chunk_dict not in all_chunks:
                    all_chunks.append(chunk_dict)

        # 构建法条上下文
        from rag_service.retrieval.citation import build_citations
        citations = await build_citations(all_chunks)
        context_result = await self.context_builder.build(
            all_chunks, citations, max_tokens=settings.context_max_tokens
        )

        return {
            "retrieved_chunks": all_chunks,
            "citations": citations,
            "context_text": context_result.context_text or "（未检索到相关法条）",
            "retrieval_quality": "sufficient" if all_chunks else "insufficient",
            "trace_id": state.get("trace_id") or "",
        }

    async def reason_node(self, state: LegalAgentState) -> dict[str, Any]:
        """用检索结果生成确定性中间摘要，避免为编排内部步骤再次调用 LLM。

        contract_rag 的职责是向后续 RiskReportAgent 提供法条 chunks、citations 和
        context_text；最终自然语言报告由 w5/w6 生成。旧实现沿用 BaseAgent 的完整
        LLM 推理节点，导致多条款检索完成后还要等待一次大上下文生成，容易超过
        Executor 的 60 秒步骤上限。
        """
        citations = list(state.get("citations") or [])
        if not citations:
            return {"answer": "未检索到可引用的相关法条，后续报告不得生成法条编号。"}

        items: list[str] = []
        for position, citation in enumerate(citations[:8], start=1):
            index = citation.get("index") or position
            law_name = str(citation.get("law_name") or citation.get("title") or "法律依据").strip()
            article_no = str(citation.get("article_no") or "").strip()
            label = f"{law_name}第{article_no}条" if article_no else law_name
            items.append(f"{label}[{index}]")
        return {"answer": "已检索到相关法律依据：" + "；".join(items) + "。"}

    @staticmethod
    def _build_legal_query(clause: dict[str, Any]) -> str:
        """从条款构造法条检索 query。"""
        clause_type = clause.get("clause_type", "other")
        text = (clause.get("text") or "")[:200].replace("\n", " ")
        type_map = {
            "payment": "付款 支付 报酬 期限",
            "liability": "违约责任 违约金 赔偿",
            "termination": "合同解除 终止",
            "jurisdiction": "管辖 争议解决 仲裁",
            "confidentiality": "保密义务",
            "term": "合同期限 有效期",
        }
        type_keywords = type_map.get(clause_type, "合同")
        return f"{type_keywords} 民法典 合同编 {text}".strip()

    def _build_reason_messages(self, state: LegalAgentState) -> list[dict[str, str]]:
        """输出法条依据摘要，供 RiskReportAgent 引用。"""
        context_text = state.get("context_text") or "（未检索到相关法条）"
        user_content = (
            "以下是检索到的相关法条，请提取与合同审查相关的法律依据，"
            "输出 JSON 数组（每项含 law_name、article_no、summary）：\n\n"
            + context_text[:6000]
        )
        return [
            {"role": "system", "content": "你是法律依据提取器，只输出 JSON 数组。"},
            {"role": "user", "content": user_content},
        ]
