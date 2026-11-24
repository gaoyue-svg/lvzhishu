"""本文件封装向量化任务入队、文档向量清理与缓存查询业务操作。"""

from __future__ import annotations

import asyncio

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.knowledge import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from backend.models.task import TaskLog
from backend.services.model_runtime import resolve_embedding_runtime
from backend.utils.logger import get_logger
from backend.worker.task_queue import CHUNK_EMBEDDING_STREAM, TaskQueue
from embedding_service.embedding.embedding_cache import EmbeddingCache
from rag_service.retrieval.milvus_client import MilvusStore

logger = get_logger(__name__)


async def trigger_embedding(
    db: AsyncSession, task_queue: TaskQueue, document_id: str | int
) -> None:
    """将已解析文档加入 Embedding Stream 并写入任务日志。"""
    document = await db.get(KnowledgeDocument, int(document_id))
    if document is None:
        raise ValueError(f"文档不存在: {document_id}")
    kb = await db.get(KnowledgeBase, document.kb_id)
    if kb is None:
        raise ValueError(f"知识库不存在: {document.kb_id}")
    existing_task = await _find_unfinished_embedding_task(db, document.id)
    if existing_task is not None:
        logger.info("文档 %s 已存在未完成向量化任务 task_id=%s,跳过重复入队", document.id, existing_task.id)
        if document.embedding_status not in ("pending", "processing"):
            document.embedding_status = "pending"
        return
    runtime = await resolve_embedding_runtime(db, document, kb)
    task = {
        "document_id": str(document.id),
        "kb_id": str(document.kb_id),
        "kb_type": kb.kb_type,
        "runtime_snapshot": runtime.to_task_snapshot(),
    }
    msg_id = await task_queue.enqueue(CHUNK_EMBEDDING_STREAM, task)
    document.embedding_status = "pending"
    db.add(
        TaskLog(
            task_type="chunk_embedding",
            resource_type="knowledge_document",
            resource_id=document.id,
            user_id=document.user_id,
            status="pending",
            input_params={**task, "stream_msg_id": msg_id},
        )
    )


async def _find_unfinished_embedding_task(
    db: AsyncSession, document_id: int
) -> TaskLog | None:
    """查找同一文档尚未完成的向量化任务,避免重复入队。"""
    result = await db.execute(
        select(TaskLog)
        .where(
            TaskLog.task_type == "chunk_embedding",
            TaskLog.resource_id == document_id,
            TaskLog.status.in_(("pending", "running")),
        )
        .order_by(TaskLog.created_at.desc())
    )
    return result.scalars().first()


async def delete_document_vectors(
    milvus: MilvusStore | None, db: AsyncSession, document_id: str | int
) -> None:
    """删除文档全部 Milvus 向量并清空 vector_id，不触碰可复用缓存。"""
    result = await db.execute(
        select(KnowledgeChunk.id).where(
            KnowledgeChunk.document_id == int(document_id),
        )
    )
    chunk_ids = [str(item) for item in result.scalars().all()]
    if milvus is not None and chunk_ids:
        await asyncio.to_thread(milvus.delete_by_chunk_ids, chunk_ids)
    await db.execute(
        update(KnowledgeChunk)
        .where(KnowledgeChunk.document_id == int(document_id))
        .values(vector_id=None)
    )


async def check_embedding_cache(
    cache: EmbeddingCache | None, content_hash: str
) -> list[float] | None:
    """缓存未启用时直接返回未命中，否则读取指定内容哈希。"""
    return await cache.get(content_hash) if cache is not None else None
