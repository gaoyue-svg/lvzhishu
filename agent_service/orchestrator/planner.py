"""本文件实现规划层（doc 19 §4.2 / §4.3）：Plan DAG 生成 + 守卫 + 预置工作流 + 默认兜底。

- 已知工作流（合同审查）直通预置模板，不走 LLM 规划；
- 单 Agent 即可覆盖的问题走默认单步计划，规划默认克制；
- 其余由 LLM 产出 Plan DAG，过 AgentCardRegistry.validate_plan 守卫；
- 守卫失败或 LLM 不可用时回退默认单步计划（P1-4 兜底）。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from agent_service.agents.registry import AgentCardRegistry, get_registry
from agent_service.llm.usage import usage_purpose
from agent_service.prompts import get_prompt
from backend.config import settings
from backend.utils.logger import get_logger

from .plan import PlanDAG, PlanStep, default_single_step_plan
from .run_state import MultiAgentRun
from .workflow import build_preset_plan, match_preset_workflow

logger = get_logger(__name__)

PLANNER_SYSTEM = get_prompt("planner_system")


class Planner:
    """规划层：按意图 + Agent Card 注册表产出 plan-and-execute 的 Plan DAG。"""

    def __init__(
        self,
        llm: Any,
        *,
        registry: AgentCardRegistry | None = None,
        max_steps: int | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: int | None = None,
        retry: int | None = None,
    ) -> None:
        """注入 LLM 与 Agent Card 注册表；max_steps 默认取配置 plan_max_steps。"""
        self.llm = llm
        self.registry = registry or get_registry()
        self.max_steps = max_steps if max_steps is not None else settings.plan_max_steps
        self.temperature = temperature if temperature is not None else settings.planner_llm_temperature
        self.max_tokens = max_tokens if max_tokens is not None else settings.planner_llm_max_tokens
        self.timeout = timeout if timeout is not None else settings.planner_llm_timeout
        self.retry = retry if retry is not None else settings.planner_llm_retry

    async def plan(
        self,
        intent: dict[str, Any],
        shared_state: dict[str, Any],
        *,
        plan_id: str = "",
    ) -> PlanDAG:
        """生成计划：预置工作流 → 默认单步 → LLM 规划 → 兜底单步。"""
        query = str(shared_state.get("query") or "")

        # 1. 预置工作流：合同审查等固定流程，不交给 LLM
        workflow = match_preset_workflow(intent, shared_state)
        if workflow:
            preset = build_preset_plan(workflow, query=query, plan_id=plan_id)
            if preset is not None:
                logger.info("[Planner] 直通预置工作流 workflow=%s steps=%d", workflow, len(preset.steps))
                return preset

        # 2. 单 Agent 即可覆盖的 fast-path：默认单步计划（规划默认克制）
        entry_hint = str(intent.get("entry_hint") or shared_state.get("entry_hint") or "").strip()
        if entry_hint and _single_agent_covering(intent):
            return default_single_step_plan(entry_hint, query, plan_id=plan_id)

        # 3. LLM 规划 + 守卫
        llm_plan = await self._llm_plan(intent, query, plan_id=plan_id)
        if llm_plan is not None:
            return llm_plan

        # 4. 兜底默认计划
        logger.warning("[Planner] LLM 规划失败或守卫不过，回退默认单步计划 entry_hint=%s", entry_hint or "law_qa")
        return default_single_step_plan(entry_hint or "law_qa", query, plan_id=plan_id)

    async def replan(
        self,
        run: MultiAgentRun,
        intent: dict[str, Any],
        shared_state: dict[str, Any],
        failed_step: PlanStep,
        *,
        plan_id: str = "",
    ) -> PlanDAG | None:
        """失败重规划钩子（doc 19 §4.3）：在已产出 slot 基础上重跑出错步。

        Args:
            run: 当前 run（含已产出 slots / agent_results）。
            failed_step: 审查或执行失败的步骤。

        Returns:
            重规划后的 PlanDAG（重跑出错步 + 合成），供上层在保留 slots 的前提下续跑。
        """
        query = str(shared_state.get("query") or "")
        logger.info("[Planner] 失败重规划 step=%s agent=%s", failed_step.step_id, failed_step.agent)
        return PlanDAG(
            plan_id=plan_id or f"{run.plan_id or 'plan'}_replan",
            query=query,
            steps=[
                PlanStep(
                    step_id=failed_step.step_id,
                    agent=failed_step.agent,
                    goal=failed_step.goal,
                    inputs=failed_step.inputs,
                    outputs=failed_step.outputs,
                    deps=[],
                ),
                PlanStep(step_id="s_synth", agent="synthesize", goal="合并引用并重写最终答案", deps=[failed_step.step_id]),
            ],
        )

    async def _llm_plan(self, intent: dict[str, Any], query: str, *, plan_id: str = "") -> PlanDAG | None:
        """调用规划 LLM 产出 Plan DAG，经守卫校验；失败或校验不过返回 None。"""
        user_prompt = self._build_plan_prompt(intent, query)
        for attempt in range(self.retry + 1):
            try:
                with usage_purpose("plan"):
                    payload = await asyncio.wait_for(
                        self.llm.chat_json(
                            PLANNER_SYSTEM,
                            user_prompt,
                            temperature=self.temperature,
                            max_tokens=self.max_tokens,
                        ),
                        timeout=self.timeout,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[Planner] LLM 规划失败 (attempt=%d): %s", attempt + 1, exc.__class__.__name__)
                if attempt < self.retry:
                    await asyncio.sleep(min(2**attempt, 2))
                continue

            try:
                plan = _parse_plan_payload(payload, query, plan_id=plan_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[Planner] Plan 解析失败: %s", exc.__class__.__name__)
                continue

            errors = self.registry.validate_plan([step.model_dump() for step in plan.steps], self.max_steps)
            if not errors:
                logger.info("[Planner] LLM 规划通过守卫 steps=%d", len(plan.steps))
                return plan
            logger.warning("[Planner] Plan 守卫不通过: %s", "；".join(errors))
            return None
        return None

    def _build_plan_prompt(self, intent: dict[str, Any], query: str) -> str:
        """构造规划 prompt：注入意图、Agent 卡片、数据契约约束。"""
        card_block = self.registry.agent_blocks()
        payload = {
            "user_query": query,
            "intent": intent,
            "agent_cards": card_block,
            "constraints": {
                "max_steps": self.max_steps,
                "last_step_agent": "synthesize",
                "inputs_format": "键=LegalAgentState 字段名，值=$user.x / $intent.x / slot.name / 字面量",
                "outputs_format": "键=AgentResult 字段名(chunks/citations/answer/tool_calls/context_text)，值=slot 名",
            },
        }
        return "请基于以下上下文输出 Plan JSON：\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def _single_agent_covering(intent: dict[str, Any]) -> bool:
    """判断单 Agent 是否足以覆盖：法条定位/合同审查入口且无多路诉求。"""
    entry_hint = str(intent.get("entry_hint") or "")
    if entry_hint in {"article_locate", "law_qa"}:
        return True
    # 案例分析默认需要联网+本地双路，仍允许单 Agent 直达
    return entry_hint == "case_analysis" and not (intent.get("sub_questions") or [])


def _parse_plan_payload(payload: dict[str, Any], query: str, *, plan_id: str) -> PlanDAG:
    """把 LLM 返回的 plan payload 解析为 PlanDAG。"""
    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("LLM 未返回 steps 数组")
    steps: list[PlanStep] = []
    for index, raw in enumerate(raw_steps):
        step_id = str(raw.get("step_id") or f"s{index + 1}")
        agent = str(raw.get("agent") or "")
        if not agent:
            raise ValueError(f"step {step_id} 缺少 agent")
        steps.append(
            PlanStep(
                step_id=step_id,
                agent=agent,
                goal=str(raw.get("goal") or ""),
                inputs=dict(raw.get("inputs") or {}),
                outputs=dict(raw.get("outputs") or {}),
                parallel_group=str(raw.get("parallel_group") or ""),
                deps=[str(item) for item in (raw.get("deps") or [])],
            )
        )
    return PlanDAG(plan_id=plan_id, query=query, steps=steps)
