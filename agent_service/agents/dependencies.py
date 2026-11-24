"""本文件提供从 FastAPI app.state 获取 AgentManager 的依赖函数。"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from .manager import AgentManager


def get_agent_manager(request: Request) -> AgentManager:
    """返回应用级 AgentManager 实例。"""
    return request.app.state.agent_manager


AgentManagerDep = Annotated[AgentManager, Depends(get_agent_manager)]

__all__ = ["AgentManagerDep", "get_agent_manager"]

