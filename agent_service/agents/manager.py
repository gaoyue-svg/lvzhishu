"""本文件实现 AgentManager，按 RouterDecision.agent 调度四个业务 Agent。"""

from __future__ import annotations

from typing import Any

from agent_service.citation import CitationValidator
from agent_service.llm import BaseLLM
from agent_service.tools import ToolRegistry
from backend.utils.logger import get_logger
from embedding_service.embedding.embedding import BaseEmbedding
from rag_service.retrieval.context_builder import ContextBuilder
from rag_service.retrieval.reranker import ConfigurableLegalReranker, RuleLegalReranker
from rag_service.retrieval.retriever import HybridRetriever

from .article_locate import ArticleLocateAgent
from .base import BaseAgent
from .case_analysis import CaseAnalysisAgent
from .contract import ClauseAgent, ContractElementsAgent, LegalRAGAgent, RiskReportAgent, RuleAgent
from .contract_review import ContractReviewAgent
from .law_qa import LawQaAgent
from .registry import AgentCardRegistry, get_registry
from .supervisor import Supervisor

logger = get_logger(__name__)


class AgentManager:
    """业务 Agent 调度器，注册 key 与 Router AgentType 保持严格一致。"""

    _agent_classes: dict[str, type[BaseAgent]] = {
        "law_qa": LawQaAgent,
        "article_locate": ArticleLocateAgent,
        "contract_review": ContractReviewAgent,
        "case_analysis": CaseAnalysisAgent,
        # 合同审查多阶段子 Agent
        "contract_clause": ClauseAgent,
        "contract_rule": RuleAgent,
        "contract_rag": LegalRAGAgent,
        "contract_elements": ContractElementsAgent,
        "contract_risk_report": RiskReportAgent,
    }

    def __init__(
        self,
        *,
        bm25: Any,
        milvus: Any,
        embedding: BaseEmbedding,
        query_rewriter: Any,
        query_router: Any,
        context_builder: ContextBuilder,
        tool_registry: ToolRegistry,
        memory: Any,
        citation_validator: CitationValidator,
    ) -> None:
        """保存可跨请求复用的组件；DB 与 LLM 在 get_agent 时注入。"""
        self.bm25 = bm25
        self.milvus = milvus
        self.embedding = embedding
        self.query_rewriter = query_rewriter
        self.query_router = query_router
        self.context_builder = context_builder
        self.tool_registry = tool_registry
        self.memory = memory
        self.citation_validator = citation_validator

    def get_agent(self, agent_key: str, *, llm: BaseLLM, db: Any) -> BaseAgent:
        """按 RouterDecision.agent 创建对应业务 Agent。"""
        return self.create_agent(agent_key, llm=llm, db=db, embedding=self.embedding)

    def create_agent(
        self,
        agent_key: str,
        *,
        llm: BaseLLM,
        db: Any,
        embedding: BaseEmbedding | None = None,
        reranker: RuleLegalReranker | None = None,
    ) -> BaseAgent:
        """创建业务 Agent，并允许请求级覆盖 Embedding 模型配置。"""
        logger.info("[AgentManager] 开始分配业务 Agent agent_key=%s", agent_key)
        agent_cls = self._agent_classes.get(agent_key)
        if agent_cls is None:
            logger.warning("[AgentManager] 未知 Agent agent_key=%s，已注册=%s", agent_key, sorted(self._agent_classes))
            raise ValueError(f"未知 Agent: {agent_key}")
        retriever = HybridRetriever(
            bm25=self.bm25,
            milvus=self.milvus,
            embedding=embedding or self.embedding,
            reranker=reranker or ConfigurableLegalReranker(),
            query_rewriter=self.query_rewriter,
            query_router=self.query_router,
            db=db,
        )
        logger.info(
            "[AgentManager] 业务 Agent 已创建 agent_key=%s class=%s",
            agent_key,
            agent_cls.__name__,
        )
        return agent_cls(
            llm=llm,
            retriever=retriever,
            context_builder=self.context_builder,
            tool_registry=self.tool_registry,
            memory=self.memory,
            citation_validator=self.citation_validator,
            db=db,
        )

    @classmethod
    def supported_agents(cls) -> list[str]:
        """返回当前已注册的业务 Agent key。"""
        return sorted(cls._agent_classes)

    @property
    def registry(self) -> AgentCardRegistry:
        """返回进程级 Agent Card 注册表（doc 19 §5.1）。"""
        return get_registry()

    def create_supervisor(
        self,
        *,
        llm: BaseLLM,
        db: Any,
        embedding: BaseEmbedding | None = None,
        reranker: RuleLegalReranker | None = None,
        query_rewriter: Any | None = None,
    ) -> Supervisor:
        """创建 Supervisor 多 Agent 编排器实例。

        Supervisor 持有 agent_manager 引用，运行时通过 create_agent 动态创建子 Agent。
        embedding/reranker 未传时回退到应用级兜底实例；query_rewriter 为查询改写器。
        """
        return Supervisor(
            agent_manager=self,
            llm=llm,
            db=db,
            embedding=embedding or self.embedding,
            reranker=reranker,
            query_rewriter=query_rewriter,
        )
