"""本文件实现 Supervisor 多 Agent 编排器，基于规则候选+LLM 决策动态调度 Agent。

P1+P2 阶段仅接入 law_qa 和 article_locate 两个 Agent，支持协同检索。
Supervisor 不可用时由 /chat 入口降级到现有 Router 单 Agent 链路。
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from typing import Any, Literal

from pydantic import BaseModel, model_validator

from agent_service.agents.base import sse_event
from agent_service.agents.citation_merge import merge_citations, renumber_answer_text
from agent_service.agents.registry import get_registry
from agent_service.agents.state import SharedState
from agent_service.llm import BaseLLM
from agent_service.prompts import build_supervisor_user_prompt, build_synthesizer_user_prompt, get_prompt
from agent_service.router.models import RouterInput
from agent_service.router.rules import generate_candidates, is_document_generation_query
from backend.config import settings
from backend.utils.logger import get_logger

logger = get_logger(__name__)

# 允许 Supervisor 调度的 Agent 白名单，从 Agent Card 注册表派生（doc 19 §5.1）。
# 根治 contract_review 漏登记问题；synthesize 为编排保留步骤，不在此列。
ALLOWED_AGENTS = get_registry().allowed_agents()

# Supervisor / Synthesizer 系统提示词，启动时加载一次
SUPERVISOR_SYSTEM = get_prompt("supervisor_system")
SYNTHESIZER_SYSTEM = get_prompt("synthesizer_system")


class SupervisorDecision(BaseModel):
    """Supervisor 每轮的决策输出，约束 LLM 必须按 action 填齐字段。"""

    thought: str = ""
    action: Literal["call_agent", "synthesize", "finish"]
    agent: str | None = None
    input: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _check_action_fields(self) -> SupervisorDecision:
        """按 action 校验必填字段，缺字段直接抛错让上层降级。"""
        if self.action == "call_agent":
            if not self.agent:
                raise ValueError("call_agent 必须指定 agent")
            if not self.input:
                raise ValueError("call_agent 必须指定 input")
        elif self.action == "synthesize":
            if not self.reason:
                raise ValueError("synthesize 必须给出 reason")
        return self


class Supervisor:
    """多 Agent 编排器，手动驱动决策循环并穿插 SSE 事件。

    不使用 LangGraph graph.astream，因为需要在 Agent 执行前后发自定义事件，
    并在合成阶段流式输出 token。graph 编译版本供 ainvoke 非流式调用复用。
    """

    def __init__(
        self,
        *,
        agent_manager: Any,
        llm: BaseLLM,
        db: Any,
        embedding: Any | None = None,
        reranker: Any | None = None,
        candidates_fn: Any | None = None,
        query_rewriter: Any | None = None,
    ) -> None:
        """注入 AgentManager、LLM、DB 和检索组件；candidates_fn 默认复用规则候选。

        query_rewriter 为编排层查询改写器（QueryRewriteLayer），决策循环开始前
        先规范化用户 query，再进入意图/候选生成。
        """
        self.agent_manager = agent_manager
        self.llm = llm
        self.db = db
        self.embedding = embedding
        self.reranker = reranker
        self.candidates_fn = candidates_fn or generate_candidates
        self.query_rewriter = query_rewriter
        self.max_rounds = settings.supervisor_max_rounds
        self.max_agent_calls = settings.supervisor_max_agent_calls
        self.llm_temperature = settings.supervisor_llm_temperature
        self.llm_max_tokens = settings.supervisor_llm_max_tokens
        self.llm_timeout = settings.supervisor_llm_timeout
        self.llm_retry = settings.supervisor_llm_retry
        self.synth_temperature = settings.synthesizer_temperature

    async def astream(self, state: SharedState) -> AsyncIterator[str]:
        """流式执行 Supervisor 决策循环，产出 SSE 事件。

        流程：rewrite → init → (decide → agent_exec)* → synthesize/finish → citation_merge → final
        超过 max_rounds 或同一 Agent 调用次数达上限时强制 synthesize。
        """
        yield sse_event("supervisor_start", {
            "entry_hint": state.get("entry_hint") or "",
            "max_rounds": self.max_rounds,
        })

        # 已有结构化案件记忆时，“房东叫张某”“第三次是3月20日”只是事实续写，
        # 无需再调用 Supervisor 决策模型。直接交给 law_qa 可避免两次决策超时，
        # 同时保留业务 Agent 的检索、提示词、引用校验和最终答案生成能力。
        fast_agent = self._structured_followup_agent(state)
        if fast_agent:
            query = str(state.get("query") or "").strip()
            state.setdefault("original_query", query)
            state.update(await self._init(state))
            state["entry_hint"] = fast_agent
            state["current_round"] = 1
            yield sse_event("agent_start", {
                "round": 1,
                "agent": fast_agent,
                "input": query,
                "thought": "结构化案件事实补充，跳过 Supervisor LLM 决策",
            })
            agent = self.agent_manager.create_agent(
                fast_agent,
                llm=self.llm,
                db=self.db,
                embedding=self.embedding,
                reranker=self.reranker,
            )
            result = await agent.invoke_for_supervisor(query, state)
            state["agent_history"] = [{
                "round": 1,
                "agent": fast_agent,
                "input": query,
                "thought": "结构化案件事实补充，跳过 Supervisor LLM 决策",
                "output_summary": result.get("output_summary") or "",
                "chunks_count": len(result.get("chunks") or []),
                "citations_count": len(result.get("citations") or []),
            }]
            state["agent_results"] = [result]
            state.update(await self._finish(state))
            yield sse_event("agent_end", {
                "round": 1,
                "agent": fast_agent,
                "chunks_count": len(result.get("chunks") or []),
                "citations_count": len(result.get("citations") or []),
                "output_summary": result.get("output_summary") or "",
            })
            yield sse_event("supervisor_finish", {
                "reason": "结构化案件事实补充已由 law_qa 直接处理",
            })
            yield sse_event("final", self._final_payload(state))
            return

        # 查询改写：用户提问后先规范化 query（纠错别字/口语转法律术语），再进入决策循环。
        # 改写结果写回 state["query"]，_init/_decide/_gen_candidates 自动读取。
        if self.query_rewriter is not None:
            meta = await self.query_rewriter.rewrite(state)
            if meta:
                yield sse_event("query_rewrite", meta)

        # 初始化轮次和 entry_hint
        state.update(await self._init(state))

        while True:
            round_num = int(state.get("current_round") or 0) + 1

            # 强制终止：超过 max_rounds
            if round_num > self.max_rounds:
                logger.info("Supervisor 超过最大轮次 %d，强制合成", self.max_rounds)
                yield sse_event("supervisor_synthesize", {"reason": "超过最大轮次，强制合成"})
                async for piece in self._synthesize_stream(state):
                    yield sse_event("token", {"content": piece})
                break

            # 决策
            decision = await self._decide(state, round_num)
            if decision is None:
                # LLM 决策失败：有产出则合成，无产出则报错
                if state.get("agent_results"):
                    yield sse_event("supervisor_synthesize", {"reason": "决策 LLM 失败，用已有产出台成"})
                    async for piece in self._synthesize_stream(state):
                        yield sse_event("token", {"content": piece})
                else:
                    state["final_answer"] = "（决策失败，未能生成答案，请重试）"
                    state["final_citations"] = []
                break

            if decision.action == "synthesize":
                yield sse_event("supervisor_synthesize", {"reason": decision.reason or ""})
                async for piece in self._synthesize_stream(state):
                    yield sse_event("token", {"content": piece})
                break

            if decision.action == "finish":
                yield sse_event("supervisor_finish", {"reason": decision.thought})
                state.update(await self._finish(state))
                break

            # call_agent：记录轮次并检查同一 Agent 调用次数
            state["current_round"] = round_num
            agent_key = decision.agent or ""
            agent_count = sum(
                1 for h in state.get("agent_history") or [] if h.get("agent") == agent_key
            )
            if agent_count >= self.max_agent_calls:
                logger.info("Agent %s 已达最大调用次数 %d，强制合成", agent_key, self.max_agent_calls)
                yield sse_event("supervisor_synthesize", {
                    "reason": f"{agent_key} 已达最大调用次数，强制合成",
                })
                async for piece in self._synthesize_stream(state):
                    yield sse_event("token", {"content": piece})
                break

            # agent 不在白名单：降级为 synthesize
            if agent_key not in ALLOWED_AGENTS:
                logger.warning("Supervisor 返回未支持的 agent: %s", agent_key)
                yield sse_event("supervisor_synthesize", {
                    "reason": f"agent {agent_key} 暂未接入，强制合成",
                })
                async for piece in self._synthesize_stream(state):
                    yield sse_event("token", {"content": piece})
                break

            yield sse_event("agent_start", {
                "round": round_num,
                "agent": agent_key,
                "input": decision.input or "",
                "thought": decision.thought,
            })

            # 执行 Agent（每次新建实例，P1+P2 阶段简单可控）
            agent = self.agent_manager.create_agent(
                agent_key,
                llm=self.llm,
                db=self.db,
                embedding=self.embedding,
                reranker=self.reranker,
            )
            result = await agent.invoke_for_supervisor(decision.input or "", state)

            # 写回历史和产出
            agent_history = list(state.get("agent_history") or [])
            agent_history.append({
                "round": round_num,
                "agent": agent_key,
                "input": decision.input or "",
                "thought": decision.thought,
                "output_summary": result.get("output_summary") or "",
                "chunks_count": len(result.get("chunks") or []),
                "citations_count": len(result.get("citations") or []),
            })
            agent_results = list(state.get("agent_results") or [])
            agent_results.append(result)
            state["agent_history"] = agent_history
            state["agent_results"] = agent_results

            # 聚合 trace_id：message.retrieval_trace_id 列仅存单个检索 trace（关联 rag_trace），
            # 故 state["trace_id"] 取首个非空；完整链路收集到 state["trace_ids"] 列表便于回放，
            # 避免逗号拼接超过 VARCHAR(50) 列宽（Data too long）。
            trace_id = result.get("trace_id") or ""
            if trace_id:
                if not state.get("trace_id"):
                    state["trace_id"] = trace_id
                trace_ids = list(state.get("trace_ids") or [])
                if trace_id not in trace_ids:
                    trace_ids.append(trace_id)
                state["trace_ids"] = trace_ids

            yield sse_event("agent_end", {
                "round": round_num,
                "agent": agent_key,
                "chunks_count": len(result.get("chunks") or []),
                "citations_count": len(result.get("citations") or []),
                "output_summary": result.get("output_summary") or "",
            })

            # “起诉/立案需要哪些材料”是边界清晰的单 Agent 清单型问题。
            # LawQaAgent 已负责检索、组织答案和引用校验，首轮成功后继续请求
            # Supervisor 再判断一次只会增加一次模型调用和超时风险，不会增加新信息。
            if self._can_finish_filing_material_query(state, agent_key, result):
                logger.info("民事立案材料问答已由 law_qa 完成，跳过二次 Supervisor 决策")
                yield sse_event("supervisor_finish", {
                    "reason": "民事立案材料清单已完整生成，无需二次规划",
                })
                state.update(await self._finish(state))
                break

            # 正式文书生成由 law_qa 在单次调用中完成；再次规划会重复生成整篇文书，
            # 显著增加耗时并可能触发 Supervisor 决策超时。
            if self._can_finish_document_generation(state, agent_key, result):
                logger.info("正式文书已由 law_qa 生成，跳过重复 Agent 调用和二次 Supervisor 决策")
                yield sse_event("supervisor_finish", {
                    "reason": "正式文书已生成，无需二次规划",
                })
                state.update(await self._finish(state))
                break

        # 所有 break 路径（超轮次/决策失败/合成/结束/超调用次数/不在白名单）
        # 都已在 _synthesize_stream 或 _finish 里设置 final_citations，
        # 此处不再做死代码兜底（doc 19 低危项），直接输出 final。
        yield sse_event("final", self._final_payload(state))

    async def ainvoke(self, state: SharedState) -> SharedState:
        """非流式执行，供测试和后台任务使用；内部复用 astream 但不输出 SSE。"""
        async for _ in self.astream(state):  # noqa: F841
            pass
        return state

    @staticmethod
    def _structured_followup_agent(state: SharedState) -> str:
        """识别可由既有结构化记忆确定的短事实追问，绕过易超时的规划模型。"""
        query = str(state.get("original_query") or state.get("query") or "").strip()
        memory = state.get("legal_memory") or {}
        if hasattr(memory, "model_dump"):
            memory = memory.model_dump(mode="json")
        current_case = dict((memory or {}).get("current_case") or {})
        if current_case.get("civil_dispute_topic") != "residential_lease_repair":
            return ""
        landlord_fact = re.fullmatch(
            r"\s*房东(?:叫|是|姓名为?)\s*[^，。；;？！?\s]{1,12}[。.]?\s*",
            query,
        )
        notice_date_fact = re.fullmatch(
            r"\s*(?:我)?第\s*[一二两三四五六七八九十\d]+\s*次"
            r"(?:催修|催告|通知|联系)?\s*(?:是|在|为)?\s*"
            r"(?:今年)?\s*(?:(?:20\d{2})\s*年)?\s*\d{1,2}\s*月\s*\d{1,2}\s*日[。.]?\s*",
            query,
        )
        rental_fact = any(re.fullmatch(pattern, query) for pattern in (
            r"\s*(?:房东|出租人)[^，。；;？！?\n]{0,12}(?:不修|不维修|一直没修|一直没有维修|仍未维修)[。.]?\s*",
            r"\s*(?:漏水|渗水)[^，。；;？！?\n]{0,12}(?:导致|造成)[^，。；;？！?\n]{0,8}电脑(?:损坏|进水|故障)[。.]?\s*",
            r"\s*电脑(?:维修|修理)(?:花了|花费|费用(?:是|为)?|费(?:是|为)?)?\s*\d+(?:\.\d+)?\s*元[。.]?\s*",
            r"\s*(?:我)?(?:有|也有|还有)维修发票[。.]?\s*",
            r"\s*(?:我)?(?:也)?有?[一二两三四五六七八九十\d]+次催修记录[。.]?\s*",
        ))
        return "law_qa" if landlord_fact or notice_date_fact or rental_fact else ""

    @staticmethod
    def _can_finish_filing_material_query(
        state: SharedState,
        agent_key: str,
        result: dict[str, Any],
    ) -> bool:
        """民事立案材料清单首轮成功时直接结束，避免无效二次规划。"""
        if agent_key != "law_qa" or not str(result.get("answer") or "").strip():
            return False
        query = str(state.get("query") or "")
        return ("起诉" in query or "立案" in query) and any(
            marker in query
            for marker in ("材料", "准备", "需要什么", "怎么办理", "办理渠道", "怎么提交")
        )

    @staticmethod
    def _can_finish_document_generation(
        state: SharedState,
        agent_key: str,
        result: dict[str, Any],
    ) -> bool:
        """正式文书首轮生成成功后直接结束，避免重复生成和决策超时。"""
        return (
            agent_key == "law_qa"
            and bool(str(result.get("answer") or "").strip())
            and is_document_generation_query(str(state.get("query") or ""))
        )

    # ===== 内部节点 =====

    async def _init(self, state: SharedState) -> dict[str, Any]:
        """初始化轮次和 entry_hint；entry_hint 优先用外部传入，否则取规则候选最高分。"""
        candidates = self._gen_candidates(state)
        entry_hint = state.get("entry_hint") or ""
        if not entry_hint:
            # 取最高分且非 None 的候选 agent 作为 entry_hint
            entry_hint = next(
                (c.agent for c in candidates if c.agent),
                "law_qa",
            )
        return {
            "current_round": 0,
            "agent_history": [],
            "agent_results": [],
            "entry_hint": entry_hint,
            "max_rounds": self.max_rounds,
        }

    async def _decide(self, state: SharedState, round_num: int) -> SupervisorDecision | None:
        """规则候选 + LLM 判别，产出 SupervisorDecision；失败重试 1 次后返回 None。

        使用 chat_json 统一 JSON 输出与解析，raw 原文日志下沉到 chat_json 层，
        本层只关心决策对象与业务重试。
        """
        candidates = self._gen_candidates(state)
        user_prompt = build_supervisor_user_prompt(
            query=state.get("original_query") or state.get("query") or "",
            entry_hint=state.get("entry_hint") or "",
            agent_history=state.get("agent_history") or [],
            candidates=candidates,
            round_num=round_num,
            max_rounds=self.max_rounds,
        )

        for attempt in range(self.llm_retry + 1):
            try:
                # provider 专属参数（DeepSeek thinking 关闭）已下沉到 provider 层封装，
                # 业务代码不出现 provider 专属参数（doc 19 D7 / §5.5 模型分层）。
                payload = await asyncio.wait_for(
                    self.llm.chat_json(
                        SUPERVISOR_SYSTEM,
                        user_prompt,
                        temperature=self.llm_temperature,
                        max_tokens=self.llm_max_tokens,
                    ),
                    timeout=self.llm_timeout,
                )
                return SupervisorDecision.model_validate(payload)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Supervisor 决策 LLM 失败 (attempt=%d): %s: %s",
                    attempt + 1,
                    exc.__class__.__name__,
                    exc,
                )
                if attempt < self.llm_retry:
                    await asyncio.sleep(min(2**attempt, 2))
                    continue
        return None

    async def _finish(self, state: SharedState) -> dict[str, Any]:
        """finish=直接用最后一个 Agent 的答案。

        doc 19 D1：直接使用最后一个 Agent 答案时，必须按全局合并编号重写 [n]，
        否则 final_answer 引用编号与 final_citations 错位。
        """
        results = state.get("agent_results") or []
        if not results:
            return {"final_answer": "（未能生成答案）", "final_citations": []}
        last = results[-1]
        merged, renumber_map = merge_citations(results)
        final_answer = renumber_answer_text(last.get("answer") or "", last.get("agent") or "", renumber_map)
        return {
            "final_answer": final_answer,
            "final_citations": merged,
            "merged_citations": merged,
        }

    async def _synthesize_stream(self, state: SharedState) -> AsyncIterator[str]:
        """合并引用 + 调 Synthesizer LLM 流式重写最终答案。

        LLM 失败时用最后一个 Agent 的 answer 作为兜底（L3 兜底）。
        """
        merged, renumber_map = merge_citations(state.get("agent_results") or [])
        state["merged_citations"] = merged
        state["final_citations"] = merged

        # 无产出兜底
        if not state.get("agent_results"):
            state["final_answer"] = "（未能生成答案，请重试）"
            yield state["final_answer"]
            return

        user_prompt = build_synthesizer_user_prompt(
            query=state.get("original_query") or state.get("query") or "",
            agent_results=state.get("agent_results") or [],
            merged_citations=merged,
            renumber_map=renumber_map,
        )
        messages = [
            {"role": "system", "content": SYNTHESIZER_SYSTEM},
            {"role": "user", "content": user_prompt},
        ]

        answer_parts: list[str] = []
        try:
            async for piece in self.llm.stream(
                messages,
                temperature=self.synth_temperature,
                max_tokens=settings.llm_max_tokens,
            ):
                answer_parts.append(piece)
                yield piece
            state["final_answer"] = "".join(answer_parts)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Synthesizer LLM 失败，用最后 Agent 答案兜底: %s", exc.__class__.__name__)
            last = state["agent_results"][-1]
            # doc 19 D1：L3 兜底同样重写引用编号，避免与全局 final_citations 错位
            state["final_answer"] = renumber_answer_text(
                last.get("answer") or "（生成失败，请重试）",
                last.get("agent") or "",
                renumber_map,
            )
            yield state["final_answer"]

    # ===== 辅助方法 =====

    def _gen_candidates(self, state: SharedState) -> list[Any]:
        """构造 RouterInput 调用规则候选生成器，注入记忆/文件/知识库上下文。

        修复 doc 19 D3：此前只传 user_query，导致 has_uploaded_contract /
        has_memory_continuation 在 Supervisor 路径下恒为 False。
        """
        query = str(state.get("query") or "")
        if not query.strip():
            return []
        return self.candidates_fn(
            RouterInput(
                user_query=query,
                conversation_id=str(state.get("conversation_id") or ""),
                user_id=str(state.get("user_id") or ""),
                tenant_id=str(state.get("tenant_id") or ""),
                history_summary=state.get("history_summary"),
                legal_memory=state.get("legal_memory"),
                uploaded_files=state.get("uploaded_files") or [],
                available_kbs=state.get("available_kbs") or [],
            )
        )

    def _final_payload(self, state: SharedState) -> dict[str, Any]:
        """生成 SSE final 事件载荷，与现有 BaseAgent.final_payload 结构对齐。"""
        risk_alerts = self._build_risk_alerts(state)
        return {
            "answer": state.get("final_answer") or "",
            "citations": state.get("final_citations") or [],
            "risk_alerts": risk_alerts,
            "trace_id": state.get("trace_id") or "",
            "needs_human_review": bool(state.get("risk_level") == "high"),
            "agent_history": state.get("agent_history") or [],
        }

    @staticmethod
    def _build_risk_alerts(state: SharedState) -> list[dict[str, Any]]:
        """把风险等级转换为前端可展示的风险提醒。"""
        if state.get("risk_level") != "high":
            return []
        return [{"level": "high", "message": "该问题风险较高，建议人工复核后再使用结论。"}]
