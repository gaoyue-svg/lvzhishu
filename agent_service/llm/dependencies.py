"""本文件提供 FastAPI 获取当前用户 LLM 客户端的依赖函数（BYOK，按用户配置创建）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from agent_service.llm import BaseLLM
from agent_service.llm.byok import load_user_llm
from backend.database import get_db
from backend.models.user import User
from backend.services.auth import get_current_user


async def get_llm(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> BaseLLM:
    """按当前用户配置构造 LLM；未配置且允许时回退到全局兜底模型。"""
    llm = await load_user_llm(db, current_user.id)
    if llm is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先配置模型")
    return llm


LLMDep = Annotated[BaseLLM, Depends(get_llm)]

__all__ = ["LLMDep", "get_llm"]
