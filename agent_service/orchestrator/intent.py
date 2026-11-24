"""本文件实现意图识别层（doc 19 §4.1）：规则兜底 + LLM 增强，注入记忆。

原则：规则命中率高（明确法条定位/合同审查/案例分析）时直接产出 intent，不调 LLM；
规则不确定时 LLM 一次结构化输出。必须注入 query + history_summary + legal_memory +
uploaded_files + available_kbs（修复 doc 19 D3/D4 上下文退化）。
"""

from __future__ import annotations

import asyncio
from typing import Any

from agent_service.agents.registry import get_registry
from agent_service.llm.usage import usage_purpose
from agent_service.prompts import get_prompt
from agent_service.router.fallback import (
    _is_high_risk,
    infer_legal_context,
    infer_retrieval_scope,
    infer_sub_questions,
    infer_time_context,
)
from agent_service.router.models import RouterInput
from agent_service.router.rules import generate_candidates
from backend.config import settings
from backend.utils.logger import get_logger

logger = get_logger(__name__)

INTENT_SYSTEM = get_prompt("intent_system")

# 意图命中率足够高、无需 LLM 增强的规则分数阈值
_RULE_CONFIDENT_SCORE = 0.7


class IntentLayer:
    """规则预筛 + LLM 结构化输出，产出 v2 链路第一步的 intent。"""

    def __init__(
        self,
        llm: Any,
        *,
        candidates_fn: Any | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: int | None = None,
        retry: int | None = None,
    ) -> None:
        """注入 LLM 与规则候选生成器；temperature 等沿用 Supervisor 同级配置。"""
        self.llm = llm
        self.candidates_fn = candidates_fn or generate_candidates
        self.registry = get_registry()
        self.temperature = temperature if temperature is not None else settings.supervisor_llm_temperature
        self.max_tokens = max_tokens if max_tokens is not None else settings.planner_llm_max_tokens
        self.timeout = timeout if timeout is not None else settings.planner_llm_timeout
        self.retry = retry if retry is not None else settings.planner_llm_retry

    async def analyze(self, shared_state: dict[str, Any]) -> dict[str, Any]:
        """识别用户问题意图，返回结构化 intent。"""
        query = str(shared_state.get("query") or "").strip()
        router_input = self._build_router_input(shared_state)
        candidates = self.candidates_fn(router_input)
        entry_hint = next((c.agent for c in candidates if c.agent), "law_qa")

        # 规则确定性预筛：优先复用 fallback 的 guardrails
        scope = infer_retrieval_scope(query)
        legal_context = infer_legal_context(query, scope.category)
        time_context = infer_time_context(query)
        sub_questions = infer_sub_questions(query, entry_hint)
        high_risk = _is_high_risk(query)

        intent: dict[str, Any] = {
            "entry_hint": entry_hint,
            "domain": scope.domain,
            "category": scope.category,
            "risk_level": "high" if high_risk else _default_risk_level(entry_hint),
            "needs_files": entry_hint == "contract_review",
            "needs_web": entry_hint == "case_analysis",
            "legal_context": legal_context.model_dump(mode="json"),
            "retrieval_scope": scope.model_dump(mode="json"),
            "sub_questions": sub_questions,
            "time_context": time_context.model_dump(mode="json"),
            "history_summary": shared_state.get("history_summary") or "",
            "uploaded_files": shared_state.get("uploaded_files") or [],
            "available_kbs": shared_state.get("available_kbs") or [],
            "rule_confident": _rules_confident(candidates),
        }

        # 规则命中率高：直接产出，不调 LLM
        if intent["rule_confident"]:
            logger.info("[Intent] 规则命中直出 intent entry_hint=%s", entry_hint)
            return intent

        # 规则不确定：LLM 一次结构化输出
        llm_intent = await self._llm_enhance(shared_state, router_input, candidates, intent)
        if llm_intent:
            return llm_intent
        return intent

    async def _llm_enhance(
        self,
        shared_state: dict[str, Any],
        router_input: RouterInput,
        candidates: list[Any],
        rule_intent: dict[str, Any],
    ) -> dict[str, Any] | None:
        """LLM 增强意图识别；失败返回 None 由上层用规则 intent 兜底。"""
        from agent_service.prompts import build_user_prompt

        # 复用 Router 用户上下文 prompt，注入记忆与文件
        user_prompt = build_user_prompt(router_input, candidates)
        user_prompt += (
            "\n\n【Agent 候选卡片】\n"
            + self.registry.agent_blocks()
            + "\n\n请只输出 Intent JSON：{entry_hint, domain, category, risk_level, needs_files, "
            "needs_web, legal_context, retrieval_scope, sub_questions, time_context}，不要输出计划。"
        )
        for attempt in range(self.retry + 1):
            try:
                with usage_purpose("intent"):
                    payload = await asyncio.wait_for(
                        self.llm.chat_json(
                            INTENT_SYSTEM,
                            user_prompt,
                            temperature=self.temperature,
                            max_tokens=self.max_tokens,
                        ),
                        timeout=self.timeout,
                    )
                return _merge_intent(payload, rule_intent)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[Intent] LLM 增强失败 (attempt=%d): %s", attempt + 1, exc.__class__.__name__)
                if attempt < self.retry:
                    await asyncio.sleep(min(2**attempt, 2))
        return None

    def _build_router_input(self, shared_state: dict[str, Any]) -> RouterInput:
        """从 SharedState 构造 RouterInput，注入记忆/文件/知识库上下文。"""
        return RouterInput(
            user_query=str(shared_state.get("query") or ""),
            conversation_id=str(shared_state.get("conversation_id") or ""),
            user_id=str(shared_state.get("user_id") or ""),
            tenant_id=str(shared_state.get("tenant_id") or ""),
            history_summary=shared_state.get("history_summary"),
            legal_memory=shared_state.get("legal_memory"),
            uploaded_files=shared_state.get("uploaded_files") or [],
            available_kbs=shared_state.get("available_kbs") or [],
        )


def _rules_confident(candidates: list[Any]) -> bool:
    """规则候选最高分达到阈值即认为命中率高。"""
    best = next((c for c in candidates if c.agent), None)
    return best is not None and float(best.score) >= _RULE_CONFIDENT_SCORE


def _default_risk_level(agent: str) -> str:
    """按 Agent 给出默认风险等级，与 fallback.AGENT_DEFAULTS 对齐。"""
    return {
        "contract_review": "medium",
        "case_analysis": "medium",
        "article_locate": "low",
        "law_qa": "low",
    }.get(agent, "low")


def _merge_intent(payload: dict[str, Any], rule_intent: dict[str, Any]) -> dict[str, Any]:
    """LLM 输出与规则 intent 合并，规则字段缺失时回退，修复字段类型。"""
    merged = dict(rule_intent)
    for key in (
        "entry_hint",
        "domain",
        "category",
        "risk_level",
        "needs_files",
        "needs_web",
        "legal_context",
        "retrieval_scope",
        "sub_questions",
        "time_context",
    ):
        value = payload.get(key)
        if value not in (None, "", {}):
            merged[key] = value
    # entry_hint 必须落在注册表内
    registry = get_registry()
    if merged.get("entry_hint") not in registry.keys():
        merged["entry_hint"] = rule_intent.get("entry_hint") or "law_qa"
    merged["rule_confident"] = False
    return merged
