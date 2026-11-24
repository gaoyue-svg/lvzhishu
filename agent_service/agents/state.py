"""本文件定义四类业务 Agent 运行期共享的 LangGraph 状态结构。"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages

from agent_service.router.models import LegalMemory


class LegalAgentState(TypedDict, total=False):
    """业务 Agent 的完整运行期状态，初始字段由 Router state_mapper 注入。"""

    query: str
    conversation_id: str
    user_id: str
    tenant_id: str
    kb_ids: list[dict[str, Any]]
    intent: str
    legal_domain: str
    retrieval_scope: dict[str, Any]
    sub_questions: list[str]
    legal_context: dict[str, Any]
    time_context: dict[str, Any]
    execution_mode: str
    risk_level: str
    needs_human_review: bool
    messages: Annotated[list[Any], add_messages]
    legal_memory: LegalMemory | dict[str, Any] | None
    history_summary: str

    rewritten_query: str
    retrieved_chunks: list[dict[str, Any]]
    retrieval_quality: str
    context_text: str
    citations: list[dict[str, Any]]
    citation_validation: dict[str, Any]
    tool_calls: list[dict[str, Any]]
    pending_tool_calls: list[dict[str, Any]]
    answer: str
    risk_alerts: list[dict[str, Any]]
    retry_count: int
    validation_retry_count: int
    trace_id: str
    document_id: str
    review_dimensions: list[str]
    contract_text: str
    contract_clauses: list[dict[str, Any]]


# ===== Supervisor 多 Agent 协同共享状态 =====
# P1+P2 阶段：Supervisor 编排器跨 Agent 共享的运行期状态。
# 与 LegalAgentState（单 Agent 内部）并存，互不污染。


class AgentResult(TypedDict, total=False):
    """单个 Agent 被 Supervisor 调用后的结构化产出。

    Supervisor 决策时只看 output_summary，不看完整 chunks/context_text，
    避免 LLM 上下文随轮次膨胀。
    """

    agent: str                         # agent_key，标识产出方
    round: int                         # 第几轮调用的
    input: str                         # Supervisor 给该 Agent 的子任务输入
    context_text: str                  # 该 Agent 检索/构建的上下文
    chunks: list[dict[str, Any]]       # 检索到的 chunks
    citations: list[dict[str, Any]]    # 该 Agent 产出的引用（局部编号）
    answer: str                        # 该 Agent 的局部答案
    trace_id: str                      # 检索 trace
    tool_calls: list[dict[str, Any]]   # 该 Agent 执行的工具调用（含规则风险等结果）
    output_summary: str                # 给 Supervisor 看的产出摘要


class SharedState(TypedDict, total=False):
    """Supervisor 多 Agent 协同的共享状态。

    初始字段由 /chat 入口注入，后续每轮由 Supervisor 节点更新。
    """

    # ===== 输入 =====
    query: str
    conversation_id: str
    user_id: str
    tenant_id: str
    kb_ids: list[dict[str, Any]]
    entry_hint: str                    # 入口建议 agent（来自规则候选最高分）
    legal_memory: LegalMemory | dict[str, Any] | None
    risk_level: str                    # 来自规则候选的风险预判
    max_rounds: int                    # 默认 5

    # ===== 上下文注入（doc 19 D3：修复 Supervisor/V2 分支上下文退化）=====
    # 由 /chat 入口从 Memory 与请求体补齐，规划/执行层据此喂给子 Agent。
    document_id: str                   # 已上传待审查文档 id
    legal_context: dict[str, Any]      # 法条定位增强检索（law_name/article_no）
    sub_questions: list[str]           # 案例分析多路检索
    time_context: dict[str, Any]       # 时间上下文
    history_summary: str               # 会话摘要，多轮追问识别
    uploaded_files: list[dict[str, Any]]
    available_kbs: list[dict[str, Any]]

    # ===== 查询改写层（orchestrator/query_rewrite.py 写入）=====
    original_query: str                # 改写前的原始用户提问（DB 已由 body.query 落库，此为下游副本）
    rewrite_meta: dict[str, Any]       # 改写元信息：{original_query, rewritten_query, method, notes}

    # ===== v2 编排结果（agent_service/orchestrator 写入）=====
    plan: dict[str, Any] | None        # Plan DAG（steps/slots）
    plan_slots: dict[str, Any]         # 执行期 slot 表（工作记忆）
    review_result: dict[str, Any]      # 审查结论（L1/L2/needs_human_review）
    intent: dict[str, Any]             # 意图识别层结构化输出

    # ===== Supervisor 决策历史 =====
    current_round: int
    agent_history: list[dict[str, Any]]
    # 每条形如:
    # {
    #   "round": 1,
    #   "agent": "law_qa",
    #   "input": "正当防卫的认定条件",
    #   "thought": "用户问正当防卫，先调 law_qa",
    #   "output_summary": "检索到 8 条相关法条，含刑法第20条",
    #   "chunks_count": 8,
    #   "citations_count": 3
    # }

    # ===== 多 Agent 产出累积 =====
    agent_results: list[AgentResult]

    # ===== 引用合并 =====
    merged_citations: list[dict[str, Any]]
    # 全局重编号后的引用列表

    # ===== 合成 =====
    final_answer: str
    final_citations: list[dict[str, Any]]
    risk_alerts: list[dict[str, Any]]
    trace_id: str                        # 首个检索 trace，落 message.retrieval_trace_id（VARCHAR(50)）
    trace_ids: list[str]                 # 全部 Agent 检索 trace 链路，供 run 级回放
    needs_human_review: bool

    # ===== 兜底标记 =====
    fallback_single_agent: bool        # True=Supervisor 不可用，退化为单 Agent
    fallback_reason: str

