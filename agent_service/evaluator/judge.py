"""离线 LLM-as-Judge 评审（doc 21 §4.2/Phase 3）：对一次 run 的最终答案做落地支撑/幻觉量化打分。

- 只离线执行（worker 消费队列），绝不上在线热路径；
- 打分 LLM 走用户 BYOK 配置（不回退全局 key，见 backend/worker/evaluator.py）；
- 失败/无答案时返回空分，不影响任何在线结果。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from agent_service.llm.usage import usage_purpose
from agent_service.prompts import get_prompt
from backend.utils.logger import get_logger

logger = get_logger(__name__)

JUDGE_SYSTEM = get_prompt("evaluator_judge_system")

_TIMEOUT_SECONDS = 60


def _clamp(value: Any, default: float = 0.5) -> float:
    """把模型输出的打分收敛到 [0,1]，非法值用默认值兜底。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number))


def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """把 judge 输出归一化为可落库的指标。"""
    grounded = _clamp(raw.get("grounded_score"))
    hallucination = _clamp(raw.get("hallucination"))
    failed_claims = raw.get("failed_claims") or []
    if not isinstance(failed_claims, list):
        failed_claims = []
    overall = round((grounded + (1 - hallucination)) / 2, 4)
    return {
        "grounded_score": round(grounded, 4),
        "hallucination": round(hallucination, 4),
        "overall": overall,
        "detail": {
            "failed_claims": failed_claims[:5],
            "reason": str(raw.get("reason") or "")[:500],
        },
    }


async def judge_offline(answer: str, citations: list[dict[str, Any]], llm: Any) -> dict[str, Any]:
    """对最终答案执行离线评审；失败返回空分（record_offline 会跳过落库）。"""
    if not (answer or "").strip():
        return {"grounded_score": None, "hallucination": None, "overall": None, "detail": {"skipped": "无最终答案"}}

    payload = {
        "answer": answer,
        "citations": [{"index": c.get("index"), "text": (c.get("text") or c.get("title") or "")[:800]} for c in citations],
    }
    user_prompt = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        with usage_purpose("review"):
            raw = await asyncio.wait_for(
                llm.chat_json(JUDGE_SYSTEM, user_prompt, temperature=0.0, max_tokens=1024),
                timeout=_TIMEOUT_SECONDS,
            )
        return _normalize(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[Evaluator] 离线评审失败: %s", exc.__class__.__name__)
        return {"grounded_score": None, "hallucination": None, "overall": None, "detail": {"skipped": exc.__class__.__name__}}
