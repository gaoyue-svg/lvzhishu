"""本文件实现合成层（doc 19 §4.5）：跨 Agent 引用合并 + LLM 流式重写最终答案。

- 复用 citation_merge.merge_citations 做去重 + 全局重编号；
- 传给合成器的 context_text 按 synth_context_max_tokens 截断，控制 token 膨胀（D6）；
- LLM 失败时用最后一个 Agent 答案做 L3 兜底，且兜底答案也统一重编号（D1）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Callable

from agent_service.agents.citation_merge import (
    merge_citations,
    renumber_answer_text,
    sanitize_citation_references,
)
from agent_service.llm.usage import usage_purpose
from agent_service.prompts import build_synthesizer_user_prompt, get_prompt
from backend.config import settings
from backend.utils.logger import get_logger

logger = get_logger(__name__)


class Synthesizer:
    """跨 Agent 引用合并 + LLM 流式重写最终答案。"""

    def __init__(
        self,
        llm: Any,
        *,
        context_max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> None:
        """注入 LLM；context_max_tokens 默认取配置 synth_context_max_tokens。"""
        self.llm = llm
        self.context_max_tokens = context_max_tokens if context_max_tokens is not None else settings.synth_context_max_tokens
        self.temperature = temperature if temperature is not None else settings.synthesizer_temperature

    async def synthesize(
        self,
        query: str,
        agent_results: list[dict[str, Any]],
        *,
        on_token: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        """合并引用并流式重写最终答案。

        Returns:
            {answer, citations, merged_citations, renumber_map}
        """
        merged, renumber_map = merge_citations(agent_results)

        # 无产出兜底
        if not agent_results:
            answer = "（未能生成答案，请重试）"
            if on_token:
                on_token(answer)
            return {"answer": answer, "citations": merged, "merged_citations": merged, "renumber_map": renumber_map}

        user_prompt = build_synthesizer_user_prompt(
            query=query,
            agent_results=agent_results,
            merged_citations=merged,
            renumber_map=renumber_map,
            context_max_tokens=self.context_max_tokens,
        )
        # 调用时解析 system prompt，支持 A/B 实验按请求切换版本（doc 21 Phase 3）
        messages = [
            {"role": "system", "content": get_prompt("synthesizer_system")},
            {"role": "user", "content": user_prompt},
        ]

        parts: list[str] = []
        try:
            with usage_purpose("synthesize"):
                async for piece in self.llm.stream(
                    messages,
                    temperature=self.temperature,
                    max_tokens=settings.llm_max_tokens,
                ):
                    parts.append(piece)
            answer = "".join(parts)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Synthesizer LLM 失败，用最后 Agent 答案兜底: %s", exc.__class__.__name__)
            last = agent_results[-1]
            # L3 兜底：同样走 renumber_answer_text，避免引用编号错位（D1）
            answer = renumber_answer_text(last.get("answer") or "（生成失败，请重试）", last.get("agent") or "", renumber_map)

        # LLM 有时会把 prompt 中的 [1][2] 格式示例误当成可用来源。先依据真实
        # citations 清除悬空编号，再向前端发送，保证流式正文与最终事件一致。
        answer = sanitize_citation_references(answer, merged)
        if on_token:
            on_token(answer)

        return {
            "answer": answer,
            "citations": merged,
            "merged_citations": merged,
            "renumber_map": renumber_map,
        }
