"""本文件导出 Router Agent 的入口类、数据结构与状态映射方法。"""

from agent_service.router.models import Candidate, LegalMemory, RouterDecision, RouterInput
from agent_service.router.router import RouterAgent
from agent_service.router.state_mapper import LegalAgentState, build_initial_state

__all__ = [
    "Candidate",
    "LegalAgentState",
    "LegalMemory",
    "RouterAgent",
    "RouterDecision",
    "RouterInput",
    "build_initial_state",
]

