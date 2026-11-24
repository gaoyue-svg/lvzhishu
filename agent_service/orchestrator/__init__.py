"""本子包实现 v2 多 Agent 编排层（doc 19 多Agent编排与治理方案）。

链路：查询改写(QueryRewriteLayer) → 意图识别(IntentLayer) → 规划(Planner) →
执行(PlanExecutor) → 审查(Reviewer) → 合成(Synthesizer)，由 MultiAgentPipeline 串成 SSE 流式。
"""

from .executor import PlanExecutor
from .intent import IntentLayer
from .planner import Planner
from .query_rewrite import QueryRewriteLayer
from .reviewer import Reviewer
from .synthesizer import Synthesizer
from .pipeline import MultiAgentPipeline
from .plan import PlanDAG, PlanStep, default_single_step_plan
from .run_state import MultiAgentRun, SlotStore, StepTrace
from .workflow import build_preset_plan, match_preset_workflow

__all__ = [
    "PlanExecutor",
    "IntentLayer",
    "QueryRewriteLayer",
    "Planner",
    "Reviewer",
    "Synthesizer",
    "MultiAgentPipeline",
    "PlanDAG",
    "PlanStep",
    "default_single_step_plan",
    "MultiAgentRun",
    "SlotStore",
    "StepTrace",
    "build_preset_plan",
    "match_preset_workflow",
]
