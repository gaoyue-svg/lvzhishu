"""本文件实现 Agent 回答的引用编号校验，防止回答引用不存在的来源。"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select

from backend.config import settings
from backend.models.knowledge import KnowledgeChunk


class CitationValidator:
    """校验回答中 `[n]` 引用是否能映射到检索或工具产生的 citation。"""

    async def validate(
        self,
        *,
        answer: str,
        citations: list[dict[str, Any]],
        db: Any | None = None,
        require_citation_use: bool = True,
    ) -> dict[str, Any]:
        """执行编号一致性和法条 Chunk 真实性校验。

        require_citation_use=True 时，有检索上下文却未用任何 `[n]` 引用会判失败，
        适用于最终回答（保证法律回答可溯源）；中间 Agent 产出（如 contract_rag 的
        法条检索结果，交由合成器合并引用）应传 False，只校验已用编号是否真实存在。
        """
        if not settings.citation_validation_enabled:
            return {"passed": True, "failed_ids": [], "reasons": []}
        used_numbers = {int(item) for item in re.findall(r"\[(\d+)\]", answer or "")}
        available_numbers = set(range(1, len(citations) + 1))
        available_numbers.update(
            int(item["index"]) for item in citations if str(item.get("index") or "").isdigit()
        )
        failed_ids = sorted(used_numbers - available_numbers)
        reasons = [f"回答引用了不存在的编号: {failed_ids}"] if failed_ids else []

        legal_chunk_ids = [
            str(item.get("chunk_id") or "")
            for item in citations
            if item.get("source_type", "law") == "law" and str(item.get("chunk_id") or "").isdigit()
        ]
        if db is not None and legal_chunk_ids:
            result = await db.execute(
                select(KnowledgeChunk.id).where(KnowledgeChunk.id.in_([int(item) for item in legal_chunk_ids]))
            )
            found = {str(item) for item in result.scalars().all()}
            missing = sorted(set(legal_chunk_ids) - found)
            if missing:
                failed_ids.extend(int(item) for item in missing if item.isdigit())
                reasons.append(f"法条引用对应 Chunk 不存在: {missing}")

        # 有检索上下文时，法律回答至少应引用一个来源，否则需要重写或人工复核。
        # 仅当 require_citation_use=True（最终回答）时生效；中间 Agent 产出不强制。
        if require_citation_use and citations and not used_numbers:
            reasons.append("回答未使用任何引用编号")

        return {
            "passed": not reasons,
            "failed_ids": sorted(set(failed_ids)),
            "reasons": reasons,
        }

