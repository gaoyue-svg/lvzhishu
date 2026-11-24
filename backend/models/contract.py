"""本文件定义合同审查风险产出相关的 ORM 模型，映射 contract_risk 表。"""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, JSON, String, Text, text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models import Base


class ContractRisk(Base):
    """合同审查产出的单条风险记录，关联 task_log 与 knowledge_chunk。"""

    __tablename__ = "contract_risk"
    __table_args__ = (
        Index("idx_contract_risk_task", "task_id"),
        Index("idx_contract_risk_clause", "clause_id"),
        Index("idx_contract_risk_level", "task_id", "risk_level"),
        {"comment": "合同审查风险表"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 关联 task_log.id，对应一次合同审查任务
    task_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="审查任务ID(task_log.id)")
    document_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="合同文档ID")
    # 关联 knowledge_chunk.id，NULL 表示全局风险（如合同整体缺失条款）
    clause_id: Mapped[int | None] = mapped_column(BigInteger, default=None, comment="条款chunk ID，NULL=全局风险")
    # 冗余条款编号，便于前端直接展示，无需反查 knowledge_chunk
    article_no: Mapped[str | None] = mapped_column(String(50), default=None, comment="条款编号")
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, comment="风险等级: high/medium/low")
    risk_type: Mapped[str] = mapped_column(String(50), nullable=False, comment="风险类型: payment/jurisdiction/termination...")
    title: Mapped[str] = mapped_column(String(200), nullable=False, comment="风险标题")
    description: Mapped[str] = mapped_column(Text, nullable=False, comment="风险描述")
    excerpt: Mapped[str | None] = mapped_column(Text, default=None, comment="合同原文摘录")
    suggestion: Mapped[str | None] = mapped_column(Text, default=None, comment="修改建议")
    # 法律依据列表，如 ["民法典第585条"]，JSON 存储
    law_references: Mapped[list[str] | None] = mapped_column(JSON, default=None, comment="法律依据列表")
    # 风险来源：rule=规则引擎, rag=RAG检索, llm=LLM分析
    source: Mapped[str] = mapped_column(String(20), nullable=False, comment="风险来源: rule/rag/llm")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=sql_text("CURRENT_TIMESTAMP"), comment="创建时间"
    )
