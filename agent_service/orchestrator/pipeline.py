"""本文件实现 v2 多 Agent 全链路（doc 19 架构总览）：改写→意图→规划→执行→审查→合成。

串成一条 SSE 流式链路，替代 Supervisor V1 的逐轮决策循环；事件名与 V1 对齐
（agent_start/agent_end/token/final），前端无需改动即可消费。

实现说明：执行器与合成器内部通过 on_token/on_event 回调产出事件，pipeline
用 asyncio.Queue + 后台任务把事件转发为 SSE 帧，保证流式顺序与执行进度同步。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import json
import re
from time import perf_counter
from typing import Any
from uuid import uuid4

from agent_service.agents.base import sse_event
from agent_service.agents.citation_merge import sanitize_citation_references
from backend.config import settings
from backend.utils.logger import get_logger

from .executor import PlanExecutor
from .hooks import (
    AFTER_PLAN,
    AFTER_PIPELINE,
    AFTER_REVIEW,
    AFTER_SYNTHESIZE,
    BEFORE_PIPELINE,
    BEFORE_PLAN,
    BEFORE_REVIEW,
    BEFORE_SYNTHESIZE,
    get_hook_bus,
)
from .intent import IntentLayer
from .planner import Planner
from .query_rewrite import QueryRewriteLayer
from .reviewer import Reviewer
from .run_state import MultiAgentRun
from .synthesizer import Synthesizer
from .trace_recorder import finalize_run

logger = get_logger(__name__)


class MultiAgentPipeline:
    """把意图/规划/执行/审查/合成串成一条 SSE 流式链路。"""

    def __init__(
        self,
        *,
        query_rewrite_layer: QueryRewriteLayer,
        intent_layer: IntentLayer,
        planner: Planner,
        executor: PlanExecutor,
        reviewer: Reviewer,
        synthesizer: Synthesizer,
        replan_max: int | None = None,
    ) -> None:
        """注入各层组件；replan_max 默认取配置 replan_max。"""
        self.query_rewrite_layer = query_rewrite_layer
        self.intent_layer = intent_layer
        self.planner = planner
        self.executor = executor
        self.reviewer = reviewer
        self.synthesizer = synthesizer
        self.replan_max = replan_max if replan_max is not None else settings.replan_max

    async def run(self, shared_state: dict[str, Any]) -> AsyncIterator[str]:
        """执行一次完整 run，产出 SSE 帧。

        Harness 收尾：整个函数体用 try/finally 包裹，finally 内 best-effort 落 agent_run_trace
        并触发 after_pipeline hook（doc 21），正常结束 / 异常中断 / 前端断连都会执行。
        """
        started = perf_counter()
        hook_bus = get_hook_bus()
        await hook_bus.emit(BEFORE_PIPELINE, {"shared_state": shared_state, "started": started})

        # ① 查询改写：先规范化用户提问，再进入意图识别；改写结果写回 shared_state["query"]，
        # 下游 intent/planner/executor/synthesizer 自动读到规范化 query（$user.query 引用共享状态）。
        rewrite_meta = await self.query_rewrite_layer.rewrite(shared_state)
        if rewrite_meta:
            yield sse_event("v2_query_rewrite", rewrite_meta)

        query = str(shared_state.get("query") or "")
        # 用入口生成的 run 级 trace_id 初始化（executor 只在为空时填充首个检索 trace，避免覆盖）
        run = MultiAgentRun(plan_id="", query=query, trace_id=shared_state.get("trace_id") or "")

        # 预置 slot：会话上传合同的条款由 chat_agent 预解析进 plan_slots.clauses，直接注入本次 run，
        # 供 contract_review_upload 工作流各步骤消费（w1 透传，w2/w3/w4 并行）。
        for _slot_name, _slot_value in (shared_state.get("plan_slots") or {}).items():
            run.slots.set(_slot_name, _slot_value)

        error = ""
        try:
            # ② 意图识别
            run.intent = await self.intent_layer.analyze(shared_state)
            yield sse_event("v2_intent", {"intent": run.intent})

            # ③ 规划 + 守卫（守卫失败时 planner 内部已回退默认计划）
            await hook_bus.emit(BEFORE_PLAN, {"run": run, "shared_state": shared_state})
            plan = await self.planner.plan(run.intent, shared_state, plan_id=uuid4().hex[:12])
            run.plan = plan.model_dump(mode="json")
            run.plan_id = plan.plan_id
            await hook_bus.emit(AFTER_PLAN, {"run": run, "plan": plan, "shared_state": shared_state})
            yield sse_event(
                "v2_plan",
                {
                    "plan_id": plan.plan_id,
                    "steps": [step.model_dump() for step in plan.steps],
                    "entry_hint": run.intent.get("entry_hint") or "",
                },
            )

            # ④ 执行
            outcome: dict[str, Any] = {"ok": True}
            async for event in self._stream_execution(plan, run, shared_state, outcome):
                yield event
            ok = bool(outcome["ok"])

            # ⑤ 审查 + 失败重试/重规划闭环
            await hook_bus.emit(BEFORE_REVIEW, {"run": run, "shared_state": shared_state})
            review = await self.reviewer.review(run, db=self.executor.db)
            await hook_bus.emit(AFTER_REVIEW, {"run": run, "review": review, "shared_state": shared_state})
            yield sse_event(
                "v2_review",
                {
                    "passed": review["passed"],
                    "needs_human_review": review["needs_human_review"],
                    "failed_steps": review["failed_steps"],
                    "issues": review["issues"],
                },
            )

            retry_left = self.replan_max
            while not ok or not review["passed"]:
                if retry_left <= 0:
                    run.needs_human_review = True
                    yield sse_event("v2_hitl", {"message": "审查或执行重试仍失败，转人工复核"})
                    break
                retry_left -= 1

                if not ok:
                    # 执行失败：在已产出 slot 基础上重规划出错步
                    failed_step = self._first_failed_step(plan, run)
                    if failed_step is None:
                        run.needs_human_review = True
                        break
                    replanned = await self.planner.replan(run, run.intent, shared_state, failed_step)
                    logger.info("[Pipeline] 失败重规划 step=%s agent=%s", failed_step.step_id, failed_step.agent)
                    async for event in self._stream_execution(replanned, run, shared_state, outcome):
                        yield event
                    ok = bool(outcome["ok"])
                elif review["failed_steps"]:
                    # 审查失败：重跑出错步
                    for step_id in review["failed_steps"]:
                        step = next((s for s in plan.steps if s.step_id == step_id), None)
                        if step is None:
                            continue
                        async for event in self._stream_step(plan, run, shared_state, step, outcome):
                            yield event
                    ok = True
                else:
                    # L2 抽查不符但无具体出错步：直接转人工复核
                    run.needs_human_review = True
                    break

                await hook_bus.emit(BEFORE_REVIEW, {"run": run, "shared_state": shared_state})
                review = await self.reviewer.review(run, db=self.executor.db)
                await hook_bus.emit(AFTER_REVIEW, {"run": run, "review": review, "shared_state": shared_state})
                yield sse_event(
                    "v2_review",
                    {
                        "passed": review["passed"],
                        "needs_human_review": review["needs_human_review"],
                        "failed_steps": review["failed_steps"],
                        "issues": review["issues"],
                    },
                )

            # ⑥ 合成：跨 Agent 引用合并 + 流式重写
            async for event in self._stream_synthesis(query, run, shared_state):
                yield event

            # 最终校验前再做一次确定性清理，覆盖未来新增 Synthesizer 或兜底路径。
            run.final_answer = sanitize_citation_references(run.final_answer, run.final_citations)

            # 合成后引用校验（D5）：失败不阻断，仅标记人审
            if self.reviewer.citation_validator is not None:
                validation = await self.reviewer.citation_validator.validate(
                    answer=run.final_answer,
                    citations=run.final_citations,
                    db=self.executor.db,
                )
                if not validation.get("passed"):
                    logger.warning("[Pipeline] 最终引用校验未通过: %s", validation.get("reasons"))
                    run.needs_human_review = True

            shared_state["final_answer"] = run.final_answer
            shared_state["final_citations"] = run.final_citations
            shared_state["merged_citations"] = run.final_citations
            shared_state["review_result"] = review
            shared_state["plan"] = run.plan
            shared_state["plan_slots"] = run.slots.as_dict()
            shared_state["trace_id"] = run.trace_id
            shared_state["needs_human_review"] = run.needs_human_review

            yield sse_event("final", self._final_payload(run))
        except GeneratorExit:
            # 前端断连/消费者提前关闭：仍走 finally 落库，不吞异常
            raise
        except Exception as exc:  # noqa: BLE001
            error = f"{exc.__class__.__name__}: {str(exc)[:500]}"
            logger.warning("[Pipeline] run 异常中断: %s", error)
            raise
        finally:
            await finalize_run(run, shared_state, started=started, error=error)

    # ===== 内部辅助 =====

    async def _stream_execution(
        self,
        plan: Any,
        run: MultiAgentRun,
        shared_state: dict[str, Any],
        outcome: dict[str, Any],
    ) -> AsyncIterator[str]:
        """执行整份计划并流式转发 agent_start/agent_end 事件。"""
        queue: asyncio.Queue[str] = asyncio.Queue()
        task = asyncio.create_task(self._execute_plan(plan, run, shared_state, queue))
        async for event in _drain_queue(task, queue, outcome):
            yield event

    async def _stream_step(
        self,
        plan: Any,
        run: MultiAgentRun,
        shared_state: dict[str, Any],
        step: Any,
        outcome: dict[str, Any],
    ) -> AsyncIterator[str]:
        """重跑单个出错步并流式转发事件。"""
        queue: asyncio.Queue[str] = asyncio.Queue()
        task = asyncio.create_task(self._rerun_step(plan, run, shared_state, step, queue))
        async for event in _drain_queue(task, queue, outcome):
            yield event

    async def _execute_plan(
        self,
        plan: Any,
        run: MultiAgentRun,
        shared_state: dict[str, Any],
        queue: asyncio.Queue[str],
    ) -> bool:
        """整份计划执行任务；结束时放 None 哨兵。"""
        try:
            return await self.executor.execute(
                plan,
                run,
                shared_state,
                on_event=lambda ev, data: queue.put_nowait(sse_event(ev, data)),
            )
        finally:
            await queue.put(None)

    async def _rerun_step(
        self,
        plan: Any,
        run: MultiAgentRun,
        shared_state: dict[str, Any],
        step: Any,
        queue: asyncio.Queue[str],
    ) -> bool:
        """单步重跑任务；结束时放 None 哨兵。"""
        try:
            return await self.executor.rerun_step(
                plan,
                run,
                shared_state,
                step,
                on_event=lambda ev, data: queue.put_nowait(sse_event(ev, data)),
            )
        finally:
            await queue.put(None)

    async def _stream_synthesis(
        self,
        query: str,
        run: MultiAgentRun,
        shared_state: dict[str, Any],
    ) -> AsyncIterator[str]:
        """流式合成最终答案并转发 token 事件。"""
        queue: asyncio.Queue[Any] = asyncio.Queue()
        result_box: dict[str, Any] = {}

        hook_bus = get_hook_bus()
        await hook_bus.emit(BEFORE_SYNTHESIZE, {"run": run, "shared_state": shared_state})

        async def _run_synth() -> None:
            try:
                result_box["result"] = await self.synthesizer.synthesize(
                    query,
                    run.agent_results,
                    on_token=lambda piece: queue.put_nowait(piece),
                )
            finally:
                await queue.put(None)

        task = asyncio.create_task(_run_synth())
        while True:
            item = await queue.get()
            if item is None:
                await task
                break
            yield sse_event("token", {"content": item})

        synth = result_box.get("result") or {"answer": "", "citations": []}
        run.final_answer = synth.get("answer") or ""
        run.final_citations = synth.get("citations") or []
        await hook_bus.emit(AFTER_SYNTHESIZE, {"run": run, "result": synth, "shared_state": shared_state})

    def _first_failed_step(self, plan: Any, run: MultiAgentRun) -> Any | None:
        """返回第一个执行失败的 step。"""
        failed_ids = {trace.step_id for trace in run.step_traces if trace.status == "failed"}
        return next((step for step in plan.steps if step.step_id in failed_ids), None)

    @staticmethod
    def _final_payload(run: MultiAgentRun) -> dict[str, Any]:
        """生成 SSE final 事件载荷，与 Supervisor V1 对齐。"""
        risk_alerts: list[dict[str, Any]] = []
        if (run.intent or {}).get("risk_level") == "high":
            risk_alerts.append({"level": "high", "message": "该问题风险较高，建议人工复核后再使用结论。"})
        return {
            "answer": run.final_answer,
            "citations": run.final_citations,
            "risk_alerts": risk_alerts,
            "trace_id": run.trace_id,
            "needs_human_review": run.needs_human_review,
            "agent_history": [
                {"agent": r.get("agent"), "output_summary": r.get("output_summary")} for r in run.agent_results
            ],
            "plan": run.plan,
            "contract": extract_contract_payload(run.slots.as_dict()),
        }


async def _drain_queue(
    task: asyncio.Task,
    queue: asyncio.Queue[str],
    outcome: dict[str, Any],
) -> AsyncIterator[str]:
    """消费事件队列直到哨兵，把任务结果写入 outcome['ok']。"""
    while True:
        item = await queue.get()
        if item is None:
            outcome["ok"] = bool(task.result())
            break
        yield item


def extract_contract_payload(slots: dict[str, Any]) -> dict[str, Any]:
    """从 run slots 中提取合同分析结构化结果（摘要/要素/风险），供前端渲染与报告导出。

    slots 来源：contract_review_upload 工作流的 run.slots（或 shared_state["plan_slots"]）。
    - elements：contract_elements Agent 的 JSON 字符串 answer（含 summary 与 elements）
    - report：contract_risk_report Agent 的 JSON 风险数组 answer
    - rule_risks：contract_rule 的规则工具结果（风险兜底来源）
    """
    summary = ""
    elements: dict[str, Any] = {}
    elements_raw = slots.get("elements")
    if isinstance(elements_raw, str):
        try:
            parsed = json.loads(elements_raw)
            if isinstance(parsed, dict):
                summary = parsed.get("summary") or ""
                elements = parsed.get("elements") or {}
        except json.JSONDecodeError:
            pass
    elif isinstance(elements_raw, dict):
        summary = elements_raw.get("summary") or ""
        elements = elements_raw.get("elements") or {}

    # 风险：优先解析风险报告 Agent 的 JSON 数组，其次用规则工具结果兜底
    risks: list[Any] = []
    report_raw = slots.get("report")
    if isinstance(report_raw, str):
        risks = _parse_json_array(report_raw)
    if not risks:
        for call in slots.get("rule_risks") or []:
            result = call.get("result") or {}
            risks.extend(result.get("risks", []) or [])
    return {"summary": summary or "", "elements": elements or {}, "risks": risks or []}


def _parse_json_array(text: str) -> list[Any]:
    """从文本中解析 JSON 数组，兼容 ```json 代码块包裹。"""
    if not text:
        return []
    cleaned = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("```")
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []
