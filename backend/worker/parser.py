"""本文件实现独立文档解析 Worker，并在解析后触发父级 Chunk 与向量化后处理。"""

from __future__ import annotations

import asyncio
from datetime import datetime
import os
import signal
import socket
import tempfile
from pathlib import Path
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import delete, select

from backend.config import settings
from backend.database import AsyncSessionLocal, close_connections, init_redis
from backend.models.knowledge import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from backend.models.task import TaskLog
from backend.services.parser import chunk_document, parse_document_with_metadata
from backend.services.contract_parser import parse_contract
from backend.storage.oss import OSSClient
from backend.utils.logger import get_logger
from backend.worker.task_queue import DOCUMENT_PARSE_STREAM, TaskQueue
from embedding_service.services.embedding import trigger_embedding
from rag_service.retrieval.parent_chunk import ParentChunkBuilder

logger = get_logger(__name__)
GROUP = "document-parser"

# Redis 瞬时故障（连接断开、读超时）时跳过本轮，避免 Worker 整体退出。
# TimeoutError 为内置异常，可同时覆盖 redis.exceptions.TimeoutError 与 asyncio.TimeoutError。
TRANSIENT_REDIS_ERRORS = (RedisConnectionError, TimeoutError)


async def main(
    stop_event: asyncio.Event | None = None,
    register_signals: bool = True,
    close_on_exit: bool = True,
) -> None:
    """运行文档解析 Worker，直到收到 SIGINT/SIGTERM 或外部 stop_event。

    嵌入模式（register_signals=False, close_on_exit=False）下由宿主进程
    管理生命周期与资源清理，便于在后端 lifespan 中作为后台协程运行。
    """
    if stop_event is None:
        stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    if register_signals:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:
                signal.signal(sig, lambda *_: stop_event.set())

    redis = await init_redis()
    if redis is None:
        raise RuntimeError("Redis 未初始化")
    queue = TaskQueue(redis)
    consumer = f"{socket.gethostname()}-{os.getpid()}"
    oss = OSSClient(settings.oss_endpoint, settings.oss_access_key_id, settings.oss_access_key_secret)
    logger.info("文档解析 Worker 以 %s 身份启动", consumer)

    try:
        while not stop_event.is_set():
            # 仅对"读取任务"做瞬时故障容错：BLOCK 读取超时或连接抖动时跳过本轮，
            # 下一轮 continue 即可；避免异常冒泡导致整个 Worker 退出。
            try:
                tasks = await queue.reclaim_stale(
                    DOCUMENT_PARSE_STREAM, GROUP, consumer, min_idle_ms=60000
                )
                if not tasks:
                    tasks = await queue.consume(DOCUMENT_PARSE_STREAM, GROUP, consumer, block_ms=5000)
            except TRANSIENT_REDIS_ERRORS:
                logger.warning("解析 Worker 读取任务瞬时故障，跳过本轮重试")
                continue
            for msg_id, task in tasks:
                try:
                    await _handle_task(task, oss, queue)
                except asyncio.CancelledError:
                    # Worker 被取消（关闭/重启）：不 ACK，让下次 reclaim_stale 重新消费，
                    # 避免消息被确认但处理未完成导致状态永久卡住。
                    logger.warning("解析 Worker 被取消，消息 %s 未 ACK，下次将重新消费", msg_id)
                    raise
                except Exception:
                    logger.exception("处理消息 %s 时发生未预期错误", msg_id)
                # 仅在正常完成或异常已处理后 ACK；CancelledError 已 re-raise 不会走到这里。
                await queue.ack(DOCUMENT_PARSE_STREAM, GROUP, msg_id)
                if stop_event.is_set():
                    break
    finally:
        if close_on_exit:
            await close_connections()
        logger.info("文档解析 Worker 已停止")


async def _handle_task(task: dict[str, Any], oss: OSSClient, queue: TaskQueue) -> None:
    """解析单个文档，生成父级 Chunk，并在提交后入队向量化任务。"""
    document_id = int(task["document_id"])
    trace = f"document_id={document_id}"
    logger.info("开始解析 %s", trace)
    async with AsyncSessionLocal() as db:
        doc = await db.get(KnowledgeDocument, document_id)
        if doc is None:
            logger.warning("文档不存在: %s", trace)
            return
        kb = await db.get(KnowledgeBase, doc.kb_id)
        if kb is None:
            logger.warning("知识库不存在: %s", trace)
            return
        task_log = await _find_task_log(db, document_id)
        if task_log:
            task_log.status = "running"
            task_log.started_at = datetime.now()
        doc.parse_status = "parsing"
        doc.error_message = None
        await db.commit()

        tmp_path = Path(tempfile.gettempdir()) / f"lawrag-doc-{document_id}.{doc.file_type}"
        try:
            await oss.download_file(doc.oss_bucket, doc.oss_key, str(tmp_path))
            parsed = await parse_document_with_metadata(str(tmp_path), doc.file_type)
            text = parsed.markdown
            doc.raw_markdown = text
            # 合同走 ContractParser 结构化切分，复用 knowledge_chunk 表，跳过 ParentChunkBuilder
            if kb.kb_type == "contract":
                chunks = _build_contract_chunks(text, doc.id, doc.filename)
            else:
                chunks = await chunk_document(
                    text,
                    kb.kb_type,
                    kb.chunk_size,
                    kb.chunk_overlap,
                    filename=doc.filename,
                )
            if not chunks:
                warning_text = "；".join(parsed.warnings) if parsed.warnings else "解析器未提取到可用正文"
                raise ValueError(f"文档未生成任何 Chunk：{warning_text}")
            old_chunk_count = doc.chunk_count or 0
            await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id))
            db.add_all(
                KnowledgeChunk(
                    document_id=doc.id,
                    kb_id=doc.kb_id,
                    chunk_index=chunk["chunk_index"],
                    chunk_type=chunk["chunk_type"],
                    chunk_level=chunk.get("chunk_level"),
                    chunk_subtype=chunk.get("chunk_subtype"),
                    parent_chunk_id=chunk.get("parent_chunk_id") or None,
                    text=chunk["text"],
                    token_count=chunk["token_count"],
                    metadata_=chunk["metadata"],
                )
                for chunk in chunks
            )
            await db.flush()
            # 合同已由 ContractParser 产出章节层级，跳过 ParentChunkBuilder
            if kb.kb_type == "contract":
                parent_count = 0
            else:
                # Parser 已产出 LawTree 层级 metadata；这里仅基于 metadata 生成父级 Chunk。
                parent_count = await ParentChunkBuilder().build_for_document(db, doc.id)
            # chunk_count 是冗余统计字段，不会随着 KnowledgeChunk ORM 对象插入自动更新。
            # 必须按本次实际生成的叶子/条款与父级 Chunk 数量显式写回，否则数据库
            # 已有 Chunk、向量化也成功，但日志和前端会一直错误显示为 0。
            total_chunk_count = len(chunks) + parent_count
            doc.chunk_count = total_chunk_count
            doc.parse_status = "completed"
            kb.chunk_count = max((kb.chunk_count or 0) - old_chunk_count, 0) + total_chunk_count
            if task_log:
                task_log.status = "completed"
                task_log.output_result = {
                    "article_and_leaf_count": len(chunks),
                    "parent_chunk_count": parent_count,
                    "chunk_count": total_chunk_count,
                    "parse_warnings": parsed.warnings,
                }
                task_log.finished_at = datetime.now()
            await db.commit()
            logger.info("解析完成 %s chunks=%s", trace, total_chunk_count)

            # 解析事务先落库；即使 Redis 短暂故障也不回滚已成功的解析结果。
            try:
                await trigger_embedding(db, queue, doc.id)
                await db.commit()
            except Exception:
                await db.rollback()
                logger.exception("入队向量化任务失败 %s", trace)
        except Exception as exc:
            await db.rollback()
            async with AsyncSessionLocal() as error_db:
                failed_doc = await error_db.get(KnowledgeDocument, document_id)
                failed_log = await _find_task_log(error_db, document_id)
                if failed_doc:
                    failed_doc.parse_status = "failed"
                    failed_doc.error_message = str(exc)[:2000]
                if failed_log:
                    failed_log.status = "failed"
                    failed_log.error_message = str(exc)[:2000]
                    failed_log.finished_at = datetime.now()
                await error_db.commit()
            logger.exception("解析失败 %s", trace)
        finally:
            tmp_path.unlink(missing_ok=True)


def _build_contract_chunks(markdown: str, document_id: int, filename: str) -> list[dict[str, Any]]:
    """用 ContractParser 把合同 Markdown 切分为结构化条款 chunk 列表。

    合同条款复用 knowledge_chunk 表，chunk_subtype 区分章节与叶子条款。
    ContractParser 已产出章节层级，无需 ParentChunkBuilder 再生成父级。
    """
    doc = parse_contract(markdown, filename)
    chunks = doc.to_chunks(document_id)
    if not chunks:
        # 合同解析未识别到条款时降级为单段落，避免空文档导致后续向量化失败
        clean_text = markdown.strip()
        if clean_text:
            chunks = [{
                "chunk_index": 0,
                "chunk_type": "contract_clause",
                "chunk_level": "section",
                "chunk_subtype": "contract_clause",
                "text": clean_text[:2000],
                "token_count": len(clean_text[:2000]) // 2,
                "parent_chunk_id": None,
                "metadata": {
                    "article_no": "",
                    "title": filename or "合同全文",
                    "clause_type": "other",
                    "chunk_level": "section",
                    "parent_no": "",
                    "entities": {},
                    "chunk_index": 0,
                },
            }]
    return chunks


async def _find_task_log(db, document_id: int) -> TaskLog | None:
    """查询指定文档最近一条 document_parse 任务日志。"""
    result = await db.execute(
        select(TaskLog)
        .where(TaskLog.task_type == "document_parse", TaskLog.resource_id == document_id)
        .order_by(TaskLog.created_at.desc())
    )
    return result.scalars().first()


if __name__ == "__main__":
    asyncio.run(main())
