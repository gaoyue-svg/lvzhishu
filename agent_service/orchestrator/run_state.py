"""本文件定义 v2 多 Agent 编排的运行状态：slot 工作记忆、单步 Trace 与 run 级模型。

doc 19 §4.3：slot 表是本次 run 的"工作记忆"，每个 step 从 slot 读入参、产出落 slot；
MultiAgentRun 是 run 级状态模型，为 P2 checkpointer 持久化预留字段。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class SlotStore:
    """本次 run 的工作记忆：slot.{name} → value。

    语义上等价 doc 19 §4.3 的 slot 表，跨 step 传递上游产出，
    杜绝"每个 Agent 独立跑一遍、结果互不相见"。
    """

    def __init__(self) -> None:
        self._slots: dict[str, Any] = {}

    def set(self, name: str, value: Any) -> None:
        """写入一个 slot。"""
        self._slots[name] = value

    def get(self, name: str, default: Any = None) -> Any:
        """读取 slot，不存在返回默认值。"""
        return self._slots.get(name, default)

    def has(self, name: str) -> bool:
        """判断 slot 是否已写入。"""
        return name in self._slots

    def as_dict(self) -> dict[str, Any]:
        """导出全部 slot，便于落 trace / checkpoint。"""
        return dict(self._slots)


@dataclass
class StepTrace:
    """单步执行的可观测记录，为 P2 run 级 Trace 预留字段。"""

    step_id: str
    agent: str
    status: str = "pending"          # pending/running/success/failed/skipped
    goal: str = ""
    output_summary: str = ""
    chunks_count: int = 0
    citations_count: int = 0
    latency_ms: int = 0
    error: str = ""


@dataclass
class MultiAgentRun:
    """一次 run 的完整运行状态（doc 19 §4.3 MultiAgentRun 模型）。"""

    plan_id: str
    query: str
    plan: dict[str, Any] | None = None       # Plan DAG 序列化快照
    intent: dict[str, Any] = field(default_factory=dict)
    slots: SlotStore = field(default_factory=SlotStore)
    agent_results: list[dict[str, Any]] = field(default_factory=list)
    step_traces: list[StepTrace] = field(default_factory=list)
    review: dict[str, Any] = field(default_factory=dict)
    final_answer: str = ""
    final_citations: list[dict[str, Any]] = field(default_factory=list)
    trace_id: str = ""
    needs_human_review: bool = False
