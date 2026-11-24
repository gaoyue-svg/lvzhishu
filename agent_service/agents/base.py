"""本文件实现业务 Agent 的共享 LangGraph 骨架、检索编排和 SSE 输出。"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from time import perf_counter
from typing import Any
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from agent_service.citation import CitationValidator
from agent_service.harness.execution_trace import get_current_tracer
from agent_service.llm import BaseLLM
from agent_service.llm.usage import usage_purpose
from agent_service.prompts import format_prompt, get_prompt
from agent_service.tools import ToolRegistry
from backend.config import settings
from backend.utils.logger import get_logger
from rag_service.retrieval.citation import build_citations
from rag_service.retrieval.context_builder import ContextBuilder
from rag_service.retrieval.retriever import HybridRetriever

from .state import AgentResult, LegalAgentState, SharedState

logger = get_logger(__name__)


class BaseAgent:
    """所有业务 Agent 的基类，封装 Intent/Retrieve/Reason/Citation/Validate 闭环。"""

    agent_key = "law_qa"
    agent_name = "法律咨询"
    default_top_k = 15
    default_rerank_top_k = 8
    answer_temperature = 0.3

    def __init__(
        self,
        llm: BaseLLM,
        retriever: HybridRetriever,
        context_builder: ContextBuilder,
        tool_registry: ToolRegistry,
        memory: Any,
        citation_validator: CitationValidator,
        db: Any | None = None,
    ) -> None:
        """保存运行时依赖；LLM 和 DB 都按当前请求注入，避免跨用户串用。"""
        self.llm = llm
        self.retriever = retriever
        self.context_builder = context_builder
        self.tool_registry = tool_registry
        self.memory = memory
        self.citation_validator = citation_validator
        self.db = db
        self.graph = self.build_graph()

    def build_graph(self):
        """构建 LangGraph 状态图，供非流式调用或后续 checkpoint 扩展复用。"""
        graph = StateGraph(LegalAgentState)
        graph.add_node("intent", self.intent_node)
        graph.add_node("retrieve", self.retrieve_node)
        graph.add_node("retrieve_judge", self.retrieve_judge_node)
        graph.add_node("tool_decide", self.tool_decide_node)
        graph.add_node("tool_exec", self.tool_exec_node)
        graph.add_node("reason", self.reason_node)
        graph.add_node("citation", self.citation_node)
        graph.add_node("validate", self.validate_node)
        graph.add_edge(START, "intent")
        graph.add_edge("intent", "retrieve")
        graph.add_edge("retrieve", "retrieve_judge")
        graph.add_conditional_edges(
            "retrieve_judge",
            self._retrieve_quality_router,
            {"retry": "retrieve", "proceed": "tool_decide"},
        )
        graph.add_edge("tool_decide", "tool_exec")
        graph.add_edge("tool_exec", "reason")
        graph.add_edge("reason", "citation")
        graph.add_edge("citation", "validate")
        graph.add_conditional_edges(
            "validate",
            self._validation_router,
            {"retry": "reason", "end": END},
        )
        return graph.compile()

    async def ainvoke(self, state: LegalAgentState) -> LegalAgentState:
        """执行 LangGraph 非流式闭环，主要用于测试和后台任务。"""
        result = await self.graph.ainvoke(state)
        return LegalAgentState(**result)

    async def astream(self, state: LegalAgentState) -> AsyncIterator[str]:
        """按业务节点顺序流式执行，并输出 text/event-stream 格式事件。"""
        yield sse_event("node_start", {"node": "intent", "agent": self.agent_key})
        state.update(await self.intent_node(state))
        yield sse_event("node_end", {"node": "intent"})

        while True:
            yield sse_event("node_start", {"node": "retrieve"})
            state.update(await self.retrieve_node(state))
            yield sse_event(
                "node_end",
                {
                    "node": "retrieve",
                    "quality": state.get("retrieval_quality"),
                    "chunk_count": len(state.get("retrieved_chunks") or []),
                },
            )
            state.update(await self.retrieve_judge_node(state))
            if self._retrieve_quality_router(state) != "retry":
                break

        yield sse_event("node_start", {"node": "tool_decide"})
        state.update(await self.tool_decide_node(state))
        yield sse_event("node_end", {"node": "tool_decide"})

        yield sse_event("node_start", {"node": "tool_exec"})
        state.update(await self.tool_exec_node(state))
        yield sse_event("node_end", {"node": "tool_exec", "tool_count": len(state.get("tool_calls") or [])})

        while True:
            yield sse_event("node_start", {"node": "reason"})
            async for piece in self.reason_stream(state):
                yield sse_event("token", {"content": piece})
            yield sse_event("node_end", {"node": "reason"})

            yield sse_event("node_start", {"node": "citation"})
            state.update(await self.citation_node(state))
            yield sse_event("citation", {"citations": state.get("citations") or []})

            yield sse_event("node_start", {"node": "validate"})
            state.update(await self.validate_node(state))
            yield sse_event("node_end", {"node": "validate", **(state.get("citation_validation") or {})})
            if self._validation_router(state) != "retry":
                break

        yield sse_event("final", self.final_payload(state))

    async def invoke_for_supervisor(
        self,
        input: str,
        shared_state: SharedState,
        *,
        overrides: dict[str, Any] | None = None,
    ) -> AgentResult:
        """被 Supervisor / v2 执行器调用时执行单次完整流程，返回结构化产出。

        与 astream 的区别：
        - 输入是编排器给的子任务 input，不是原 query
        - 返回 AgentResult，不直接 SSE
        - 复用现有 graph（intent→retrieve→...→validate），不重写 Agent 逻辑
        - overrides 用于 slot 驱动注入：v2 执行器把上游产出（document_id/条款/风险）写进子状态，
          修复 doc 19 D2 合同多阶段子 Agent 数据断链问题
        """
        sub_state = self._build_sub_state(input, shared_state, overrides=overrides)
        # 提问级执行链路（doc 21 扩展）：begin_agent 绑定当前 task 的 Agent，
        # 使 tool_exec_node 记录的工具能归入本 Agent；finally 里固化结果（含取消/异常）。
        tracer = get_current_tracer()
        agent_index = None
        if tracer is not None:
            agent_index = tracer.begin_agent(
                self.agent_key,
                round_num=int(shared_state.get("current_round") or 0),
                input_summary=input,
            )
        result: dict[str, Any] | None = None
        error_hint = ""
        try:
            result = await self.graph.ainvoke(sub_state)
        except Exception as exc:
            logger.warning("Supervisor 调用 Agent 失败: agent=%s error=%s", self.agent_key, exc.__class__.__name__)
            error_hint = exc.__class__.__name__
        finally:
            if tracer is not None and agent_index is not None:
                if result is not None:
                    tracer.end_agent(
                        agent_index,
                        status="success",
                        output_summary=self._summarize_output(result),
                        chunks_count=len(result.get("retrieved_chunks") or []),
                        citations_count=len(result.get("citations") or []),
                    )
                else:
                    tracer.end_agent(agent_index, status="failed", output_summary=f"Agent 执行失败: {error_hint or 'cancel'}")
        if result is None:
            # 失败时返回空产出，避免拖垮整个编排流程
            return AgentResult(
                agent=self.agent_key,
                round=int(shared_state.get("current_round") or 0),
                input=input,
                context_text="",
                chunks=[],
                citations=[],
                answer="",
                trace_id="",
                tool_calls=[],
                output_summary=f"Agent 执行失败: {error_hint}",
            )
        return AgentResult(
            agent=self.agent_key,
            round=int(shared_state.get("current_round") or 0),
            input=input,
            context_text=result.get("context_text") or "",
            chunks=result.get("retrieved_chunks") or [],
            citations=result.get("citations") or [],
            answer=result.get("answer") or "",
            trace_id=result.get("trace_id") or "",
            tool_calls=result.get("tool_calls") or [],
            output_summary=self._summarize_output(result),
        )

    def _build_sub_state(
        self,
        input: str,
        shared_state: SharedState,
        *,
        overrides: dict[str, Any] | None = None,
    ) -> LegalAgentState:
        """把编排器子任务 + 共享状态映射为 Agent 内部 LegalAgentState。

        关键点：
        - query=input，让 Agent 用编排器给的子任务检索，而不是原问题；
        - 显式注入 doc 19 D2/D3 的跨步依赖数据（document_id/legal_context/sub_questions/
          retrieval_scope/time_context），修复法条定位增强检索失效、案例分析多路检索退化、
          合同子 Agent 拿不到 document_id 的问题；
        - overrides 由 v2 执行器按 Plan 数据契约传入，覆盖子状态字段（如 slot 里的上游条款/风险）。
        """
        sub_state: LegalAgentState = LegalAgentState(
            query=input,
            # 保留本轮用户原话。业务 Agent 的检索可以使用 Supervisor 扩写任务，
            # 但专项提示词/子意图必须以用户本轮真实问题为准，不能被历史回答污染。
            original_query=shared_state.get("original_query") or shared_state.get("query") or input,
            conversation_id=shared_state.get("conversation_id") or "",
            user_id=shared_state.get("user_id") or "",
            tenant_id=shared_state.get("tenant_id") or "",
            kb_ids=shared_state.get("kb_ids") or [],
            intent=shared_state.get("entry_hint") or "",
            legal_memory=shared_state.get("legal_memory"),
            history_summary=shared_state.get("history_summary") or "",
            risk_level=shared_state.get("risk_level") or "low",
            document_id=shared_state.get("document_id") or "",
            legal_context=shared_state.get("legal_context"),
            sub_questions=shared_state.get("sub_questions") or [],
            retrieval_scope=shared_state.get("retrieval_scope"),
            time_context=shared_state.get("time_context"),
            review_dimensions=shared_state.get("review_dimensions") or [],
            retrieved_chunks=[],
            citations=[],
            tool_calls=[],
            retry_count=0,
            validation_retry_count=0,
            messages=[],
            trace_id="",
        )
        if overrides:
            sub_state.update(overrides)
        return sub_state

    def _summarize_output(self, result: dict[str, Any]) -> str:
        """生成给 Supervisor 看的产出摘要，避免把完整 context 塞回决策 LLM。"""
        chunks = result.get("retrieved_chunks") or []
        # 提取前 3 条命中的法律名+条号，给 Supervisor 判断"是否已覆盖条文"
        top_laws: list[str] = []
        for chunk in chunks[:5]:
            law_name = chunk.get("law_name") or ""
            article_no = chunk.get("article_no") or ""
            if law_name:
                top_laws.append(f"{law_name}{article_no}".strip())
        answer_len = len(result.get("answer") or "")
        law_hint = "、".join(top_laws) if top_laws else "无"
        return f"检索到 {len(chunks)} 条，答案 {answer_len} 字，关键法条: {law_hint}"

    async def intent_node(self, state: LegalAgentState) -> dict[str, Any]:
        """细化 Router 已识别的意图，不推翻 Router 决策。"""
        return {
            "tool_calls": state.get("tool_calls") or [],
            "retry_count": state.get("retry_count") or 0,
            "validation_retry_count": state.get("validation_retry_count") or 0,
            "risk_alerts": self._build_risk_alerts(state),
        }

    async def retrieve_node(self, state: LegalAgentState) -> dict[str, Any]:
        """调用阶段三 HybridRetriever，Agent 只做参数编排和上下文构建。"""
        kb_ids = self._extract_kb_ids(state)
        query = self._retrieval_query(state)
        retrieval = await self.retriever.retrieve(
            query,
            kb_ids=kb_ids,
            top_k=self.default_top_k,
            rerank_top_k=self.default_rerank_top_k,
        )
        chunks = [hit.to_dict() for hit in retrieval.chunks]
        citations = await build_citations(chunks)
        context_result = await self._build_context(chunks, citations, retrieval.trace)
        trace = dict(retrieval.trace)
        trace["context_text"] = context_result.context_text
        trace["context_token_count"] = context_result.token_count
        trace["citations"] = citations
        trace_id = state.get("trace_id") or uuid4().hex
        return {
            "rewritten_query": (trace.get("rewritten_query") or {}).get("legal_query", query),
            "retrieved_chunks": chunks,
            "citations": citations,
            "context_text": context_result.context_text,
            "retrieval_quality": self._judge_retrieval_quality(context_result.context_text, chunks),
            "trace_id": trace_id,
        }

    async def retrieve_judge_node(self, state: LegalAgentState) -> dict[str, Any]:
        """检索质量不足时只允许补检一次，防止图循环失控。"""
        if state.get("retrieval_quality") == "sufficient":
            return {}
        return {"retry_count": int(state.get("retry_count") or 0) + 1}

    async def tool_decide_node(self, state: LegalAgentState) -> dict[str, Any]:
        """默认不调用工具；子类按业务场景生成 pending_tool_calls。"""
        return {"pending_tool_calls": []}

    async def tool_exec_node(self, state: LegalAgentState) -> dict[str, Any]:
        """执行注册表中的内部 Python 工具，并把工具结果记入状态。

        所有编排路径的工具调用都汇聚于此，是提问级执行链路（doc 21 扩展）
        ExecutionTracer 记录"调用了哪些工具"的唯一入口。
        """
        executed = list(state.get("tool_calls") or [])
        tracer = get_current_tracer()
        for call in state.get("pending_tool_calls") or []:
            name = str(call.get("name") or "")
            args = dict(call.get("args") or {})
            started = perf_counter()
            try:
                result = await self.tool_registry.execute(name, **args)
                # 网页正文体积大，抽离到 state 单独保存，避免撑爆 LLM 提示词(tool_calls)。
                if isinstance(result, dict):
                    full_texts = result.pop("full_texts", None)
                    if full_texts:
                        merged = dict(state.get("full_texts") or {})
                        merged.update(full_texts)
                        state["full_texts"] = merged
                executed.append({"name": name, "args": args, "result": result, "ok": True})
                if tracer is not None:
                    tracer.add_tool(
                        name,
                        input_summary=args,
                        output_summary=result,
                        ok=True,
                        latency_ms=int((perf_counter() - started) * 1000),
                    )
            except Exception as exc:
                logger.warning("Agent 工具执行失败: name=%s error=%s", name, exc.__class__.__name__)
                executed.append({"name": name, "args": args, "error": str(exc), "ok": False})
                if tracer is not None:
                    tracer.add_tool(
                        name,
                        input_summary=args,
                        output_summary=str(exc),
                        ok=False,
                        latency_ms=int((perf_counter() - started) * 1000),
                    )
        return {"tool_calls": executed, "pending_tool_calls": []}

    async def reason_node(self, state: LegalAgentState) -> dict[str, Any]:
        """非流式推理节点，供 LangGraph ainvoke 使用。"""
        answer = await self._chat_answer(state)
        return {"answer": answer}

    async def reason_stream(self, state: LegalAgentState) -> AsyncIterator[str]:
        """流式推理节点，逐段输出答案并同步写回 state['answer']。"""
        messages = self._build_reason_messages(state)
        answer_parts: list[str] = []
        try:
            with usage_purpose("agent"):
                async for piece in self.llm.stream(
                    messages,
                    temperature=self.answer_temperature,
                    max_tokens=settings.llm_max_tokens,
                ):
                    answer_parts.append(piece)
                    state["answer"] = "".join(answer_parts)
                    yield piece
        except Exception as exc:
            logger.warning("LLM 流式生成失败，降级为非流式: %s", exc.__class__.__name__)
            answer = await self._chat_answer(state)
            state["answer"] = answer
            yield answer

    async def citation_node(self, state: LegalAgentState) -> dict[str, Any]:
        """合并检索引用和工具产生的网络引用，保持编号稳定可追溯。"""
        citations = list(state.get("citations") or [])
        seen = {
            (
                item.get("source_type", "law"),
                str(item.get("chunk_id") or ""),
                str(item.get("url") or ""),
                str(item.get("title") or ""),
            )
            for item in citations
        }
        next_id = len(citations) + 1
        full_texts = state.get("full_texts") or {}
        for call in state.get("tool_calls") or []:
            result = dict(call.get("result") or {})
            for item in result.get("citations") or []:
                citation = dict(item)
                citation.setdefault("source_type", "web")
                key = (
                    citation.get("source_type", "law"),
                    str(citation.get("chunk_id") or ""),
                    str(citation.get("url") or ""),
                    str(citation.get("title") or ""),
                )
                if key in seen:
                    continue
                seen.add(key)
                citation.setdefault("index", next_id)
                # 前端弹窗展示的网页全文，来自 tool_exec_node 抽离到 state["full_texts"]。
                if not citation.get("full_text") and citation.get("url"):
                    url_full = full_texts.get(str(citation["url"]))
                    if url_full:
                        citation["full_text"] = url_full
                citations.append(citation)
                next_id += 1
        return {"citations": citations}

    async def validate_node(self, state: LegalAgentState) -> dict[str, Any]:
        """校验回答中的引用编号是否来自检索或工具结果，失败时触发一次重写。"""
        validation = await self.citation_validator.validate(
            answer=state.get("answer") or "",
            citations=state.get("citations") or [],
            db=self.db,
        )
        update: dict[str, Any] = {"citation_validation": validation}
        if not validation["passed"]:
            update["validation_retry_count"] = int(state.get("validation_retry_count") or 0) + 1
        if state.get("risk_level") == "high" or not validation["passed"]:
            update["needs_human_review"] = True
        return update

    def _retrieve_quality_router(self, state: LegalAgentState) -> str:
        """LangGraph 条件边：检索不足时最多补充检索一次。"""
        max_retry = settings.agent_retry_max
        if state.get("retrieval_quality") == "insufficient" and int(state.get("retry_count") or 0) <= max_retry:
            return "retry"
        return "proceed"

    def _validation_router(self, state: LegalAgentState) -> str:
        """LangGraph 条件边：引用校验失败时最多重写一次。"""
        max_retry = settings.agent_retry_max
        validation = state.get("citation_validation") or {}
        if not validation.get("passed", True) and int(state.get("validation_retry_count") or 0) <= max_retry:
            return "retry"
        return "end"

    async def _chat_answer(self, state: LegalAgentState) -> str:
        """调用非流式 LLM 生成答案，供失败降级和测试使用。"""
        with usage_purpose("agent"):
            return await self.llm.chat(
                self._build_reason_messages(state),
                temperature=self.answer_temperature,
                max_tokens=settings.llm_max_tokens,
            )

    async def _build_context(
        self,
        chunks: list[dict[str, Any]],
        citations: list[dict[str, Any]],
        trace: dict[str, Any],
    ):
        """根据检索意图构建 Prompt Context，章节摘要场景允许展开父子 Chunk。"""
        query_intent = trace.get("query_intent") or {}
        if query_intent.get("intent_type") == "chapter_summary" and self.db is not None:
            return await self.context_builder.build_with_parent_expansion(
                chunks,
                self.db,
                max_tokens=settings.context_max_tokens,
            )
        return await self.context_builder.build(
            chunks,
            citations,
            max_tokens=settings.context_max_tokens,
        )

    def _retrieval_query(self, state: LegalAgentState) -> str:
        """生成本轮检索 query；补检时叠加 Router keywords 扩大召回。"""
        query = state.get("query") or ""
        if state.get("retry_count"):
            keywords = (state.get("retrieval_scope") or {}).get("keywords") or []
            if keywords:
                query = f"{query} {' '.join(str(item) for item in keywords)}"
        return query

    def _build_reason_messages(self, state: LegalAgentState) -> list[dict[str, str]]:
        """组装通用法律问答 Prompt，约束 LLM 只能使用给定上下文引用。"""
        context_text = state.get("context_text") or "（未检索到可引用的本地法条上下文）"
        memory = state.get("legal_memory")
        history_summary = state.get("history_summary") or ""
        validation = state.get("citation_validation") or {}
        retry_hint = ""
        if validation.get("reasons"):
            # 引用校验失败时追加修正提示，前导换行由业务层控制
            retry_hint = "\n" + format_prompt("retry_hint", reasons="；".join(validation["reasons"]))
        user_content = format_prompt(
            "base_reason_user",
            query=state.get("query"),
            memory=self._json(memory),
            history_summary=history_summary or "无（首轮对话）",
            context_text=context_text,
            risk_level=state.get("risk_level"),
            tool_calls=self._json(state.get("tool_calls") or []),
            retry_hint=retry_hint,
        )
        return [
            {"role": "system", "content": self.system_prompt()},
            {"role": "user", "content": user_content},
        ]

    def system_prompt(self) -> str:
        """返回当前 Agent 的系统提示词，子类可覆盖输出风格。"""
        return get_prompt("base_agent_system")

    def final_payload(self, state: LegalAgentState) -> dict[str, Any]:
        """生成 SSE final 事件载荷，方便前端一次性落库或展示。"""
        return {
            "answer": state.get("answer") or "",
            "citations": state.get("citations") or [],
            "risk_alerts": state.get("risk_alerts") or [],
            "trace_id": state.get("trace_id") or "",
            "needs_human_review": bool(state.get("needs_human_review")),
            "citation_validation": state.get("citation_validation") or {},
        }

    def _judge_retrieval_quality(self, context_text: str, chunks: list[dict[str, Any]]) -> str:
        """用可解释的轻量规则判断检索是否足够进入推理。

        修复 doc 19 低危项"非空即 sufficient 形同虚设"：至少要求存在一条
        有正文、有引用的命中，否则判定 insufficient 触发一次补检。
        子类（Rule/RiskReport）按业务覆盖此方法。
        """
        if not context_text.strip() or not chunks:
            return "insufficient"
        usable = [c for c in chunks if str(c.get("text") or "").strip()]
        if not usable:
            return "insufficient"
        return "sufficient"

    def _build_risk_alerts(self, state: LegalAgentState) -> list[dict[str, Any]]:
        """把 Router 风险等级转换为前端可展示的风险提醒。"""
        if state.get("risk_level") != "high":
            return []
        return [{"level": "high", "message": "该问题风险较高，建议人工复核后再使用结论。"}]

    @staticmethod
    def _extract_kb_ids(state: LegalAgentState) -> list[str]:
        """从 Router 注入的知识库描述中提取真实 kb_id。"""
        ids: list[str] = []
        for item in state.get("kb_ids") or []:
            if isinstance(item, dict) and item.get("kb_id"):
                ids.append(str(item["kb_id"]))
            elif item:
                ids.append(str(item))
        return list(dict.fromkeys(ids))

    @staticmethod
    def _json(value: Any) -> str:
        """把复杂状态压缩为中文 Prompt 中可读的 JSON。"""
        try:
            if hasattr(value, "model_dump"):
                value = value.model_dump(mode="json")
            return json.dumps(value, ensure_ascii=False)
        except TypeError:
            return str(value)


def sse_event(event: str, data: dict[str, Any]) -> str:
    """把事件名和 JSON 载荷编码为标准 SSE 文本帧。"""
    payload = json.dumps({"event": event, **data}, ensure_ascii=False, default=str)
    return f"data: {payload}\n\n"


def cited_numbers(answer: str) -> set[int]:
    """提取回答中出现的 [1] 这类引用编号。"""
    return {int(item) for item in re.findall(r"\[(\d+)\]", answer or "")}
