"""本文件导出 Agent 服务的大模型抽象、工厂和内置 provider。"""

from agent_service.llm.base import BaseLLM, LLMMessage, LLMToolCall, LLMToolResult
from agent_service.llm.factory import LLMFactory
from agent_service.llm.providers import DeepSeekLLM, OpenAILLM, QwenLLM

LLMFactory.register("openai", OpenAILLM)
LLMFactory.register("deepseek", DeepSeekLLM)
LLMFactory.register("qwen", QwenLLM)

__all__ = [
    "BaseLLM",
    "DeepSeekLLM",
    "LLMFactory",
    "LLMMessage",
    "LLMToolCall",
    "LLMToolResult",
    "OpenAILLM",
    "QwenLLM",
]
