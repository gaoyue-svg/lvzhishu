"""本文件定义 Plan DAG 数据契约与守卫校验（doc 19 §4.2）。

数据契约规则：
- 每个 step 的 inputs 必须能从 $user / $intent / slot / 字面量解析；
- outputs 落 slot，供后续 step 读取；
- 守卫校验（validate_plan）纯代码，不依赖 LLM。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .run_state import SlotStore

# 编排器保留步骤：synthesize 由合成层执行，不在 Agent Card 注册表内
RESERVED_AGENTS = {"synthesize"}


class PlanStep(BaseModel):
    """单步计划：agent + 数据契约（inputs/outputs）+ 并行组 + 依赖。"""

    step_id: str
    agent: str
    goal: str = ""
    # inputs: LegalAgentState 字段名 → 引用或字面量
    #   引用前缀：$user（请求/会话上下文）、$intent（意图层输出）、slot.（工作记忆）
    #   例：{"query": "$user.query", "document_id": "$user.document_id",
    #        "retrieved_chunks": "slot.clauses", "context_text": "slot.law_context"}
    inputs: dict[str, Any] = Field(default_factory=dict)
    # outputs: AgentResult 字段名 → slot 名，如 {"chunks": "clauses", "citations": "law_cites"}
    outputs: dict[str, str] = Field(default_factory=dict)
    parallel_group: str = ""
    deps: list[str] = Field(default_factory=list)


class PlanDAG(BaseModel):
    """带数据契约的完整计划。"""

    plan_id: str = ""
    query: str = ""
    steps: list[PlanStep] = Field(default_factory=list)


def resolve_input_ref(
    ref: Any,
    *,
    user: dict[str, Any],
    intent: dict[str, Any],
    slots: SlotStore,
) -> Any:
    """解析 inputs 里的值引用：$user.x / $intent.x / slot.x / 字面量。

    Args:
        ref: 引用表达式或字面量。
        user: 请求/会话上下文（SharedState 相关字段）。
        intent: 意图识别层结构化输出。
        slots: 本次 run 的 slot 表。

    Returns:
        解析后的实参；解析不到时返回 None（由上层按缺失处理）。
    """
    if not isinstance(ref, str):
        return ref
    if ref.startswith("$user"):
        return _get_path(user, ref[len("$user") :])
    if ref.startswith("$intent"):
        return _get_path(intent, ref[len("$intent") :])
    if ref.startswith("slot."):
        return slots.get(ref[len("slot.") :])
    return ref


def _get_path(data: dict[str, Any], path: str) -> Any:
    """按 a.b.c 路径读取嵌套 dict，缺失返回 None。"""
    parts = [part for part in path.strip(".").split(".") if part]
    value: Any = data
    for part in parts:
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return None
    return value


def default_single_step_plan(agent: str, query: str, *, plan_id: str = "") -> PlanDAG:
    """规划默认克制的单步兜底计划：单 Agent + synthesize 标记。

    法务问答大多数问题 1~2 步足够；守卫失败或单 Agent 即可覆盖时使用。
    """
    return PlanDAG(
        plan_id=plan_id,
        query=query,
        steps=[
            PlanStep(
                step_id="s1",
                agent=agent,
                goal="直接回答用户问题",
                inputs={"query": "$user.query"},
                outputs={"chunks": "chunks", "citations": "cites", "answer": "answer"},
            ),
            PlanStep(
                step_id="s2",
                agent="synthesize",
                goal="合并引用并重写最终答案",
                deps=["s1"],
            ),
        ],
    )
