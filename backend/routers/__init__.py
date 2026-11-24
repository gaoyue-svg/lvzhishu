"""本文件集中收集需要自动挂载到 FastAPI 应用的路由。"""

from fastapi import APIRouter

from agent_service.harness.monitor import router as harness_monitor_router
from agent_service.metrics.router import router as metrics_router
from agent_service.routers import agent
from backend.routers import (
    auth,
    chat_upload,
    chunk,
    contract,
    conversation,
    dashboard,
    document,
    kb,
    llm_config,
    user,
)
from rag_service.routers import retrieval

routers: list[APIRouter] = [
    auth.router,
    user.router,
    kb.router,
    document.router,
    chunk.router,
    contract.router,
    llm_config.router,
    agent.router,
    chat_upload.router,
    conversation.router,
    dashboard.router,
    retrieval.router,
    metrics_router,
    harness_monitor_router,
]

__all__ = ["routers"]
