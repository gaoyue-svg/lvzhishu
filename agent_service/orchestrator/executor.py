"""本文件实现执行层（doc 19 §4.3）：slot 表 + 拓扑执行 + 并行组 + 超时重试。

- 维护 slot 表（SlotStore），每步按数据契约从 slot 读入参、产出落 slot；
- 同波次就绪且相互独立的 step 用 asyncio.gather 并行执行；
- 每步 step_timeout 超时 + step_retry 指数退避重试；
- 单步仍失败时返回 False，由上层触发失败重规划或 HITL。
"""

from __future__ import annotations

import asyncio
from time import perf_counter
from typing import Any, Callable

from agent_service.agents.registry import get_registry
from backend.config import settings
from backend.utils.logger import get_logger

from .hooks import AFTER_STEP, BEFORE_STEP, get_hook_bus
from .plan import PlanDAG, PlanStep, resolve_input_ref
from .run_state import MultiAgentRun, StepTrace

logger = get_logger(__name__)

# 事件回调：on_event(event, data)，由 pipeline 转发为 SSE 帧
OnEvent = Callable[[str, dict[str, Any]], None]


class PlanExecutor:
    """按 Plan DAG 执行 Agent，把产出落 slot，为审查/合成提供原料。"""

    def __init__(
        self,
        agent_manager: Any,
        *,
        llm: Any,
        db: Any,
        embedding: Any | None = None,
        reranker: Any | None = None,
        step_timeout: float | None = None,
        step_retry: int | None = None,
    ) -> None:
        """注入 AgentManager 与请求级 LLM/DB/检索组件。"""
        self.agent_manager = agent_manager
        self.llm = llm
        self.db = db
        self.embedding = embedding
        self.reranker = reranker
        self.step_timeout = step_timeout if step_timeout is not None else settings.step_timeout
        self.step_retry = step_retry if step_retry is not None else settings.step_retry
        self.registry = get_registry()

    async def execute(
        self,
        plan: PlanDAG,
        run: MultiAgentRun,
        shared_state: dict[str, Any],
        *,
        on_event: OnEvent | None = None,
    ) -> bool:
        """按拓扑序执行全部非 synthesize 步骤，产出落 run.slots / run.agent_results。

        Returns:
            True=全部成功；False=存在失败步骤（由上层决定重规划或 HITL）。
        """
        if not plan.steps:
            logger.warning("[Executor] 空计划，跳过执行")
            return True

        by_id = {step.step_id: step for step in plan.steps}
        dependents: dict[str, list[str]] = {step.step_id: [] for step in plan.steps}
        indegree: dict[str, int] = {}
        for step in plan.steps:
            deps = [d for d in step.deps if d in by_id]
            indegree[step.step_id] = len(deps)
            for dep in deps:
                dependents[dep].append(step.step_id)

        ready = [step_id for step_id, degree in indegree.items() if degree == 0]
        completed: set[str] = set()
        ok_all = True

        while ready:
            wave = ready[:]
            ready = []
            outcomes = await asyncio.gather(
                *[
                    self._run_step(step, run, shared_state, on_event=on_event)
                    for step_id in wave
                    for step in [by_id[step_id]]
                ],
                return_exceptions=False,
            )
            for step_id, succeeded in zip(wave, outcomes):
                if not succeeded:
                    ok_all = False
                completed.add(step_id)
                for dependent in dependents[step_id]:
                    indegree[dependent] -= 1
                    if indegree[dependent] == 0:
                        ready.append(dependent)

        if ok_all:
            logger.info("[Executor] 计划执行完成 steps=%d results=%d", len(plan.steps), len(run.agent_results))
        return ok_all

    async def rerun_step(
        self,
        plan: PlanDAG,
        run: MultiAgentRun,
        shared_state: dict[str, Any],
        step: PlanStep,
        *,
        on_event: OnEvent | None = None,
    ) -> bool:
        """审查失败后的单步重跑：复用原 inputs/outputs，覆盖旧 slot 产出。"""
        logger.info("[Executor] 重跑出错步 step=%s agent=%s", step.step_id, step.agent)
        return await self._run_step(step, run, shared_state, on_event=on_event, replace=True)

    async def _run_step(
        self,
        step: PlanStep,
        run: MultiAgentRun,
        shared_state: dict[str, Any],
        *,
        on_event: OnEvent | None = None,
        replace: bool = False,
    ) -> bool:
        """执行单个 step：解析输入 → 调用 Agent → 落 slot。

        Returns:
            True=成功；False=超过重试次数仍失败。
        """
        if step.agent == "synthesize":
            # synthesize 是合成层标记步骤，执行层跳过
            return True

        trace = StepTrace(step_id=step.step_id, agent=step.agent, status="running", goal=step.goal)
        if not replace:
            run.step_traces.append(trace)

        hook_bus = get_hook_bus()
        await hook_bus.emit(BEFORE_STEP, {"run": run, "step": step, "trace": trace, "shared_state": shared_state})

        if on_event:
            on_event(
                "agent_start",
                {"round": len(run.agent_results) + 1, "agent": step.agent, "input": step.goal, "thought": step.goal},
            )

        overrides = self._resolve_inputs(step, run, shared_state)
        task_input = str(overrides.pop("query", "") or run.query)
        started = perf_counter()

        result: dict[str, Any] | None = None
        last_error: str = ""
        for attempt in range(self.step_retry + 1):
            try:
                agent = self.agent_manager.create_agent(
                    step.agent,
                    llm=self.llm,
                    db=self.db,
                    embedding=self.embedding,
                    reranker=self.reranker,
                )
                result = await asyncio.wait_for(
                    agent.invoke_for_supervisor(task_input, shared_state, overrides=overrides),
                    timeout=self.step_timeout,
                )
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc.__class__.__name__
                logger.warning("[Executor] step=%s agent=%s 失败 (attempt=%d): %s", step.step_id, step.agent, attempt + 1, last_error)
                if attempt < self.step_retry:
                    await asyncio.sleep(min(2**attempt, 4))

        latency_ms = int((perf_counter() - started) * 1000)
        if result is None:
            trace.status = "failed"
            trace.error = last_error
            trace.latency_ms = latency_ms
            if on_event:
                on_event("agent_end", {"round": len(run.agent_results) + 1, "agent": step.agent, "error": last_error})
            await hook_bus.emit(
                AFTER_STEP,
                {
                    "run": run,
                    "step": step,
                    "trace": trace,
                    "shared_state": shared_state,
                    "status": "failed",
                    "error": last_error,
                },
            )
            return False

        # 产出按 outputs 契约落 slot
        for out_field, slot_name in (step.outputs or {}).items():
            value = result.get(out_field)
            if value is not None:
                run.slots.set(slot_name, value)

        # 记录产出与 trace
        if replace:
            run.agent_results = [r for r in run.agent_results if r.get("_step_id") != step.step_id]
        result["_step_id"] = step.step_id
        run.agent_results.append(dict(result))

        trace.status = "success"
        trace.output_summary = result.get("output_summary") or ""
        trace.chunks_count = len(result.get("chunks") or [])
        trace.citations_count = len(result.get("citations") or [])
        trace.latency_ms = latency_ms
        run.trace_id = run.trace_id or result.get("trace_id") or ""

        if on_event:
            on_event(
                "agent_end",
                {
                    "round": len(run.agent_results),
                    "agent": step.agent,
                    "chunks_count": trace.chunks_count,
                    "citations_count": trace.citations_count,
                    "output_summary": result.get("output_summary") or "",
                },
            )
        await hook_bus.emit(
            AFTER_STEP,
            {
                "run": run,
                "step": step,
                "trace": trace,
                "shared_state": shared_state,
                "status": "success",
            },
        )
        return True

    def _resolve_inputs(
        self,
        step: PlanStep,
        run: MultiAgentRun,
        shared_state: dict[str, Any],
    ) -> dict[str, Any]:
        """按数据契约把 step.inputs 解析为子状态覆盖（LegalAgentState 字段名 → 实参）。"""
        overrides: dict[str, Any] = {}
        for field_name, ref in (step.inputs or {}).items():
            value = resolve_input_ref(
                ref,
                user=dict(shared_state),
                intent=dict(run.intent),
                slots=run.slots,
            )
            if value is not None:
                overrides[field_name] = value
        return overrides
