"""本文件提供 Router Agent 和 Memory 的 FastAPI 依赖注入函数。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Request

from agent_service.memory import RedisMemory
from agent_service.router import RouterAgent


def get_router_agent(request: Request) -> RouterAgent:
    """从 FastAPI 应用状态中取得 RouterAgent 实例。"""
    return request.app.state.router_agent


def get_memory(request: Request) -> RedisMemory:
    """从 FastAPI 应用状态中取得短期 Memory 实例。"""
    return request.app.state.memory


RouterAgentDep = Annotated[RouterAgent, Depends(get_router_agent)]
MemoryDep = Annotated[RedisMemory, Depends(get_memory)]

__all__ = ["MemoryDep", "RouterAgentDep", "get_memory", "get_router_agent"]

