"""本文件实现按用户加载 BYOK LLM，并在允许时回退到全局兜底模型。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from agent_service.llm import BaseLLM
from agent_service.llm.factory import LLMFactory
from agent_service.llm.registry import get_or_create
from backend.config import settings
from backend.services.llm_config import get_active_config

_global_llm: BaseLLM | None = None


async def load_user_llm(db: AsyncSession, user_id: int) -> BaseLLM | None:
    """按 user_id 加载 LLM；用户未配置时根据开关返回全局兜底 LLM。"""
    if settings.byok_enabled:
        config = await get_active_config(db, user_id)
        if config is not None:
            return await get_or_create(config)
    if settings.byok_fallback_to_global:
        return get_global_llm()
    return None


def get_global_llm() -> BaseLLM:
    """创建或复用 `.env` 中配置的全局兜底 LLM。"""
    global _global_llm
    if _global_llm is None:
        _global_llm = LLMFactory.create(
            provider=settings.llm_provider,
            model_name=settings.llm_model,
            api_base=settings.llm_api_base or None,
            api_key=settings.llm_api_key or None,
            default_temperature=settings.llm_temperature,
            default_max_tokens=settings.llm_max_tokens,
            timeout=settings.llm_timeout,
            retry=settings.llm_retry,
        )
    return _global_llm
