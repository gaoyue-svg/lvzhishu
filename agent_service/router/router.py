"""本文件实现 RouterAgent 主入口，编排记忆恢复、规则候选、LLM 判别和兜底校验。"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from agent_service.llm.usage import usage_purpose
from agent_service.router.fallback import apply_guardrails, fallback_from_candidates
from agent_service.router.models import LegalMemory, RouterDecision, RouterInput
from agent_service.prompts import build_user_prompt, get_prompt
from agent_service.router.rules import generate_candidates
from backend.config import settings
from backend.utils.logger import get_logger

# Router 系统提示词从 md 加载，启动时取一次作为常量
SYSTEM_PROMPT = get_prompt("router_system")

logger = get_logger(__name__)

AvailableKbsLoader = Callable[[str], Awaitable[list[dict[str, Any]]] | list[dict[str, Any]]]


class RouterAgent:
    """编排层路由器，只输出 RouterDecision，不检索、不生成答案、不执行工具。"""

    def __init__(
        self,
        llm: Any | None = None,
        memory: Any | None = None,
        available_kbs_loader: AvailableKbsLoader | None = None,
        trace_recorder: Any | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: int | None = None,
        retry: int | None = None,
        confidence_threshold: float | None = None,
        confidence_max: float | None = None,
    ) -> None:
        """注入 LLM、Memory、知识库加载器和可选 Trace 记录器。"""
        self.llm = llm
        self.memory = memory
        self.available_kbs_loader = available_kbs_loader
        self.trace_recorder = trace_recorder
        self.temperature = temperature if temperature is not None else settings.router_llm_temperature
        self.max_tokens = max_tokens if max_tokens is not None else settings.router_llm_max_tokens
        self.timeout = timeout if timeout is not None else settings.router_llm_timeout
        self.retry = retry if retry is not None else settings.router_llm_retry
        self.confidence_threshold = (
            confidence_threshold if confidence_threshold is not None else settings.router_confidence_threshold
        )
        self.confidence_max = confidence_max if confidence_max is not None else settings.router_confidence_max

    async def route(self, router_input: RouterInput, llm: Any | None = None) -> RouterDecision:
        """执行 Router 四步流程并返回稳定的 RouterDecision。llm 运行时注入，未传则回退到实例默认。"""
        started = perf_counter()
        logger.info(
            "[Router] 开始路由 query=%r conversation_id=%s",
            router_input.user_query,
            router_input.conversation_id,
        )
        hydrated_input = await self._hydrate_context(router_input)
        candidates = generate_candidates(hydrated_input)
        logger.info(
            "[Router] 规则候选 agents=%s",
            [c.agent for c in candidates],
        )
        effective_llm = llm if llm is not None else self.llm
        llm_called = effective_llm is not None
        llm_raw_output: Any = None
        llm_latency_ms = 0

        if effective_llm is None:
            logger.info("[Router] LLM 未配置，使用规则候选兜底")
            decision = fallback_from_candidates(hydrated_input, candidates, reason="LLM 未配置，使用规则候选兜底")
        else:
            llm_started = perf_counter()
            try:
                logger.info("[Router] 调用 LLM 进行判别")
                llm_raw_output = await self._call_llm_with_retry(hydrated_input, candidates, effective_llm)
                llm_latency_ms = int((perf_counter() - llm_started) * 1000)
                logger.info(
                    "[Router] LLM 判别完成 latency_ms=%s raw=%s",
                    llm_latency_ms,
                    _truncate_for_log(llm_raw_output),
                )
                decision = RouterDecision.model_validate(_coerce_json_payload(llm_raw_output))
                decision = apply_guardrails(
                    decision,
                    hydrated_input,
                    confidence_threshold=self.confidence_threshold,
                    confidence_max=self.confidence_max,
                )
            except (TimeoutError, ValueError, ValidationError, RuntimeError) as exc:
                llm_latency_ms = int((perf_counter() - llm_started) * 1000)
                logger.warning(
                    "[Router] LLM 判别失败，进入兜底 latency_ms=%s exc=%s",
                    llm_latency_ms,
                    exc.__class__.__name__,
                )
                decision = fallback_from_candidates(
                    hydrated_input,
                    candidates,
                    reason=f"LLM 判别失败，使用规则候选兜底",
                )

        total_latency_ms = int((perf_counter() - started) * 1000)
        logger.info(
            "[Router] 路由完成 agent=%s confidence=%s need_retrieval=%s risk_level=%s fallback=%s reason=%s total_latency_ms=%s",
            decision.agent,
            decision.confidence,
            decision.need_retrieval,
            decision.risk_level,
            decision.fallback,
            decision.route_reason,
            total_latency_ms,
        )
        await self._record_trace(
            hydrated_input,
            candidates,
            decision,
            llm_called=llm_called,
            llm_raw_output=llm_raw_output,
            llm_latency_ms=llm_latency_ms,
            total_latency_ms=total_latency_ms,
        )
        return decision

    async def _hydrate_context(self, router_input: RouterInput) -> RouterInput:
        """从 Memory 和知识库加载器补齐 RouterInput 的上下文。"""
        data = router_input.model_dump()
        if self.memory is not None and router_input.conversation_id:
            if router_input.legal_memory is None and hasattr(self.memory, "load"):
                loaded_memory = await _maybe_await(self.memory.load(router_input.conversation_id))
                data["legal_memory"] = _normalize_legal_memory(loaded_memory)
            if not router_input.history_summary and hasattr(self.memory, "load_summary"):
                data["history_summary"] = await _maybe_await(self.memory.load_summary(router_input.conversation_id))
            if not router_input.uploaded_files and hasattr(self.memory, "load_files"):
                data["uploaded_files"] = await _maybe_await(self.memory.load_files(router_input.conversation_id)) or []
        if not router_input.available_kbs and self.available_kbs_loader is not None:
            data["available_kbs"] = await _maybe_await(self.available_kbs_loader(router_input.tenant_id)) or []
        return RouterInput.model_validate(data)

    async def _call_llm_with_retry(self, router_input: RouterInput, candidates: list[Any], llm: Any) -> Any:
        """按配置重试 Router LLM 调用，仍失败则交给上层兜底。"""
        last_exc: Exception | None = None
        for attempt in range(self.retry + 1):
            try:
                return await asyncio.wait_for(self._call_llm(router_input, candidates, llm), timeout=self.timeout)
            except Exception as exc:
                last_exc = exc
                if attempt < self.retry:
                    await asyncio.sleep(min(2**attempt, 2))
        raise RuntimeError("Router LLM 调用失败") from last_exc

    async def _call_llm(self, router_input: RouterInput, candidates: list[Any], llm: Any) -> Any:
        """兼容项目内不同 LLM 抽象，统一取得 JSON 决策结果。"""
        user_prompt = build_user_prompt(router_input, candidates)
        params = {
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }
        # 关键兼容点：适配常见 chat_json/route/ainvoke 接口，llm 由调用方运行时注入。
        with usage_purpose("router"):
            if hasattr(llm, "chat_json"):
                return await _maybe_await(llm.chat_json(SYSTEM_PROMPT, user_prompt, **params))
            if hasattr(llm, "route"):
                return await _maybe_await(llm.route(router_input, candidates))
            if hasattr(llm, "ainvoke"):
                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ]
                return await _maybe_await(llm.ainvoke(messages, **params))
            if callable(llm):
                return await _maybe_await(llm(SYSTEM_PROMPT, user_prompt, **params))
            raise RuntimeError("未识别的 LLM 接口")

    async def _record_trace(
        self,
        router_input: RouterInput,
        candidates: list[Any],
        decision: RouterDecision,
        *,
        llm_called: bool,
        llm_raw_output: Any,
        llm_latency_ms: int,
        total_latency_ms: int,
    ) -> None:
        """把 Router 可观测信息交给外部记录器，失败不影响决策返回。"""
        if self.trace_recorder is None or not hasattr(self.trace_recorder, "record"):
            return
        trace = {
            "trace_id": uuid4().hex,
            "router_input": router_input,
            "rule_candidates": [candidate.model_dump(mode="json") for candidate in candidates],
            "llm_called": llm_called,
            "llm_raw_output": _safe_jsonable(llm_raw_output),
            "llm_latency_ms": llm_latency_ms,
            "final_decision": decision,
            "total_latency_ms": total_latency_ms,
        }
        try:
            await _maybe_await(self.trace_recorder.record(trace))
        except Exception as exc:
            logger.warning("Router Trace 记录器执行失败: %s", exc.__class__.__name__)


async def _maybe_await(value: Any) -> Any:
    """兼容同步和异步依赖返回值。"""
    if inspect.isawaitable(value):
        return await value
    return value


def _coerce_json_payload(raw: Any) -> dict[str, Any]:
    """把 LLM 返回值转换为可校验的 JSON 字典。"""
    if isinstance(raw, RouterDecision):
        return raw.model_dump()
    if isinstance(raw, dict):
        return raw
    content = getattr(raw, "content", raw)
    if isinstance(content, bytes):
        content = content.decode("utf-8")
    if not isinstance(content, str):
        raise ValueError("LLM 输出不是 JSON 字符串或字典")
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("LLM 输出 JSON 解析失败") from exc
    if not isinstance(payload, dict):
        raise ValueError("LLM 输出 JSON 顶层不是对象")
    return payload


def _normalize_legal_memory(value: Any) -> LegalMemory | None:
    """把 Memory 返回值标准化为 LegalMemory。"""
    if value is None or isinstance(value, LegalMemory):
        return value
    if isinstance(value, dict):
        return LegalMemory.model_validate(value)
    return None


def _safe_jsonable(value: Any) -> Any:
    """将 LLM 原始输出压成可写入 JSON 字段的内容。"""
    if isinstance(value, RouterDecision):
        return value.model_dump(mode="json")
    if isinstance(value, (dict, list, str, int, float, bool)) or value is None:
        return value
    return str(value)


def _truncate_for_log(value: Any, limit: int = 300) -> str:
    """把 LLM 原始输出压成单行短字符串，避免控制台被长 JSON 刷屏。"""
    if isinstance(value, RouterDecision):
        text = value.model_dump_json()
    elif isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
    elif isinstance(value, str):
        text = value
    else:
        text = str(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + "...(truncated)"

