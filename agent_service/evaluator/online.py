"""在线确定性评估指标（doc 21 §4.2）：引用编号完整性 + 引用覆盖度，纯代码可算、不调 LLM。"""

from __future__ import annotations

import re
from typing import Any

_REF_PATTERN = re.compile(r"\[(\d+)\]")


def _citation_indexes(citations: list[dict[str, Any]]) -> set[int]:
    """收集 citations 中有效的数字编号集合。"""
    indexes: set[int] = set()
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        value = citation.get("index")
        if value is None:
            continue
        try:
            indexes.add(int(value))
        except (TypeError, ValueError):
            continue
    return indexes


def _answer_refs(answer: str) -> list[int]:
    """提取最终答案中所有 [n] 引用编号。"""
    return [int(number) for number in _REF_PATTERN.findall(answer or "")]


def compute_citation_score(answer: str, citations: list[dict[str, Any]]) -> float:
    """引用编号完整性：答案中每个 [n] 都必须在 citations 中存在。

    无引用 → 1.0（无可检查项）；否则 matched/total。
    """
    refs = _answer_refs(answer)
    if not refs:
        return 1.0
    valid = _citation_indexes(citations)
    matched = sum(1 for ref in refs if ref in valid)
    return round(matched / len(refs), 4)


def compute_coverage(answer: str, citations: list[dict[str, Any]]) -> float:
    """引用覆盖度：citations 中被答案实际引用的比例（used_unique / total）。

    无引用列表 → 1.0；否则为实际引用编号占比。
    """
    if not citations:
        return 1.0
    refs = set(_answer_refs(answer))
    valid = _citation_indexes(citations)
    used = len(refs & valid)
    return round(used / len(citations), 4)


def compute_online_scores(answer: str, citations: list[dict[str, Any]]) -> dict[str, Any]:
    """一次算齐在线指标并附带失败引用明细，供 recorder 落 evaluation_result。"""
    citation_score = compute_citation_score(answer, citations)
    coverage = compute_coverage(answer, citations)
    overall = round(0.5 * citation_score + 0.5 * coverage, 4)

    refs = _answer_refs(answer)
    valid = _citation_indexes(citations)
    detail = {
        "failed_refs": [ref for ref in refs if ref not in valid],
        "ref_count": len(refs),
        "citation_count": len(citations),
    }
    return {
        "citation_score": citation_score,
        "coverage": coverage,
        "overall": overall,
        "detail": detail,
    }
