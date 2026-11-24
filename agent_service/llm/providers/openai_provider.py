"""本文件实现遵循 OpenAI Chat Completions 协议的大模型 provider。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Coroutine, Sequence
from time import perf_counter
from typing import Any

from agent_service.llm.base import BaseLLM, LLMMessageLike, LLMToolCall, LLMToolResult, normalize_messages
from agent_service.llm.usage import record_usage
from backend.utils.logger import get_logger
from backend.utils.tokenizer import count_tokens

logger = get_logger(__name__)


class OpenAICompatibleLLM(BaseLLM):
    """封装 OpenAI 兼容协议，DeepSeek、Qwen 等 provider 可复用。"""

    DEFAULT_API_BASE: str | None = None

    def __init__(
        self,
        model_name: str,
        api_base: str | None = None,
        api_key: str | None = None,
        *,
        default_temperature: float = 0.3,
        default_max_tokens: int = 4096,
        timeout: float = 60.0,
        retry: int = 2,
        client: Any | None = None,
    ) -> None:
        """初始化 OpenAI 兼容异步客户端。"""
        self._model_name = model_name
        self.default_temperature = default_temperature
        self.default_max_tokens = default_max_tokens
        self.retry = max(retry, 0)
        if client is not None:
            self.client = client
            return

        from openai import AsyncOpenAI

        kwargs: dict[str, Any] = {"api_key": api_key or "not-configured", "timeout": timeout}
        effective_api_base = api_base or self.DEFAULT_API_BASE
        if effective_api_base:
            kwargs["base_url"] = effective_api_base
        self.client = AsyncOpenAI(**kwargs)

    @property
    def model_name(self) -> str:
        """返回当前模型名称。"""
        return self._model_name

    @property
    def supports_tool_call(self) -> bool:
        """OpenAI 兼容 chat completions 协议默认支持工具调用。"""
        return True

    @property
    def provider_name(self) -> str:
        """返回提供方标识（deepseek/openai/qwen），供用量采集使用。"""
        name = type(self).__name__
        if name == "DeepSeekLLM":
            return "deepseek"
        if name == "QwenLLM":
            return "qwen"
        return "openai"

    async def chat(self, messages: Sequence[LLMMessageLike], **kwargs: Any) -> str:
        """执行非流式对话，返回 assistant 文本内容。"""
        started = perf_counter()
        response = await self._request_with_retry(
            lambda: self.client.chat.completions.create(
                **self._build_params(messages, stream=False, **kwargs)
            )
        )
        message = _first_choice_message(response)
        content = str(_get(message, "content", "") or "")
        usage = _get(response, "usage", None)
        record_usage(
            provider=self.provider_name,
            model=self.model_name,
            prompt_tokens=_get(usage, "prompt_tokens", 0),
            completion_tokens=_get(usage, "completion_tokens", 0),
            latency_ms=int((perf_counter() - started) * 1000),
        )
        return content

    async def stream(self, messages: Sequence[LLMMessageLike], **kwargs: Any) -> AsyncIterator[str]:
        """执行流式对话；一旦已有输出，后续异常交给调用方处理。"""
        yielded = False
        pieces: list[str] = []
        started = perf_counter()
        last_error: Exception | None = None
        for attempt in range(self.retry + 1):
            try:
                stream = await self.client.chat.completions.create(
                    **self._build_params(messages, stream=True, **kwargs)
                )
                async for chunk in stream:
                    delta = _first_choice_delta(chunk)
                    piece = _get(delta, "content", None)
                    if piece:
                        pieces.append(str(piece))
                        yielded = True
                        yield str(piece)
                break
            except Exception as exc:
                last_error = exc
                if yielded or attempt >= self.retry:
                    break
                await asyncio.sleep(min(2**attempt, 4))
        # 流式拿不到真实 usage，用 tiktoken 估算（best-effort）
        try:
            prompt_text = "\n".join(
                message.get("content", "") if isinstance(message, dict) else getattr(message, "content", "")
                for message in messages
            )
            record_usage(
                provider=self.provider_name,
                model=self.model_name,
                prompt_tokens=count_tokens(prompt_text, self.model_name),
                completion_tokens=count_tokens("".join(pieces), self.model_name),
                latency_ms=int((perf_counter() - started) * 1000),
            )
        except Exception:  # noqa: BLE001
            logger.warning("流式 LLM 用量估算失败，已忽略", exc_info=True)
        if last_error is not None:
            raise last_error

    async def chat_with_tools(
        self,
        messages: Sequence[LLMMessageLike],
        tools: list[dict[str, Any]],
        **kwargs: Any,
    ) -> LLMToolResult:
        """执行带 tools 的对话，并标准化 tool_calls。"""
        kwargs.setdefault("tool_choice", "auto")
        started = perf_counter()
        response = await self._request_with_retry(
            lambda: self.client.chat.completions.create(
                **self._build_params(messages, stream=False, tools=tools, **kwargs)
            )
        )
        message = _first_choice_message(response)
        usage = _get(response, "usage", None)
        record_usage(
            provider=self.provider_name,
            model=self.model_name,
            prompt_tokens=_get(usage, "prompt_tokens", 0),
            completion_tokens=_get(usage, "completion_tokens", 0),
            latency_ms=int((perf_counter() - started) * 1000),
        )
        return LLMToolResult(
            content=_get(message, "content", None),
            tool_calls=_parse_tool_calls(_get(message, "tool_calls", []) or []),
        )

    def _build_params(self, messages: Sequence[LLMMessageLike], *, stream: bool, **kwargs: Any) -> dict[str, Any]:
        """构造 Chat Completions 请求参数。"""
        params = {
            "model": self.model_name,
            "messages": normalize_messages(messages),
            "temperature": kwargs.pop("temperature", self.default_temperature),
            "max_tokens": kwargs.pop("max_tokens", self.default_max_tokens),
            "stream": stream,
        }
        params.update({key: value for key, value in kwargs.items() if value is not None})
        return params

    async def _request_with_retry(
        self,
        operation: Callable[[], Coroutine[Any, Any, Any]],
    ) -> Any:
        """对非流式请求执行指数退避重试。"""
        last_error: Exception | None = None
        for attempt in range(self.retry + 1):
            try:
                return await operation()
            except Exception as exc:
                last_error = exc
                if attempt >= self.retry:
                    break
                await asyncio.sleep(min(2**attempt, 4))
        assert last_error is not None
        raise last_error


class OpenAILLM(OpenAICompatibleLLM):
    """OpenAI 官方 Chat Completions 服务实现。"""


class DeepSeekLLM(OpenAICompatibleLLM):
    """DeepSeek OpenAI 兼容服务实现。

    DeepSeek 专属参数在此封装（doc 19 D7）：默认关闭思考模式，
    避免 reasoning_content 吃光 max_tokens 预算导致 content 返回空字符串。
    业务代码不得出现 thinking 等 provider 专属参数。
    """

    DEFAULT_API_BASE = "https://api.deepseek.com/v1"

    def _build_params(self, messages: Sequence[LLMMessageLike], *, stream: bool, **kwargs: Any) -> dict[str, Any]:
        """DeepSeek 专属参数下沉：无显式 extra_body 时默认关闭思考模式。"""
        extra_body = dict(kwargs.pop("extra_body", None) or {})
        extra_body.setdefault("thinking", {"type": "disabled"})
        kwargs["extra_body"] = extra_body
        return super()._build_params(messages, stream=stream, **kwargs)


class QwenLLM(OpenAICompatibleLLM):
    """通义千问 OpenAI 兼容服务实现。"""

    DEFAULT_API_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def _get(value: Any, key: str, default: Any = None) -> Any:
    """兼容 dict 和 SDK 对象的字段读取。"""
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _first_choice_message(response: Any) -> Any:
    """读取 Chat Completions 第一个 choice 的 message。"""
    choices = _get(response, "choices", []) or []
    if not choices:
        return {}
    return _get(choices[0], "message", {})


def _first_choice_delta(chunk: Any) -> Any:
    """读取流式 chunk 第一个 choice 的 delta。"""
    choices = _get(chunk, "choices", []) or []
    if not choices:
        return {}
    return _get(choices[0], "delta", {})


def _parse_tool_calls(raw_calls: Sequence[Any]) -> list[LLMToolCall]:
    """把 provider 返回的 tool_calls 统一成 LLMToolCall。"""
    parsed: list[LLMToolCall] = []
    for index, raw_call in enumerate(raw_calls):
        function = _get(raw_call, "function", {}) or {}
        name = str(_get(function, "name", "") or "")
        if not name:
            continue
        raw_args = _get(function, "arguments", "{}") or "{}"
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
        except (TypeError, ValueError):
            args = {"_raw": str(raw_args)}
        parsed.append(
            LLMToolCall(
                id=str(_get(raw_call, "id", "") or f"tool_call_{index}"),
                name=name,
                args=args,
            )
        )
    return parsed
