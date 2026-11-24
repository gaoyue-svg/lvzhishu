"""本文件提供按 config_id 缓存的 LLM 实例池，避免每次请求重复创建 HTTP 客户端。"""

from __future__ import annotations

from typing import Any

from agent_service.llm.base import BaseLLM
from agent_service.llm.factory import LLMFactory
from backend.config import settings
from backend.utils.crypto import decrypt
from backend.utils.logger import get_logger

logger = get_logger(__name__)

# 按 config_id 缓存的 LLM 实例；配置更新时通过 invalidate 清除。
_cache: dict[int, BaseLLM] = {}


async def get_or_create(config: Any) -> BaseLLM:
    """按 config_id 取缓存实例；不存在则解密 Key 并创建，写回缓存。"""
    config_id = config.id
    cached = _cache.get(config_id)
    if cached is not None:
        return cached

    api_key = decrypt(config.api_key_encrypted)
    llm = LLMFactory.create(
        provider=config.provider,
        model_name=config.model_name,
        api_base=config.api_base or None,
        api_key=api_key,
        # 用户未填的可选项回退到系统默认，避免 None 传入 provider 构造函数
        default_temperature=config.temperature if config.temperature is not None else settings.llm_temperature,
        default_max_tokens=config.max_tokens if config.max_tokens is not None else settings.llm_max_tokens,
        timeout=config.timeout if config.timeout is not None else settings.llm_timeout,
        retry=config.retry if config.retry is not None else settings.llm_retry,
    )
    _cache[config_id] = llm
    logger.info("LLM 实例已创建并缓存: config_id=%s provider=%s model=%s", config_id, config.provider, config.model_name)
    return llm


def invalidate(config_id: int) -> None:
    """配置更新或删除时清除对应缓存，下次请求会重建实例。"""
    if _cache.pop(config_id, None) is not None:
        logger.info("LLM 实例缓存已失效: config_id=%s", config_id)


def clear() -> None:
    """清空全部缓存，用于测试隔离。"""
    _cache.clear()
