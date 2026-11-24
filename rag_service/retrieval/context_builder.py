"""本文件将检索结果整理为带引用编号、层级信息与 token 上限的 Prompt Context。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.knowledge import KnowledgeChunk
from backend.utils.tokenizer import count_tokens, truncate_to_tokens
from .citation import build_citations
from .models import ContextResult


class ContextBuilder:
    """独立于 Retriever 和 LLM 的结构化上下文构建器。"""

    def __init__(self, model_name: str = "cl100k_base"):
        """保存 token 计数使用的模型名称。"""
        self.model_name = model_name

    async def build(
        self,
        chunks: list[dict[str, Any]],
        citations: list[dict[str, Any]],
        max_tokens: int = 4000,
        include_hierarchy: bool = True,
    ) -> ContextResult:
        """按排名构造 `[N] 标题 + 正文`，超限时从尾部裁剪。"""
        blocks: list[str] = []
        citation_map: dict[int, dict[str, Any]] = {}
        used_tokens = 0
        for index, chunk in enumerate(chunks, start=1):
            metadata = dict(chunk.get("metadata") or {})
            text = str(chunk.get("text") or metadata.get("content") or "").strip()
            heading = self._heading(metadata, include_hierarchy)
            prefix = f"[{index}] {heading}:\n" if heading else f"[{index}]\n"
            block = f"{prefix}{text}".strip()
            block_tokens = count_tokens(block, self.model_name)
            remaining = max_tokens - used_tokens
            if remaining <= 0:
                break
            if block_tokens > remaining:
                block = truncate_to_tokens(block, remaining, self.model_name).rstrip()
                block_tokens = count_tokens(block, self.model_name)
            if not block:
                break
            blocks.append(block)
            if index <= len(citations):
                citation_map[index] = citations[index - 1]
            used_tokens += block_tokens
            if used_tokens >= max_tokens:
                break
        return ContextResult(
            context_text="\n\n".join(blocks),
            citation_map=citation_map,
            token_count=used_tokens,
            chunk_count=len(blocks),
        )

    async def build_with_parent_expansion(
        self,
        parent_chunks: list[dict[str, Any]],
        db: AsyncSession,
        max_tokens: int = 6000,
    ) -> ContextResult:
        """沿子节点的 parent_chunk_id 向下查询，优先用完整叶子原文构建上下文。"""
        all_chunks = list(parent_chunks)
        frontier = {
            str((chunk.get("metadata") or {}).get("id"))
            for chunk in parent_chunks
            if (chunk.get("metadata") or {}).get("id")
        }
        seen = set(frontier)
        # 法律层级最多为 编→章→节→条，限制三轮避免脏数据形成循环。
        for _ in range(3):
            if not frontier:
                break
            result = await db.execute(
                select(KnowledgeChunk)
                .where(KnowledgeChunk.parent_chunk_id.in_(frontier))
                .order_by(KnowledgeChunk.document_id, KnowledgeChunk.chunk_index)
            )
            children = list(result.scalars().all())
            if not children:
                break
            child_dicts = [self._from_orm(chunk) for chunk in children]
            all_chunks.extend(child_dicts)
            next_frontier = {
                str((item.get("metadata") or {}).get("id"))
                for item in child_dicts
                if item.get("chunk_level") in {"book", "chapter", "section"}
                and (item.get("metadata") or {}).get("id")
            }
            frontier = next_frontier - seen
            seen.update(next_frontier)

        leaves = [
            chunk for chunk in all_chunks
            if (chunk.get("metadata") or {}).get("chunk_level", chunk.get("chunk_level"))
            not in {"book", "chapter", "section"}
        ]
        selected = leaves or all_chunks
        citations = await build_citations(selected)
        return await self.build(selected, citations, max_tokens=max_tokens, include_hierarchy=True)

    @staticmethod
    def _heading(metadata: dict[str, Any], include_hierarchy: bool) -> str:
        """优先使用层级路径，否则组合法律名称和条号。"""
        if include_hierarchy and metadata.get("hierarchy_path"):
            return str(metadata["hierarchy_path"])
        law_name = metadata.get("law_name")
        article_no = metadata.get("article_no") or metadata.get("article")
        title = "".join(
            part for part in (
                f"《{law_name}》" if law_name else "",
                str(article_no or metadata.get("title") or ""),
            ) if part
        )
        return title

    @staticmethod
    def _from_orm(chunk: KnowledgeChunk) -> dict[str, Any]:
        """将 ORM Chunk 转换为上下文构建所需字典。"""
        metadata = dict(chunk.metadata_ or {})
        return {
            "chunk_id": str(chunk.id),
            "text": chunk.text,
            "metadata": metadata,
            "chunk_level": chunk.chunk_level,
            "parent_chunk_id": chunk.parent_chunk_id,
        }
