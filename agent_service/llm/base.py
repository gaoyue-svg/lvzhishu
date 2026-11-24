"""本文件定义 Agent 服务共享的大模型抽象、消息结构和标准化工具调用结果。"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.utils.logger import get_logger

logger = get_logger(__name__)


MessageRole = Literal["system", "user", "assistant", "tool"]
LLMMessageLike = "LLMMessage | dict[str, Any]"


class LLMMessage(BaseModel):
    """统一的大模型消息结构，兼容 OpenAI Chat Completions 协议。"""

    role: MessageRole
    content: str
    name: str | None = None
    tool_call_id: str | None = None


class LLMToolCall(BaseModel):
    """标准化后的工具调用描述，屏蔽不同 provider 的字段差异。"""

    id: str
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class LLMToolResult(BaseModel):
    """带工具调用的大模型响应结果。"""

    content: str | None = None
    tool_calls: list[LLMToolCall] = Field(default_factory=list)


class BaseLLM(ABC):
    """LLM 抽象基类，业务 Agent 和 Router 只依赖这一层接口。"""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """返回当前使用的大模型名称。"""

    @property
    @abstractmethod
    def supports_tool_call(self) -> bool:
        """返回当前 provider 是否支持工具调用。"""

    @abstractmethod
    async def chat(self, messages: Sequence[LLMMessageLike], **kwargs: Any) -> str:
        """执行非流式对话，返回模型文本。"""

    @abstractmethod
    async def stream(self, messages: Sequence[LLMMessageLike], **kwargs: Any) -> AsyncIterator[str]:
        """执行流式对话，逐段返回模型文本增量。"""

    @abstractmethod
    async def chat_with_tools(
        self,
        messages: Sequence[LLMMessageLike],
        tools: list[dict[str, Any]],
        **kwargs: Any,
    ) -> LLMToolResult:
        """执行带工具定义的对话，返回标准化内容与工具调用列表。"""

    async def chat_json(
        self,
        system_or_messages: str | Sequence[LLMMessageLike],
        user_prompt: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """执行 JSON 输出对话，并把模型文本解析为字典；解析失败时统一记录 raw 便于排查。"""
        messages = build_messages(system_or_messages, user_prompt)
        kwargs.setdefault("response_format", {"type": "json_object"})
        content = await self.chat(messages, **kwargs)
        try:
            return parse_json_object(content)
        except Exception as exc:
            # 统一在 chat_json 层记录 raw 原文与模型信息，避免业务层散落 raw_text 日志
            logger.error(
                "chat_json 解析失败 model=%s error=%s: %s raw=%r",
                getattr(self, "model_name", "unknown"),
                exc.__class__.__name__,
                exc,
                (content or "")[:500],
            )
            raise

    async def ainvoke(self, messages: Sequence[LLMMessageLike], **kwargs: Any) -> str:
        """兼容 LangChain 风格 ainvoke 接口，便于 Router 和测试复用。"""
        return await self.chat(messages, **kwargs)


def build_messages(
    system_or_messages: str | Sequence[LLMMessageLike],
    user_prompt: str | None = None,
) -> list[LLMMessageLike]:
    """把 Router 的 system/user 双参数或标准 messages 统一为消息列表。"""
    if isinstance(system_or_messages, str):
        if user_prompt is None:
            raise ValueError("user_prompt 不能为空")
        return [
            LLMMessage(role="system", content=system_or_messages),
            LLMMessage(role="user", content=user_prompt),
        ]
    return list(system_or_messages)


def normalize_messages(messages: Sequence[LLMMessageLike]) -> list[dict[str, Any]]:
    """把内部消息对象转成 OpenAI 兼容 API 可接收的字典列表。"""
    normalized: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, LLMMessage):
            normalized.append(message.model_dump(exclude_none=True))
        elif isinstance(message, dict):
            normalized.append({key: value for key, value in message.items() if value is not None})
        else:
            raise TypeError(f"不支持的 LLM message 类型: {type(message)!r}")
    return normalized


def parse_json_object(content: str) -> dict[str, Any]:
    """解析模型 JSON 输出；兼容 Markdown 代码块、带前后缀文字、截断等异常。

    解析顺序：
    1. 去除整段 markdown 代码块包裹（原有逻辑）
    2. json.loads 严格解析（最快路径）
    3. json_repair 兜底：修复缺失括号、引号等，并从带前后缀文本中提取
    4. 正则提取第一个 {...} 块再 json_repair（处理带大量自然语言前缀的情况）
    """
    text = (content or "").strip()
    if not text:
        raise ValueError("LLM JSON 输出为空")

    # 1. 去除整段 markdown 代码块包裹
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()

    # 2. 优先严格 json.loads（最快路径，覆盖大多数正常情况）
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
        raise ValueError("LLM JSON 输出顶层必须是对象")
    except (json.JSONDecodeError, ValueError):
        pass

    # 3. json_repair 兜底：能修复截断/缺括号，也能从混合文本里提取 JSON
    try:
        from json_repair import repair_json

        repaired = repair_json(text, return_objects=True)
        if isinstance(repaired, dict):
            return repaired
    except Exception:  # noqa: BLE001
        pass

    # 4. 正则提取第一个 {...} 块（处理带大量自然语言前缀的情况）再 repair
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        try:
            from json_repair import repair_json

            repaired = repair_json(match.group(0), return_objects=True)
            if isinstance(repaired, dict):
                return repaired
        except Exception:  # noqa: BLE001
            pass

    raise ValueError(f"LLM JSON 输出无法解析: {text[:200]}")
