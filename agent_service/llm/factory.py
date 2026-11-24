"""本文件提供 LLMFactory 注册表，用统一入口创建不同 provider 的大模型客户端。"""

from __future__ import annotations

from typing import Any

from agent_service.llm.base import BaseLLM


class LLMFactory:
    """使用注册表创建 LLM 实例，新增 provider 时只需 register。"""

    _registry: dict[str, type[BaseLLM]] = {}

    @classmethod
    def register(cls, provider: str, llm_cls: type[BaseLLM]) -> None:
        """注册一个 provider 名称和它对应的 LLM 实现类。"""
        cls._registry[provider.lower()] = llm_cls

    @classmethod
    def create(
        cls,
        provider: str,
        model_name: str,
        api_base: str | None = None,
        api_key: str | None = None,
        **kwargs: Any,
    ) -> BaseLLM:
        """根据 provider 构造大模型客户端。"""
        llm_cls = cls._registry.get(provider.lower())
        if llm_cls is None:
            raise ValueError(f"未知的 LLM provider: {provider}. 已注册: {list(cls._registry)}")
        return llm_cls(
            model_name=model_name,
            api_base=api_base,
            api_key=api_key,
            **kwargs,
        )

    @classmethod
    def providers(cls) -> list[str]:
        """返回当前已注册的 provider 名称。"""
        return sorted(cls._registry)
