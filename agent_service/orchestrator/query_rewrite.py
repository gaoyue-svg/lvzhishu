"""本文件实现编排层查询改写（QueryRewriteLayer）：用户提问后、意图识别前规范化 query。

原则：规则优先（纠错别字 + 口语转法律术语），LLM 增强默认关闭（省成本），
LLM 失败回退规则结果。改写后覆盖 shared_state["query"]，原文存 original_query，
下游 intent / planner / executor / synthesizer 全部自动读到改写结果
（默认计划步 inputs={"query": "$user.query"} 引用共享状态，无需逐个改动）。
"""

from __future__ import annotations

import asyncio
from typing import Any

from agent_service.llm.usage import usage_purpose
from agent_service.prompts import get_prompt
from backend.config import settings
from backend.utils.logger import get_logger
from rag_service.retrieval.query_rewrite import RuleQueryRewriter

logger = get_logger(__name__)

REWRITE_SYSTEM = get_prompt("query_rewrite_system")

# 常见法律错别字表：key 为用户输入的错误写法，value 为规范写法。
# 与 RuleQueryRewriter.DEFAULT_SYNONYMS（口语→法律术语）合并为统一替换表。
TYPO_MAP: dict[str, str] = {
    "案列": "案例",
    "仲载": "仲裁",
    "违约今": "违约金",
    "拖久": "拖欠",
    "劳动合通": "劳动合同",
    "民典法": "民法典",
    "刑发": "刑法",
    "合同解组": "合同解除",
    "侵权培偿": "侵权赔偿",
    "消废者": "消费者",
    "工伤认订": "工伤认定",
    "上诉其": "上诉期",
}


class QueryRewriteLayer:
    """规则优先 + LLM 增强的查询改写层，产出规范化 query 并写回共享状态。"""

    def __init__(
        self,
        llm: Any,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        retry: int | None = None,
        enabled: bool | None = None,
        llm_enabled: bool | None = None,
    ) -> None:
        """注入 LLM 与容错参数；enabled/llm_enabled 缺省取配置，便于测试显式覆盖。"""
        self.llm = llm
        self.temperature = temperature if temperature is not None else settings.query_rewrite_llm_temperature
        self.max_tokens = max_tokens if max_tokens is not None else settings.query_rewrite_llm_max_tokens
        self.timeout = timeout if timeout is not None else settings.query_rewrite_llm_timeout
        self.retry = retry if retry is not None else settings.query_rewrite_llm_retry
        self.enabled = settings.query_rewrite_enabled if enabled is None else enabled
        self.llm_enabled = settings.query_rewrite_llm_enabled if llm_enabled is None else llm_enabled
        # 替换表：先口语→法律术语，再错别字覆盖（错别字 key 通常与口语 key 不重叠）
        self.rewrite_map: dict[str, str] = {**RuleQueryRewriter.DEFAULT_SYNONYMS, **TYPO_MAP}

    async def rewrite(self, shared_state: dict[str, Any]) -> dict[str, Any]:
        """改写共享状态里的 query，返回改写元信息（供 SSE 事件）。"""
        original = str(shared_state.get("query") or "").strip()
        if not original or not self.enabled:
            return {}

        rule_rewritten = self._rule_rewrite(original)
        final = rule_rewritten
        method = "rules" if rule_rewritten != original else "none"

        if self.llm_enabled:
            llm_rewritten = await self._llm_rewrite(original)
            if llm_rewritten:
                final = llm_rewritten
                method = "llm"

        meta: dict[str, Any] = {
            "original_query": original,
            "rewritten_query": final,
            "method": method,
            "notes": "",
        }
        # 原文只写一次（会话入口已把 body.query 落库/标题，此处保留副本便于下游需要时回退）
        if shared_state.get("original_query") is None:
            shared_state["original_query"] = original
        shared_state["query"] = final
        shared_state["rewrite_meta"] = meta
        if final != original:
            logger.info("[QueryRewrite] method=%s %r -> %r", method, original, final)
        return meta

    def _rule_rewrite(self, query: str) -> str:
        """对命中的错别字/口语表达做字符串替换，得到规范法律表达。"""
        rewritten = query
        for key, value in self.rewrite_map.items():
            if key in rewritten:
                rewritten = rewritten.replace(key, value)
        return rewritten

    async def _llm_rewrite(self, original: str) -> str | None:
        """LLM 一次结构化改写；失败或字段异常返回 None，由上层用规则结果兜底。"""
        for attempt in range(self.retry + 1):
            try:
                with usage_purpose("rewrite"):
                    payload = await asyncio.wait_for(
                        self.llm.chat_json(
                            REWRITE_SYSTEM,
                            original,
                            temperature=self.temperature,
                            max_tokens=self.max_tokens,
                        ),
                        timeout=self.timeout,
                    )
                rewritten = str((payload or {}).get("rewritten_query") or "").strip()
                return rewritten if rewritten else None
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[QueryRewrite] LLM 改写失败 (attempt=%d): %s", attempt + 1, exc.__class__.__name__
                )
                if attempt < self.retry:
                    await asyncio.sleep(min(2**attempt, 2))
        return None
