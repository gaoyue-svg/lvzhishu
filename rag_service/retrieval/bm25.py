"""本文件实现支持持久化、知识库过滤与增量追加的单机 BM25 检索器。"""

from __future__ import annotations

import asyncio
import pickle
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.knowledge import KnowledgeChunk, KnowledgeDocument
from .tokenizer import BaseTokenizer, JiebaTokenizer


QUERY_STOPWORDS = {
    "?", "？", "!", "！", "。", "，", ",", "、",
    "会", "吗", "呢", "啊", "被", "是否", "什么", "怎么", "如何", "哪些", "相关",
}


class BM25Retriever:
    """用内存 BM25Okapi 提供阶段三关键词检索 MVP。"""

    def __init__(self, tokenizer: BaseTokenizer | None = None, index_dir: str = "storage/bm25"):
        """初始化分词器、持久化目录与空索引。"""
        self.tokenizer = tokenizer or JiebaTokenizer()
        self.index_dir = Path(index_dir)
        self._chunks: list[dict[str, Any]] = []
        self._tokenized_corpus: list[list[str]] = []
        self._index: Any | None = None
        self._lock = asyncio.Lock()

    @property
    def size(self) -> int:
        """返回当前内存索引的文档数。"""
        return len(self._chunks)

    async def build_index(self, chunks: list[dict[str, Any]]) -> None:
        """在线程中分词并重建内存索引。"""
        normalized = [self._normalize_chunk(chunk) for chunk in chunks]
        tokenized = await asyncio.to_thread(
            lambda: [self.tokenizer.tokenize(item["text"]) for item in normalized]
        )
        async with self._lock:
            self._chunks = normalized
            self._tokenized_corpus = tokenized
            self._index = self._create_index(tokenized)

    async def search(
        self,
        query: str,
        top_k: int = 20,
        filter_kb_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """按 kb_id 过滤候选并返回归一化 BM25 分数。"""
        if not query.strip() or self._index is None:
            return []
        tokens = await asyncio.to_thread(self.tokenizer.tokenize, query)
        tokens = [token for token in tokens if token not in QUERY_STOPWORDS]
        if not tokens:
            return []
        scores = await asyncio.to_thread(self._index.get_scores, tokens)
        allowed = {str(item) for item in filter_kb_ids or []}
        candidates = [
            (index, float(score))
            for index, score in enumerate(scores)
            if (not allowed or str(self._chunks[index].get("kb_id")) in allowed) and score > 0
        ]
        candidates.sort(key=lambda item: item[1], reverse=True)
        selected = candidates[:top_k]
        max_score = selected[0][1] if selected else 1.0
        return [
            {
                **self._chunks[index],
                "raw_bm25_score": score,
                "bm25_score": min(1.0, score / max_score) if max_score > 0 else 0.0,
            }
            for index, score in selected
        ]

    async def rebuild_all(self, db: AsyncSession) -> None:
        """从 MySQL 全量加载 Chunk 及文档版本字段后重建索引。"""
        result = await db.execute(
            select(KnowledgeChunk, KnowledgeDocument).join(
                KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id
            )
        )
        chunks = []
        for chunk, document in result.all():
            metadata = dict(chunk.metadata_ or {})
            metadata.setdefault("is_latest", document.is_latest)
            metadata.setdefault("version", document.version)
            chunks.append(
                {
                    "chunk_id": str(chunk.id),
                    "text": chunk.text,
                    "kb_id": str(chunk.kb_id),
                    "document_id": str(chunk.document_id),
                    "metadata": metadata,
                }
            )
        await self.build_index(chunks)

    async def save(self, path: str | None = None) -> None:
        """将可重建 BM25 对象的 Chunk 和分词语料 pickle 到磁盘。"""
        target = Path(path) if path else self.index_dir / "bm25_index.pkl"
        payload = {"chunks": self._chunks, "tokenized_corpus": self._tokenized_corpus}

        def _save() -> None:
            """在线程内执行阻塞文件写入。"""
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as handle:
                pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)

        await asyncio.to_thread(_save)

    async def load(self, path: str | None = None) -> bool:
        """从持久化文件恢复索引，文件缺失或损坏时返回 False。"""
        target = Path(path) if path else self.index_dir / "bm25_index.pkl"
        if not target.is_file():
            return False

        def _load() -> dict[str, Any]:
            """在线程内执行阻塞文件读取。"""
            with target.open("rb") as handle:
                return pickle.load(handle)  # noqa: S301 - 仅加载本服务生成的本地索引文件

        try:
            payload = await asyncio.to_thread(_load)
            chunks = payload["chunks"]
            tokenized = payload["tokenized_corpus"]
        except (OSError, EOFError, pickle.UnpicklingError, KeyError, TypeError):
            return False
        async with self._lock:
            self._chunks = chunks
            self._tokenized_corpus = tokenized
            self._index = self._create_index(tokenized)
        return True

    async def append_chunks(self, new_chunks: list[dict[str, Any]]) -> None:
        """按 chunk_id 去重后追加数据并重建 BM25Okapi 统计结构。"""
        existing = {str(item["chunk_id"]): item for item in self._chunks}
        for chunk in new_chunks:
            normalized = self._normalize_chunk(chunk)
            existing[str(normalized["chunk_id"])] = normalized
        await self.build_index(list(existing.values()))

    @staticmethod
    def _normalize_chunk(chunk: dict[str, Any]) -> dict[str, Any]:
        """确保索引条目只包含可持久化的基础数据。"""
        metadata = dict(chunk.get("metadata") or {})
        return {
            **chunk,
            "chunk_id": str(chunk.get("chunk_id") or chunk.get("id")),
            "text": str(chunk.get("text") or metadata.get("content") or ""),
            "kb_id": str(chunk.get("kb_id") or metadata.get("kb_id") or ""),
            "metadata": metadata,
        }

    @staticmethod
    def _create_index(tokenized: list[list[str]]):
        """延迟导入可选依赖并创建 BM25Okapi，空语料返回 None。"""
        if not tokenized:
            return None
        from rank_bm25 import BM25Okapi

        return BM25Okapi(tokenized)
