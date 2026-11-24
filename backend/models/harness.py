"""Agent Harness 治理中间件数据表 ORM 模型（doc 21）：run 级 Trace / LLM 用量 / 在线评估。"""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Integer, JSON, String, Text, text as sql_text
from sqlalchemy.dialects.mysql import DECIMAL, FLOAT, MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from backend.models import Base


class AgentRunTrace(Base):
    """Agent run 级全链路 Trace 表，映射自 sql/migrations/007_agent_harness.sql。"""

    __tablename__ = "agent_run_trace"
    __table_args__ = {"comment": "Agent run 级全链路Trace表"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="主键ID")
    trace_id: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, comment="run 级链路ID")
    plan_id: Mapped[str | None] = mapped_column(String(50), default=None, comment="计划ID")
    conversation_id: Mapped[int | None] = mapped_column(BigInteger, default=None, comment="会话ID")
    user_id: Mapped[int | None] = mapped_column(BigInteger, default=None, comment="用户ID")
    query: Mapped[str | None] = mapped_column(Text, default=None, comment="改写后 query")
    intent: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None, comment="意图识别结果")
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None, comment="Plan DAG 快照")
    step_traces: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, default=None, comment="StepTrace[] 序列化")
    agent_results_summary: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, default=None, comment="各 Agent 产出摘要")
    review: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None, comment="Reviewer 结论")
    final_answer: Mapped[str | None] = mapped_column(MEDIUMTEXT, default=None, comment="最终答案")
    final_citations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, default=None, comment="最终引用列表")
    needs_human_review: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"), comment="是否需要人工复核")
    total_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"), comment="本次 run 总耗时(毫秒)")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=sql_text("'success'"), comment="状态: success/failed/hitl")
    error: Mapped[str | None] = mapped_column(Text, default=None, comment="错误信息")
    experiment_variant: Mapped[str | None] = mapped_column(String(40), default=None, comment="A/B 实验变体，如 synthesizer_ab:B")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=sql_text("CURRENT_TIMESTAMP"), comment="创建时间")


class LlmUsage(Base):
    """LLM 调用用量计费表，映射自 sql/migrations/007_agent_harness.sql。"""

    __tablename__ = "llm_usage"
    __table_args__ = {"comment": "LLM 调用用量计费表"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="主键ID")
    trace_id: Mapped[str] = mapped_column(String(50), nullable=False, comment="run 级链路ID")
    message_id: Mapped[int | None] = mapped_column(BigInteger, default=None, comment="消息ID(message.id)")
    user_id: Mapped[int | None] = mapped_column(BigInteger, default=None, comment="用户ID")
    provider: Mapped[str] = mapped_column(String(30), nullable=False, comment="LLM 提供方")
    model: Mapped[str] = mapped_column(String(60), nullable=False, comment="模型名称")
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"), comment="输入 token 数")
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"), comment="输出 token 数")
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"), comment="总 token 数")
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"), comment="单次调用耗时(毫秒)")
    cost: Mapped[float] = mapped_column(DECIMAL(10, 6), nullable=False, server_default=sql_text("0"), comment="估算成本(元)")
    purpose: Mapped[str] = mapped_column(String(30), nullable=False, server_default=sql_text("'general'"), comment="调用用途")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=sql_text("CURRENT_TIMESTAMP"), comment="创建时间")


class QuestionTrace(Base):
    """提问级 Agent/工具执行链路 Trace，映射自 sql/migrations/008_question_trace.sql。"""

    __tablename__ = "question_trace"
    __table_args__ = {"comment": "提问级 Agent/工具执行链路Trace表"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="主键ID")
    trace_id: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, comment="run 级链路ID")
    conversation_id: Mapped[int | None] = mapped_column(BigInteger, default=None, comment="会话ID")
    user_id: Mapped[int | None] = mapped_column(BigInteger, default=None, comment="用户ID")
    query: Mapped[str | None] = mapped_column(Text, default=None, comment="用户原始提问")
    intent: Mapped[str | None] = mapped_column(String(60), default=None, comment="意图/入口")
    engine: Mapped[str | None] = mapped_column(String(20), default=None, comment="编排引擎")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=sql_text("'success'"), comment="状态")
    agents: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, default=None, comment="Agent 调用序列(含嵌套 tools)")
    total_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"), comment="本次提问总耗时")
    answer_snippet: Mapped[str | None] = mapped_column(String(500), default=None, comment="最终答案摘要")
    error: Mapped[str | None] = mapped_column(Text, default=None, comment="错误信息")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=sql_text("CURRENT_TIMESTAMP"), comment="创建时间")


class EvaluationResult(Base):
    """Agent 产出质量评分表，映射自 sql/migrations/007_agent_harness.sql。"""

    __tablename__ = "evaluation_result"
    __table_args__ = {"comment": "Agent 产出质量评分表"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="主键ID")
    trace_id: Mapped[str] = mapped_column(String(50), nullable=False, comment="run 级链路ID")
    mode: Mapped[str] = mapped_column(String(10), nullable=False, server_default=sql_text("'online'"), comment="评分方式: online/offline")
    citation_score: Mapped[float | None] = mapped_column(FLOAT, default=None, comment="引用编号完整性得分")
    coverage: Mapped[float | None] = mapped_column(FLOAT, default=None, comment="引用覆盖度得分")
    grounded_score: Mapped[float | None] = mapped_column(FLOAT, default=None, comment="论断落地支撑得分")
    hallucination: Mapped[float | None] = mapped_column(FLOAT, default=None, comment="幻觉占比")
    overall: Mapped[float | None] = mapped_column(FLOAT, default=None, comment="加权总分")
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None, comment="失败论断/未覆盖法条等明细")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=sql_text("CURRENT_TIMESTAMP"), comment="创建时间")
