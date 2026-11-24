"""本文件提供 Agent 编排层接口，包含 Router 调试、SSE 对话和合同审查入口。"""

from __future__ import annotations

import io
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Annotated, Any
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from agent_service.agents import sse_event
from agent_service.agents.dependencies import AgentManagerDep
from agent_service.agents.state import SharedState
from agent_service.experiment import apply_experiment
from agent_service.guard.dependencies import release_concurrency, run_input_guard
from agent_service.harness.execution_trace import (
    ExecutionTracer,
    flush_execution_trace,
    get_current_tracer,
    reset_execution_tracer,
    set_execution_tracer,
)
from agent_service.prompts import reset_prompt_versions
from agent_service.router import RouterDecision, RouterInput
from agent_service.router.fallback import _is_high_risk
from agent_service.router.rules import is_document_generation_query
from agent_service.router.state_mapper import build_initial_state
from agent_service.llm.dependencies import LLMDep
from agent_service.llm.usage import (
    UsageCollector,
    flush_usage,
    reset_usage_collector,
    set_usage_collector,
)
from agent_service.memory.conversation import compress_history_with_llm, enrich_legal_memory, load_recent_history
from agent_service.router.dependencies import RouterAgentDep
from backend.config import settings
from backend.database import get_db
from backend.models.conversation import Conversation, Message
from backend.models.knowledge import KnowledgeBase
from backend.models.knowledge import KnowledgeDocument
from backend.models.user import User
from backend.schemas.response import ApiResponse
from backend.services.auth import get_current_user
from backend.services.llm_config import resolve_runtime_config
from backend.services.report_exporter import build_legal_document_docx, infer_legal_document_title
from backend.storage.oss import OSSClient, get_oss
from backend.utils.logger import get_logger
from backend.utils.tool_context import ToolContext, reset_tool_context, set_tool_context
from embedding_service.embedding.embedding import EmbeddingFactory
from rag_service.retrieval.reranker import ConfigurableLegalReranker

logger = get_logger(__name__)

router = APIRouter(prefix="/api/agent", tags=["Agent"])


class AgentRouteRequest(BaseModel):
    """Router 决策接口请求体。"""

    query: str = Field(min_length=1)
    conversation_id: str = ""
    kb_ids: list[str] = Field(default_factory=list)
    history_summary: str | None = None
    legal_memory: dict[str, Any] | None = None
    uploaded_files: list[dict[str, Any]] = Field(default_factory=list)


class AgentChatRequest(BaseModel):
    """Agent SSE 对话接口请求体。

    uploaded_files：会话已上传文件（doc 19 D 低危项，修复 Supervisor 分支上下文退化）；
    document_id / review_dimensions：v2 编排下合同审查经 /chat 直达预置工作流使用。
    """

    query: str = Field(min_length=1)
    conversation_id: str = ""
    kb_ids: list[str] = Field(default_factory=list)
    uploaded_files: list[dict[str, Any]] = Field(default_factory=list)
    document_id: str = ""
    review_dimensions: list[str] = Field(default_factory=lambda: ["legality", "fairness", "completeness"])


class ContractReviewRequest(BaseModel):
    """合同审查专用入口请求体。"""

    document_id: str
    conversation_id: str = ""
    review_dimensions: list[str] = Field(default_factory=lambda: ["legality", "fairness", "completeness"])
    contract_type: str | None = None
    kb_ids: list[str] = Field(default_factory=list)


@router.post("/route", response_model=ApiResponse[RouterDecision])
async def route_agent(
    body: AgentRouteRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    router_agent: RouterAgentDep,
    user_llm: LLMDep,
) -> ApiResponse[RouterDecision]:
    """只运行 Router 决策，不执行后续业务 Agent，便于前后端联调和 Bad Case 复盘。"""
    # Input Guard：调试端点同样做输入与越权闸门（不占并发槽位）。
    await run_input_guard(query=body.query, kb_ids=body.kb_ids, user_id=current_user.id, db=db, with_concurrency=False)
    available_kbs = await _load_user_kbs(db, current_user.id, body.kb_ids)
    router_input = RouterInput(
        user_query=body.query,
        conversation_id=body.conversation_id,
        user_id=str(current_user.id),
        tenant_id=str(current_user.id),
        history_summary=body.history_summary,
        legal_memory=body.legal_memory,
        uploaded_files=body.uploaded_files,
        available_kbs=available_kbs,
    )
    decision = await router_agent.route(router_input, llm=user_llm)
    return ApiResponse(data=decision)


@router.get("/message/{message_id}/export")
async def export_generated_document(
    message_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    oss: Annotated[OSSClient, Depends(get_oss)],
) -> StreamingResponse:
    """把当前用户的一条 Assistant 回答导出为 Word 文书。"""
    result = await db.execute(
        select(Message).where(
            Message.id == message_id,
            Message.user_id == current_user.id,
            Message.role == "assistant",
        )
    )
    message = result.scalar_one_or_none()
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="可导出的回答不存在")
    request_result = await db.execute(
        select(Message)
        .where(
            Message.conversation_id == message.conversation_id,
            Message.user_id == current_user.id,
            Message.role == "user",
            Message.id < message.id,
        )
        .order_by(desc(Message.id))
        .limit(1)
    )
    request_message = request_result.scalar_one_or_none()
    request_text = request_message.content if request_message else ""

    # 用户请求的是“模板”且知识库已有同案由 DOCX 时，直接返回原始模板。
    # 这样既保留官方/用户模板的表格、复选框和留白，也避免模型重写后退化成
    # 带“填写要点”的通用文本。找不到高匹配模板时才使用下方生成式兜底。
    template = await _find_matching_knowledge_template(
        db,
        user_id=current_user.id,
        request_text=request_text,
    )
    if template is not None:
        with TemporaryDirectory(prefix="lawagent-template-") as tmp_dir:
            target = Path(tmp_dir) / template.filename
            await oss.download_file(template.oss_bucket, template.oss_key, str(target))
            payload = io.BytesIO(target.read_bytes())
        safe_template_name = "".join(
            char for char in template.filename if char not in '\\/:*?"<>|'
        ).strip() or "LawAgent法律文书.docx"
        return StreamingResponse(
            payload,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(safe_template_name)}"
            },
        )

    title = infer_legal_document_title(message.content, request_text=request_text)
    buffer = build_legal_document_docx(
        content_markdown=message.content,
        title=title,
        request_text=request_text,
    )
    safe_name = "".join(char for char in title if char not in '\\/:*?\"<>|').strip() or "LawAgent法律文书"
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(safe_name + '.docx')}"
    }
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=headers,
    )


async def _find_matching_knowledge_template(
    db: AsyncSession,
    *,
    user_id: int,
    request_text: str,
) -> KnowledgeDocument | None:
    """按文书类型和案由选择用户知识库中已有的原始 DOCX 模板。"""
    query = request_text.replace("起讼状", "起诉状").replace("贷款", "借贷")
    dispute_type = _classify_civil_complaint_template(query)
    if dispute_type is None:
        return None
    result = await db.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.user_id == user_id,
            KnowledgeDocument.file_type == "docx",
            KnowledgeDocument.parse_status == "completed",
        )
    )
    candidates = list(result.scalars().all())
    dispute_terms = {
        "lending": ("借贷", "借款", "欠款"),
        "labor": ("劳动争议", "劳动纠纷", "劳动合同", "劳务纠纷"),
        "divorce": ("离婚", "婚姻纠纷"),
    }[dispute_type]

    def score(document: KnowledgeDocument) -> int:
        name = document.filename.replace("起讼状", "起诉状").replace("贷款", "借贷")
        value = 0
        if "起诉状" in name:
            value += 6
        if any(word in name for word in dispute_terms):
            value += 12
        if "模板" in name or "纠纷" in name:
            value += 2
        return value

    ranked = sorted(candidates, key=score, reverse=True)
    return ranked[0] if ranked and score(ranked[0]) >= 18 else None


def _classify_civil_complaint_template(request_text: str) -> str | None:
    """把民事起诉状请求稳定映射到知识库现有的三类原始模板。"""
    query = request_text.replace("起讼状", "起诉状").replace("贷款", "借贷")
    if "起诉状" not in query:
        return None
    categories = (
        ("lending", ("借贷", "借款", "欠款", "欠贷", "欠钱", "还款")),
        ("labor", ("劳动争议", "劳动纠纷", "劳动合同", "欠薪", "工资", "辞退", "工伤")),
        ("divorce", ("离婚", "婚姻纠纷", "抚养权", "夫妻共同财产")),
    )
    for category, terms in categories:
        if any(term in query for term in terms):
            return category
    return None


@router.post("/chat")
async def chat_agent(
    body: AgentChatRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    router_agent: RouterAgentDep,
    agent_manager: AgentManagerDep,
    user_llm: LLMDep,
) -> StreamingResponse:
    """SSE 流式对话入口：Router 决策后调度到四类业务 Agent。"""
    # Input Guard（doc 21 §4.1）：进入 pipeline 前做安全/预算闸门；拦截在此抛 4xx。
    await run_input_guard(query=body.query, kb_ids=body.kb_ids, user_id=current_user.id, db=db)

    async def event_stream():
        started = perf_counter()
        # Harness 治理：本次请求生成 run 级 trace_id 并绑定 LLM 用量收集器（doc 21），
        # agent_run_trace / llm_usage / evaluation_result 均用该 id 关联。
        run_trace_id = uuid4().hex
        usage_collector = UsageCollector()
        usage_token = set_usage_collector(usage_collector)
        # 提问级执行链路（doc 21 扩展）：绑定 ExecutionTracer，采集本提问调度了哪些 Agent、调用了哪些工具。
        execution_tracer = ExecutionTracer()
        tracer_token = set_execution_tracer(execution_tracer)
        # 本次提问的执行结果快照：各分支在 return 前写入，finally 统一冲刷到 question_trace。
        outcome: dict[str, Any] = {
            "status": "failed",
            "engine": "",
            "intent": "",
            "answer": "",
            "error": "",
            "conversation_id": None,
        }
        # A/B 实验：按 user_id 分流 prompt 版本（doc 21 Phase 3）；未启用时返回 ("none", None)
        experiment_variant, prompt_version_token = apply_experiment(current_user.id)
        # 设置请求级 ToolContext, 让 WebSearchTool 等单例工具能读取当前用户的 BYOK 配置。
        tool_ctx_token = set_tool_context(ToolContext(user_id=current_user.id, db=db))
        try:
            yield sse_event("progress", {"stage": "prepare", "message": "正在加载会话上下文与可用知识库"})
            available_kbs = await _load_user_kbs(db, current_user.id, body.kb_ids)
            logger.info(
                "[AgentRoute] 收到对话请求 user_id=%s conversation_id=%s kb_ids=%s supervisor_enabled=%s query=%r",
                current_user.id,
                body.conversation_id,
                body.kb_ids,
                settings.supervisor_enabled,
                body.query,
            )

            # 三类民事起诉状属于“已有原件交付”，不再让 LLM 把原模板改写成网页正文。
            # 命中后直接落一条带下载能力的答复；真正下载时由 export 接口从 OSS
            # 返回同一份原始 DOCX，从而完整保留表格、复选框、下划线和版式。
            matched_template = await _find_matching_knowledge_template(
                db,
                user_id=current_user.id,
                request_text=body.query,
            )
            if matched_template is not None:
                conversation = await _ensure_conversation(
                    db,
                    current_user=current_user,
                    conversation_id=body.conversation_id,
                    query=body.query,
                    agent_type="document_template",
                    kb_ids=body.kb_ids,
                )
                await _save_message(db, conversation.id, current_user.id, "user", body.query)
                answer = (
                    f"已从您的知识库匹配到原始模板《{matched_template.filename}》。\n\n"
                    "请点击下方“导出 Word (.docx)”下载原件。系统不会重新生成或改写该文档，"
                    "原有表格、复选框、填写空白和排版都会完整保留。"
                )
                message = await _save_message(
                    db,
                    conversation.id,
                    current_user.id,
                    "assistant",
                    answer,
                    latency_ms=int((perf_counter() - started) * 1000),
                )
                await _refresh_conversation_stats(db, conversation)
                outcome.update(
                    {
                        "status": "success",
                        "engine": "knowledge_template",
                        "intent": "document_generation",
                        "answer": answer,
                        "conversation_id": str(conversation.id),
                    }
                )
                yield sse_event(
                    "final",
                    {"answer": answer, "citations": [], "risk_alerts": [], "trace_id": run_trace_id},
                )
                yield sse_event(
                    "done",
                    {
                        "conversation_id": str(conversation.id),
                        "message_id": str(message.id),
                        "trace_id": run_trace_id,
                        "exportable_document": True,
                        "template_filename": matched_template.filename,
                    },
                )
                return

            # ===== 多 Agent 编排分支（V2 或 V1 Supervisor）=====
            # 会话上传合同文件时强制走 v2 预置工作流（多 Agent 深度分析），
            # 其余查询遵循 multiagent_v2_enabled / supervisor_enabled 开关。
            has_contract_upload = any(
                (file.get("doc_type") or "").lower() == "contract" or file.get("upload_id") or file.get("file_id")
                for file in (body.uploaded_files or [])
            )
            use_v2 = settings.multiagent_v2_enabled or has_contract_upload
            # 创建失败则降级到下方 Router 单 Agent 链路；执行中失败由编排器 L1/L2/L3 兜底。
            if use_v2 or settings.supervisor_enabled:
                yield sse_event("progress", {"stage": "plan", "message": "正在规划法律任务并选择合适的处理流程"})
                orchestrator = None
                try:
                    sv_embedding = await _load_user_embedding(db, current_user.id, agent_manager.embedding)
                    sv_reranker = await _load_user_reranker(db, current_user.id)
                    if use_v2:
                        orchestrator = _build_v2_pipeline(
                            agent_manager,
                            llm=user_llm,
                            db=db,
                            embedding=sv_embedding,
                            reranker=sv_reranker,
                        )
                    else:
                        # 局部导入避免模块级循环依赖（与 _build_v2_pipeline 一致）。
                        from agent_service.orchestrator import QueryRewriteLayer

                        orchestrator = agent_manager.create_supervisor(
                            llm=user_llm,
                            db=db,
                            embedding=sv_embedding,
                            reranker=sv_reranker,
                            query_rewriter=QueryRewriteLayer(user_llm),
                        )
                except Exception as exc:
                    logger.warning("多 Agent 编排器创建失败，降级单 Agent: %s", exc.__class__.__name__)

                if orchestrator is not None:
                    yield sse_event("progress", {"stage": "execute", "message": "处理流程已确定，正在调用专业 Agent"})
                    logger.info(
                        "[AgentRoute] 启用多 Agent 编排分支 v2=%s",
                        use_v2,
                    )
                    conversation = await _ensure_conversation(
                        db,
                        current_user=current_user,
                        conversation_id=body.conversation_id,
                        query=body.query,
                        agent_type="multiagent_v2" if use_v2 else "supervisor",
                        kb_ids=body.kb_ids,
                    )
                    conversation_id = str(conversation.id)

                    # 两层短期记忆：Redis 结构化案件事实 + MySQL 最近消息窗口。
                    history_summary, legal_memory = await _load_short_term_context(
                        db,
                        memory=agent_manager.memory,
                        conversation_id=conversation_id,
                        user_id=current_user.id,
                        current_query=body.query,
                    )
                    uploaded_files = list(body.uploaded_files) if body.uploaded_files else []
                    if not uploaded_files and agent_manager.memory is not None:
                        uploaded_files = await agent_manager.memory.load_files(conversation_id)

                    # ===== 会话上传合同解析：把 uploaded_files 中的合同解析为条款，注入 v2 plan_slots =====
                    uploaded_contracts: list[dict[str, Any]] = []
                    if use_v2 and uploaded_files:
                        uploaded_contracts = await _resolve_uploaded_contracts(db, current_user.id, uploaded_files)

                    risk_level = "high" if _is_high_risk(body.query) else "low"
                    shared_state: SharedState = {
                        "query": body.query,
                        "conversation_id": conversation_id,
                        "trace_id": run_trace_id,
                        "experiment_variant": experiment_variant,
                        "user_id": str(current_user.id),
                        "tenant_id": str(current_user.id),
                        "kb_ids": available_kbs,
                        "risk_level": risk_level,
                        "max_rounds": settings.supervisor_max_rounds,
                        "legal_memory": legal_memory,
                        "history_summary": history_summary or "",
                        "uploaded_files": uploaded_files,
                        "available_kbs": available_kbs,
                        "document_id": body.document_id or "",
                        "review_dimensions": body.review_dimensions or [],
                    }
                    if uploaded_contracts:
                        shared_state["plan_slots"] = {"clauses": _parse_contract_clauses(uploaded_contracts[0])}
                        shared_state["uploaded_contracts"] = uploaded_contracts
                        shared_state["entry_hint"] = "contract_review_upload"
                        # 持久化文件引用到会话记忆，后续轮次可复用（load_files）。
                        if agent_manager.memory is not None:
                            file_refs = [
                                {
                                    "upload_id": contract["upload_id"],
                                    "filename": contract["filename"],
                                    "file_type": contract["file_type"],
                                    "doc_type": contract["doc_type"],
                                }
                                for contract in uploaded_contracts
                            ]
                            await agent_manager.memory.save_files(conversation_id, file_refs)
                    await _save_message(db, conversation.id, current_user.id, "user", body.query)

                    if use_v2:
                        async for event in orchestrator.run(shared_state):
                            yield event
                    else:
                        async for event in orchestrator.astream(shared_state):
                            yield event

                    # 写回会话记忆（修复 doc 19 D4：编排分支不写记忆）
                    if shared_state.get("legal_memory") is not None and agent_manager.memory is not None:
                        await agent_manager.memory.update(conversation_id, shared_state["legal_memory"])

                    # 合同分析结果回写上传记录，供审查报告导出
                    if use_v2 and uploaded_contracts:
                        await _persist_contract_analysis(db, current_user.id, uploaded_contracts, shared_state)

                    sv_message = await _save_message(
                        db,
                        conversation.id,
                        current_user.id,
                        "assistant",
                        shared_state.get("final_answer") or "",
                        citations={"items": shared_state.get("final_citations") or []},
                        latency_ms=int((perf_counter() - started) * 1000),
                        retrieval_trace_id=shared_state.get("trace_id") or None,
                    )
                    await _persist_short_term_context(
                        memory=agent_manager.memory,
                        conversation_id=conversation_id,
                        previous_summary=history_summary,
                        legal_memory=legal_memory,
                        query=body.query,
                        answer=shared_state.get("final_answer") or "",
                        llm=user_llm,
                    )
                    await _refresh_conversation_stats(db, conversation)
                    done_payload: dict[str, Any] = {
                        "conversation_id": conversation_id,
                        "message_id": str(sv_message.id),
                        "trace_id": shared_state.get("trace_id") or "",
                        "exportable_document": is_document_generation_query(body.query),
                    }
                    if uploaded_contracts:
                        done_payload["upload_ids"] = [contract["upload_id"] for contract in uploaded_contracts]
                    outcome.update(
                        {
                            "status": "success",
                            "engine": "pipeline_v2" if use_v2 else "supervisor",
                            "intent": shared_state.get("entry_hint") or "",
                            "answer": shared_state.get("final_answer") or "",
                            "conversation_id": conversation_id,
                        }
                    )
                    yield sse_event("done", done_payload)
                    return

            # ===== 兜底分支：Router → 单 Agent（现有逻辑，保持不动）=====
            logger.info("[AgentRoute] 进入 Router 单 Agent 分支，开始路由决策")
            yield sse_event("progress", {"stage": "route", "message": "正在识别问题类型与所需法律依据"})
            single_history, single_memory = await _load_short_term_context(
                db,
                memory=agent_manager.memory,
                conversation_id=body.conversation_id,
                user_id=current_user.id,
                current_query=body.query,
            )
            router_input = RouterInput(
                user_query=body.query,
                conversation_id=body.conversation_id,
                user_id=str(current_user.id),
                tenant_id=str(current_user.id),
                history_summary=single_history or None,
                legal_memory=single_memory,
                available_kbs=available_kbs,
            )
            decision = await router_agent.route(router_input, llm=user_llm)
            logger.info(
                "[AgentRoute] Router 决策完成 agent=%s confidence=%s need_retrieval=%s risk_level=%s fallback=%s reason=%s",
                decision.agent,
                decision.confidence,
                decision.need_retrieval,
                decision.risk_level,
                decision.fallback,
                decision.route_reason,
            )
            yield sse_event("router", decision.model_dump(mode="json"))

            conversation = await _ensure_conversation(
                db,
                current_user=current_user,
                conversation_id=body.conversation_id,
                query=body.query,
                agent_type=decision.agent,
                kb_ids=body.kb_ids,
            )
            await _save_message(db, conversation.id, current_user.id, "user", body.query)
            state = build_initial_state(
                decision,
                router_input.model_copy(update={"conversation_id": str(conversation.id)}),
            )
            state["trace_id"] = run_trace_id
            embedding = await _load_user_embedding(db, current_user.id, agent_manager.embedding)
            reranker = await _load_user_reranker(db, current_user.id)
            logger.info("[AgentRoute] 分配业务 Agent: %s", decision.agent)
            yield sse_event("progress", {"stage": "execute", "message": "已选择专业 Agent，正在检索并组织答复"})
            agent = agent_manager.create_agent(decision.agent, llm=user_llm, db=db, embedding=embedding, reranker=reranker)

            # 单 Agent 分支：记录本次 Agent 调用（工具记录由 tool_exec_node 自动归入）。
            single_agent_idx = execution_tracer.begin_agent(
                decision.agent,
                round_num=1,
                input_summary=body.query,
            )
            try:
                async for event in agent.astream(state):
                    yield event
            finally:
                execution_tracer.end_agent(
                    single_agent_idx,
                    status="success",
                    output_summary=state.get("answer") or "",
                    chunks_count=len(state.get("retrieved_chunks") or []),
                    citations_count=len(state.get("citations") or []),
                )

            message = await _save_message(
                db,
                conversation.id,
                current_user.id,
                "assistant",
                state.get("answer") or "",
                citations={"items": state.get("citations") or []},
                latency_ms=int((perf_counter() - started) * 1000),
                retrieval_trace_id=state.get("trace_id") or None,
            )
            await _persist_short_term_context(
                memory=agent_manager.memory,
                conversation_id=str(conversation.id),
                previous_summary=single_history,
                legal_memory=single_memory,
                query=body.query,
                answer=state.get("answer") or "",
                llm=user_llm,
            )
            await _refresh_conversation_stats(db, conversation)
            if state.get("legal_memory") is not None:
                await agent_manager.memory.update(str(conversation.id), state["legal_memory"])
            outcome.update(
                {
                    "status": "success",
                    "engine": "single_agent",
                    "intent": decision.agent,
                    "answer": state.get("answer") or "",
                    "conversation_id": str(conversation.id),
                }
            )
            yield sse_event(
                "done",
                {
                    "conversation_id": str(conversation.id),
                    "message_id": str(message.id),
                    "trace_id": state.get("trace_id") or "",
                    "exportable_document": is_document_generation_query(body.query),
                },
            )
        except Exception as exc:  # noqa: BLE001
            # StreamingResponse 已建立连接后再抛异常，浏览器只能看到连接突然断开。
            # 将错误转为明确 SSE 事件，让前端保留助手卡片并展示可重试信息。
            outcome["error"] = f"{exc.__class__.__name__}: {exc}"
            logger.exception("[AgentRoute] 对话流执行失败 trace_id=%s", run_trace_id)
            yield sse_event(
                "error",
                {
                    "message": "生成过程中发生错误，请稍后重试；如持续失败，请在运营监控中查看本次链路。",
                    "trace_id": run_trace_id,
                    "error_type": exc.__class__.__name__,
                },
            )
        finally:
            reset_tool_context(tool_ctx_token)
            # 提问级执行链路：冲刷 Agent/工具执行记录到 question_trace（best-effort，覆盖全分支）
            await flush_execution_trace(
                execution_tracer,
                trace_id=run_trace_id,
                user_id=current_user.id,
                conversation_id=outcome["conversation_id"],
                query=body.query,
                intent=outcome["intent"],
                engine=outcome["engine"],
                status=outcome["status"],
                answer_snippet=outcome["answer"],
                error=outcome["error"],
            )
            reset_execution_tracer(tracer_token)
            # Harness 治理收尾：冲刷 LLM 用量到 llm_usage（best-effort，覆盖 v2/supervisor/单 Agent 全分支）
            await flush_usage(
                usage_collector,
                trace_id=run_trace_id,
                user_id=current_user.id,
                message_id=None,
                db=None,
            )
            reset_usage_collector(usage_token)
            # 恢复 A/B 实验的 prompt 版本覆盖
            if prompt_version_token is not None:
                reset_prompt_versions(prompt_version_token)
            # 释放 Input Guard 占用的并发槽位（与 run_input_guard 成对）
            await release_concurrency(current_user.id)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/contract/review")
async def review_contract(
    body: ContractReviewRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    agent_manager: AgentManagerDep,
    user_llm: LLMDep,
) -> StreamingResponse:
    """合同审查独立 SSE 入口，使用 contract_review Agent 生成审查报告。"""
    # Input Guard：与 chat 入口一致的安全/预算闸门。
    await run_input_guard(query=body.contract_type or "", kb_ids=body.kb_ids, user_id=current_user.id, db=db)

    async def event_stream():
        started = perf_counter()
        # Harness 治理：本次请求生成 run 级 trace_id 并绑定 LLM 用量收集器（doc 21），
        # agent_run_trace / llm_usage / evaluation_result 均用该 id 关联。
        run_trace_id = uuid4().hex
        usage_collector = UsageCollector()
        usage_token = set_usage_collector(usage_collector)
        # 提问级执行链路（doc 21 扩展）：绑定 ExecutionTracer，采集本提问调度了哪些 Agent、调用了哪些工具。
        execution_tracer = ExecutionTracer()
        tracer_token = set_execution_tracer(execution_tracer)
        # 本次提问的执行结果快照：各分支在 return 前写入，finally 统一冲刷到 question_trace。
        outcome: dict[str, Any] = {
            "status": "failed",
            "engine": "",
            "intent": "",
            "answer": "",
            "error": "",
            "conversation_id": None,
        }
        # A/B 实验：按 user_id 分流 prompt 版本（doc 21 Phase 3）；未启用时返回 ("none", None)
        experiment_variant, prompt_version_token = apply_experiment(current_user.id)
        # 设置请求级 ToolContext, 让 WebSearchTool 等单例工具能读取当前用户的 BYOK 配置。
        tool_ctx_token = set_tool_context(ToolContext(user_id=current_user.id, db=db))
        try:
            available_kbs = await _load_user_kbs(db, current_user.id, body.kb_ids)
            query = body.contract_type or f"审查合同文档 {body.document_id}"
            conversation = await _ensure_conversation(
                db,
                current_user=current_user,
                conversation_id=body.conversation_id,
                query=query,
                agent_type="contract_review",
                kb_ids=body.kb_ids,
            )

            # ===== v2 编排：合同审查走预置工作流（clause→rule→rag→report）=====
            if settings.multiagent_v2_enabled:
                pipeline = _build_v2_pipeline(
                    agent_manager,
                    llm=user_llm,
                    db=db,
                    embedding=await _load_user_embedding(db, current_user.id, agent_manager.embedding),
                    reranker=await _load_user_reranker(db, current_user.id),
                )
                shared_state: SharedState = {
                    "query": query,
                    "conversation_id": str(conversation.id),
                    "trace_id": run_trace_id,
                    "experiment_variant": experiment_variant,
                    "user_id": str(current_user.id),
                    "tenant_id": str(current_user.id),
                    "kb_ids": available_kbs,
                    "available_kbs": available_kbs,
                    "entry_hint": "contract_review",
                    "risk_level": "medium",
                    "max_rounds": settings.supervisor_max_rounds,
                    "document_id": body.document_id,
                    "review_dimensions": body.review_dimensions,
                    "legal_memory": None,
                    "history_summary": "",
                    "uploaded_files": [],
                }
                await _save_message(db, conversation.id, current_user.id, "user", query)
                async for event in pipeline.run(shared_state):
                    yield event
                message = await _save_message(
                    db,
                    conversation.id,
                    current_user.id,
                    "assistant",
                    shared_state.get("final_answer") or "",
                    citations={"items": shared_state.get("final_citations") or []},
                    latency_ms=int((perf_counter() - started) * 1000),
                    retrieval_trace_id=shared_state.get("trace_id") or None,
                )
                await _refresh_conversation_stats(db, conversation)
                outcome.update(
                    {
                        "status": "success",
                        "engine": "pipeline_v2",
                        "intent": "contract_review",
                        "answer": shared_state.get("final_answer") or "",
                        "conversation_id": str(conversation.id),
                    }
                )
                yield sse_event(
                    "done",
                    {
                        "conversation_id": str(conversation.id),
                        "message_id": str(message.id),
                        "trace_id": shared_state.get("trace_id") or "",
                    },
                )
                return

            decision = RouterDecision(
                task_type="contract_review",
                agent="contract_review",
                confidence=0.95,
                need_retrieval=True,
                need_file=True,
                execution_mode="document_analysis",
                risk_level="medium",
                route_reason="合同审查专用入口",
            )
            router_input = RouterInput(
                user_query=query,
                conversation_id=str(conversation.id),
                user_id=str(current_user.id),
                tenant_id=str(current_user.id),
                available_kbs=available_kbs,
            )
            yield sse_event("router", decision.model_dump(mode="json"))
            await _save_message(db, conversation.id, current_user.id, "user", query)
            state = build_initial_state(decision, router_input)
            state["trace_id"] = run_trace_id
            state["document_id"] = body.document_id
            state["review_dimensions"] = body.review_dimensions
            embedding = await _load_user_embedding(db, current_user.id, agent_manager.embedding)
            reranker = await _load_user_reranker(db, current_user.id)
            agent = agent_manager.create_agent("contract_review", llm=user_llm, db=db, embedding=embedding, reranker=reranker)

            # 单 Agent 分支：记录本次 Agent 调用（工具记录由 tool_exec_node 自动归入）。
            single_agent_idx = execution_tracer.begin_agent(
                "contract_review",
                round_num=1,
                input_summary=query,
            )
            try:
                async for event in agent.astream(state):
                    yield event
            finally:
                execution_tracer.end_agent(
                    single_agent_idx,
                    status="success",
                    output_summary=state.get("answer") or "",
                    chunks_count=len(state.get("retrieved_chunks") or []),
                    citations_count=len(state.get("citations") or []),
                )

            message = await _save_message(
                db,
                conversation.id,
                current_user.id,
                "assistant",
                state.get("answer") or "",
                citations={"items": state.get("citations") or []},
                latency_ms=int((perf_counter() - started) * 1000),
                retrieval_trace_id=state.get("trace_id") or None,
            )
            await _refresh_conversation_stats(db, conversation)
            outcome.update(
                {
                    "status": "success",
                    "engine": "single_agent",
                    "intent": "contract_review",
                    "answer": state.get("answer") or "",
                    "conversation_id": str(conversation.id),
                }
            )
            yield sse_event(
                "done",
                {
                    "conversation_id": str(conversation.id),
                    "message_id": str(message.id),
                    "trace_id": state.get("trace_id") or "",
                },
            )
        finally:
            reset_tool_context(tool_ctx_token)
            # 提问级执行链路：冲刷 Agent/工具执行记录到 question_trace（best-effort，覆盖全分支）
            await flush_execution_trace(
                execution_tracer,
                trace_id=run_trace_id,
                user_id=current_user.id,
                conversation_id=outcome["conversation_id"],
                query=query,
                intent=outcome["intent"],
                engine=outcome["engine"],
                status=outcome["status"],
                answer_snippet=outcome["answer"],
                error=outcome["error"],
            )
            reset_execution_tracer(tracer_token)
            # Harness 治理收尾：冲刷 LLM 用量到 llm_usage（best-effort，覆盖 v2/supervisor/单 Agent 全分支）
            await flush_usage(
                usage_collector,
                trace_id=run_trace_id,
                user_id=current_user.id,
                message_id=None,
                db=None,
            )
            reset_usage_collector(usage_token)
            # 恢复 A/B 实验的 prompt 版本覆盖
            if prompt_version_token is not None:
                reset_prompt_versions(prompt_version_token)
            # 释放 Input Guard 占用的并发槽位（与 run_input_guard 成对）
            await release_concurrency(current_user.id)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


async def _load_short_term_context(
    db: AsyncSession,
    *,
    memory: Any,
    conversation_id: str,
    user_id: int,
    current_query: str,
) -> tuple[str, dict[str, Any]]:
    """恢复最近会话与结构化案件事实，并让当前轮事实覆盖旧值。"""
    history_summary = ""
    legal_memory: Any = None
    if memory is not None and conversation_id:
        history_summary = await memory.load_summary(conversation_id) or ""
        legal_memory = await memory.load(conversation_id)
    if not history_summary:
        history_summary = await load_recent_history(
            db,
            conversation_id,
            user_id,
            max_turns=settings.agent_memory_max_turns,
            max_tokens=settings.agent_memory_recent_tokens,
        )
    enriched = enrich_legal_memory(
        legal_memory,
        history_summary=history_summary,
        current_query=current_query,
    )
    return history_summary, enriched


async def _persist_short_term_context(
    *,
    memory: Any,
    conversation_id: str,
    previous_summary: str,
    legal_memory: dict[str, Any],
    query: str,
    answer: str,
    llm: Any,
) -> None:
    """把本轮消息和最新事实写回 Redis；失败不阻断主回答。"""
    if memory is None or not conversation_id:
        return
    summary = await compress_history_with_llm(
        previous_summary,
        query=query,
        answer=answer,
        llm=llm,
        max_tokens=settings.agent_memory_max_tokens,
        timeout=settings.llm_timeout,
        trigger_tokens=settings.agent_memory_summary_trigger_tokens,
        summary_tokens=settings.agent_memory_summary_tokens,
        recent_tokens=settings.agent_memory_recent_tokens,
    )
    enriched = enrich_legal_memory(
        legal_memory,
        history_summary=summary,
        current_query=query,
    )
    await memory.update(conversation_id, enriched)
    await memory.update_summary(conversation_id, summary)


async def _load_user_kbs(
    db: AsyncSession,
    user_id: int,
    requested_ids: list[str],
) -> list[dict[str, Any]]:
    """加载当前用户可用知识库，Router 只接收描述信息而不绑定具体 kb_id。"""
    statement = select(KnowledgeBase).where(KnowledgeBase.user_id == user_id)
    result = await db.execute(statement)
    kbs = list(result.scalars().all())
    if requested_ids:
        requested = {str(item) for item in requested_ids}
        kbs = [kb for kb in kbs if str(kb.id) in requested or kb.name in requested]
    return [
        {
            "kb_id": str(kb.id),
            "name": kb.name,
            "type": kb.kb_type,
            "domain": kb.kb_type,
        }
        for kb in kbs
        if kb.status == "enabled"
    ]


async def _ensure_conversation(
    db: AsyncSession,
    *,
    current_user: User,
    conversation_id: str,
    query: str,
    agent_type: str,
    kb_ids: list[str],
) -> Conversation:
    """读取或创建会话，确保会话归属当前用户。"""
    if conversation_id:
        if not conversation_id.isdigit():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="conversation_id 必须为数字字符串")
        result = await db.execute(
            select(Conversation).where(
                Conversation.id == int(conversation_id),
                Conversation.user_id == current_user.id,
                Conversation.status == "active",
            )
        )
        conversation = result.scalar_one_or_none()
        if conversation is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
        conversation.agent_type = agent_type
        return conversation

    conversation = Conversation(
        user_id=current_user.id,
        kb_id=_first_numeric_kb_id(kb_ids),
        title=_conversation_title(query),
        agent_type=agent_type,
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def _save_message(
    db: AsyncSession,
    conversation_id: int,
    user_id: int | None,
    role: str,
    content: str,
    *,
    citations: dict[str, Any] | None = None,
    latency_ms: int = 0,
    retrieval_trace_id: str | None = None,
) -> Message:
    """保存一条会话消息，assistant 消息可携带引用和 trace。"""
    message = Message(
        conversation_id=conversation_id,
        user_id=user_id,
        role=role,
        content=content,
        citations=citations,
        latency_ms=latency_ms,
        retrieval_trace_id=retrieval_trace_id,
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return message


async def _refresh_conversation_stats(db: AsyncSession, conversation: Conversation) -> None:
    """更新会话消息计数；摘要压缩留给后续记忆模块增强。"""
    conversation.message_count = int(conversation.message_count or 0) + 2
    await db.commit()


def _conversation_title(query: str) -> str:
    """根据首问生成简短会话标题。"""
    normalized = " ".join(query.split())
    return normalized[:40] or "新的对话"


def _first_numeric_kb_id(kb_ids: list[str]) -> int | None:
    """从请求 kb_ids 中取第一个数字 ID，兼容按名称传库的场景。"""
    for item in kb_ids:
        if str(item).isdigit():
            return int(item)
    return None


async def _load_user_embedding(db: AsyncSession, user_id: int, fallback):
    """按当前用户动态配置创建 Embedding，未配置时复用应用级兜底实例。"""
    runtime = await resolve_runtime_config(db, user_id, "embedding")
    if runtime is None:
        return fallback
    return EmbeddingFactory.create(
        runtime.provider,
        runtime.model_name,
        runtime.api_base or None,
        runtime.api_key or None,
        dimension=runtime.dimension,
    )


async def _load_user_reranker(db: AsyncSession, user_id: int) -> ConfigurableLegalReranker:
    """按当前用户动态配置创建 Rerank，未配置时使用规则重排。"""
    runtime = await resolve_runtime_config(db, user_id, "rerank")
    if runtime is None:
        return ConfigurableLegalReranker()
    return ConfigurableLegalReranker(
        provider=runtime.provider,
        model_name=runtime.model_name,
        api_base=runtime.api_base,
        api_key=runtime.api_key,
        timeout=runtime.timeout or 30,
    )


async def _resolve_uploaded_contracts(
    db: AsyncSession,
    user_id: int,
    uploaded_files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """按 upload_id 加载会话上传的合同记录，过滤解析完成且属于当前用户的。"""
    from backend.services import chat_upload as chat_upload_service

    contracts: list[dict[str, Any]] = []
    for item in uploaded_files:
        upload_id = item.get("upload_id") or item.get("file_id")
        if not upload_id or not str(upload_id).isdigit():
            continue
        try:
            record = await chat_upload_service.get_upload(db, int(upload_id), user_id)
        except HTTPException:
            continue
        if record.parse_status != "completed" or not record.raw_markdown:
            continue
        contracts.append(
            {
                "upload_id": str(record.id),
                "filename": record.filename,
                "file_type": record.file_type,
                "doc_type": record.doc_type or "contract",
                "markdown": record.raw_markdown,
            }
        )
    return contracts


def _parse_contract_clauses(contract: dict[str, Any]) -> list[dict[str, Any]]:
    """把上传合同 Markdown 解析为 ClauseAgent.retrieve_node 同构的条款 dict 列表。"""
    from backend.services.contract_parser import ContractParser

    parsed = ContractParser().parse(contract["markdown"], contract["filename"])
    clauses: list[dict[str, Any]] = []
    for index, clause in enumerate(parsed.clauses):
        clauses.append(
            {
                "chunk_id": f"upload:{contract['upload_id']}:{index}",
                "text": clause.content,
                "article_no": clause.article_no,
                "title": clause.title,
                "clause_type": clause.clause_type,
                "chunk_level": clause.chunk_level,
                "entities": clause.entities,
            }
        )
    return clauses


async def _persist_contract_analysis(
    db: AsyncSession,
    user_id: int,
    uploaded_contracts: list[dict[str, Any]],
    shared_state: dict[str, Any],
) -> None:
    """把合同分析最终结果（报告/摘要/要素/风险）写回 chat_upload 记录，供报告导出。"""
    from agent_service.orchestrator.pipeline import extract_contract_payload
    from backend.services import chat_upload as chat_upload_service

    payload = extract_contract_payload(shared_state.get("plan_slots") or {})
    for contract in uploaded_contracts:
        record = await chat_upload_service.get_upload(db, int(contract["upload_id"]), user_id)
        await chat_upload_service.mark_analysis_result(
            db,
            record,
            report=shared_state.get("final_answer") or "",
            summary=payload.get("summary") or "",
            elements=payload.get("elements") or {},
            risks=payload.get("risks") or [],
        )


def _build_v2_pipeline(
    agent_manager: Any,
    *,
    llm: Any,
    db: AsyncSession,
    embedding: Any | None = None,
    reranker: Any | None = None,
):
    """构建 v2 多 Agent 编排五层组件（doc 19 架构总览）。

    意图→规划→执行→审查→合成，全部复用现有 Agent / 检索 / 引用链路。
    Reviewer 的 L2 抽查暂用主 LLM，后续按 §5.5 模型分层换成不同 provider 避免自评偏见。
    """
    from agent_service.orchestrator import (
        IntentLayer,
        MultiAgentPipeline,
        PlanExecutor,
        Planner,
        QueryRewriteLayer,
        Reviewer,
        Synthesizer,
    )

    query_rewrite_layer = QueryRewriteLayer(llm)
    intent_layer = IntentLayer(llm)
    planner = Planner(llm)
    executor = PlanExecutor(
        agent_manager,
        llm=llm,
        db=db,
        embedding=embedding,
        reranker=reranker,
    )
    reviewer = Reviewer(agent_manager.citation_validator, llm)
    synthesizer = Synthesizer(llm)
    return MultiAgentPipeline(
        query_rewrite_layer=query_rewrite_layer,
        intent_layer=intent_layer,
        planner=planner,
        executor=executor,
        reviewer=reviewer,
        synthesizer=synthesizer,
    )
