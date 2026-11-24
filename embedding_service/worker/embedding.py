"""本文件实现独立 Embedding Worker，负责缓存复用、向量入库、状态回写与 BM25 增量更新。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import os
import re
import signal
import socket
from typing import Any

from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import func, select

from backend.config import settings
from backend.database import AsyncSessionLocal, close_connections, init_redis
from backend.models.knowledge import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from backend.models.task import TaskLog
from backend.services.model_runtime import resolve_embedding_runtime
from backend.utils.logger import get_logger
from backend.worker.task_queue import CHUNK_EMBEDDING_STREAM, TaskQueue
from embedding_service.embedding.context_enhancer import create_default_enhancer
from embedding_service.embedding.embedding import EmbeddingFactory
from embedding_service.embedding.embedding_cache import CacheScope, EmbeddingCache
from rag_service.retrieval.bm25 import BM25Retriever
from rag_service.retrieval.milvus_client import MilvusStore
from rag_service.retrieval.tokenizer import JiebaTokenizer

logger = get_logger(__name__)
GROUP = "chunk-embedding"

# Redis 瞬时故障（连接断开、读超时）时跳过本轮，避免 Worker 整体退出。
# TimeoutError 为内置异常，可同时覆盖 redis.exceptions.TimeoutError 与 asyncio.TimeoutError。
TRANSIENT_REDIS_ERRORS = (RedisConnectionError, TimeoutError)


@dataclass(frozen=True)
class EmbeddingErrorInfo:
    """向量化异常的归一化信息,用于日志、任务状态和是否继续处理。"""

    status_code: int | None
    code: str
    message: str
    permanent: bool


@dataclass(frozen=True)
class EmbeddingWorkItem:
    """保存单个 Chunk 在向量化阶段需要复用的上下文。"""

    chunk: KnowledgeChunk
    metadata: dict[str, Any]
    enhanced_text: str
    content_hash: str


@dataclass(frozen=True)
class VectorizationResult:
    """保存批量向量化结果和可写入缓存的新向量。"""

    vector_by_hash: dict[str, list[float]]
    new_cache: dict[str, list[float]]
    errors: list[str]
    aborted_by_permanent_error: bool


@dataclass(frozen=True)
class UpsertResult:
    """保存 Milvus 批量入库后的统计结果。"""

    success_count: int
    errors: list[str]
    bm25_chunks: list[dict[str, Any]]


async def main(
    stop_event: asyncio.Event | None = None,
    register_signals: bool = True,
    close_on_exit: bool = True,
) -> None:
    """持续消费向量化任务，并确保每条 Redis 消息都在 finally 中 ACK。

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
    cache = None
    if settings.embedding_cache_enabled:
        cache = EmbeddingCache(
            redis,
            scope=CacheScope(settings.embedding_cache_scope),
            ttl=settings.embedding_cache_ttl,
        )
    milvus = MilvusStore(settings.milvus_host, settings.milvus_port)
    await asyncio.to_thread(milvus.init_collection, settings.embedding_dim)
    consumer = f"{socket.gethostname()}-{os.getpid()}"
    logger.info("Embedding Worker 已启动: %s", consumer)
    try:
        while not stop_event.is_set():
            # 仅对"读取任务"做瞬时故障容错：BLOCK 读取超时或连接抖动时跳过本轮，
            # 下一轮 continue 即可；避免异常冒泡导致整个 Worker 退出。
            try:
                tasks = await queue.reclaim_stale(
                    CHUNK_EMBEDDING_STREAM, GROUP, consumer, min_idle_ms=60000
                )
                if not tasks:
                    tasks = await queue.consume(
                        CHUNK_EMBEDDING_STREAM, GROUP, consumer, block_ms=5000
                    )
            except TRANSIENT_REDIS_ERRORS:
                logger.warning("Embedding Worker 读取任务瞬时故障，跳过本轮重试")
                continue
            for msg_id, task in tasks:
                try:
                    await _handle_task(task, milvus, cache)
                except asyncio.CancelledError:
                    # Worker 被取消（关闭/重启）：不 ACK，让下次 reclaim_stale 重新消费，
                    # 避免消息被确认但处理未完成导致状态永久卡住。
                    logger.warning("Embedding Worker 被取消，消息 %s 未 ACK，下次将重新消费", msg_id)
                    raise
                except Exception as exc:
                    logger.exception("Embedding消息处理出现未捕获异常 msg_id=%s", msg_id)
                    try:
                        await _record_unhandled_failure(task, exc)
                    except Exception:
                        logger.exception("Embedding失败状态回写失败 msg_id=%s", msg_id)
                # 仅在正常完成或异常已处理后 ACK；CancelledError 已 re-raise 不会走到这里。
                await queue.ack(CHUNK_EMBEDDING_STREAM, GROUP, msg_id)
                if stop_event.is_set():
                    break
    finally:
        if close_on_exit:
            await close_connections()
        logger.info("Embedding worker stopped")


def _classify_embedding_error(exc: Exception) -> EmbeddingErrorInfo:
    """将不同 SDK/HTTP 异常归类为可重试或不可重试错误。"""
    status_code = _extract_status_code(exc)
    body = _extract_error_body(exc)
    code = _extract_error_code(exc, body)
    message = _extract_error_message(exc, body)
    permanent = _is_permanent_embedding_error(status_code, code, message)
    return EmbeddingErrorInfo(
        status_code=status_code,
        code=code,
        message=message[:500],
        permanent=permanent,
    )


def _extract_status_code(exc: Exception) -> int | None:
    """从 OpenAI SDK 或 httpx 异常中提取 HTTP 状态码。"""
    status_code = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status_code is None and response is not None:
        status_code = getattr(response, "status_code", None)
    return status_code if isinstance(status_code, int) else None


def _extract_error_body(exc: Exception) -> dict[str, Any] | None:
    """尽量提取服务端 JSON 错误体。"""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        return body
    response = getattr(exc, "response", None)
    if response is None:
        return None
    try:
        payload = response.json()
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _extract_error_code(exc: Exception, body: dict[str, Any] | None) -> str:
    """从错误体或异常属性中提取稳定错误码。"""
    if body:
        error = body.get("error") if isinstance(body.get("error"), dict) else body
        code = error.get("code") or error.get("type")
        if code:
            return str(code)
    code = getattr(exc, "code", None)
    return str(code) if code else exc.__class__.__name__


def _extract_error_message(exc: Exception, body: dict[str, Any] | None) -> str:
    """从错误体或异常字符串中提取可读错误信息。"""
    if body:
        error = body.get("error") if isinstance(body.get("error"), dict) else body
        message = error.get("message") or body.get("message")
        if message:
            return _compact_message(str(message))
    return _compact_message(str(exc) or exc.__class__.__name__)


def _is_permanent_embedding_error(
    status_code: int | None, code: str, message: str
) -> bool:
    """判断错误是否属于配置、权限、额度等不可通过重试恢复的问题。"""
    if status_code is not None and 400 <= status_code < 500 and status_code != 429:
        return True
    lowered = f"{code} {message}".lower()
    permanent_markers = (
        "free tier",
        "freetier",
        "quota exhausted",
        "allocationquota",
        "invalid api key",
        "authentication",
        "permission",
        "model not found",
        "invalid model",
    )
    return any(marker in lowered for marker in permanent_markers)


def _format_chunk_error(chunk_id: int, failure: EmbeddingErrorInfo) -> str:
    """生成写入数据库的单 chunk 错误摘要。"""
    status = f" status={failure.status_code}" if failure.status_code is not None else ""
    return f"chunk_id={chunk_id}:{status} code={failure.code} message={failure.message}"[:500]


def _compact_message(message: str) -> str:
    """压缩错误信息中的空白字符,避免日志和数据库字段过长。"""
    return " ".join(message.replace("\r", " ").replace("\n", " ").split())


def _resolve_embedding_batch_size(provider: str, model_name: str, configured: int) -> int:
    """根据模型服务商限制收敛实际 Embedding 批大小。"""
    batch_size = _positive_batch_size(configured, 100)
    service_limit = _embedding_service_batch_limit(provider, model_name)
    return min(batch_size, service_limit) if service_limit else batch_size


def _embedding_service_batch_limit(provider: str, model_name: str) -> int | None:
    """返回已知 Embedding 服务的单请求条数上限。"""
    marker = f"{provider} {model_name}".lower()
    if "qwen" in marker or "dashscope" in marker:
        return 20
    return None


def _extract_embedding_batch_limit(message: str) -> int | None:
    """从服务端错误信息中提取批大小上限。"""
    lowered = message.lower()
    if "batch size" not in lowered and "input.contents" not in lowered:
        return None
    patterns = (
        r"not be larger than\s+(\d+)",
        r"larger than\s+(\d+)",
        r"at most\s+(\d+)",
        r"maximum(?:\s+batch\s+size)?\s*(?:is|:)?\s*(\d+)",
    )
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            return max(int(match.group(1)), 1)
    return None


async def _vectorize_missing_items(
    *,
    embedding: Any,
    work_items: list[EmbeddingWorkItem],
    cached: dict[str, list[float] | None],
    batch_size: int,
    document: KnowledgeDocument,
    provider: str,
    model_name: str,
) -> VectorizationResult:
    """按 content_hash 去重后批量向量化,缓存命中直接复用。"""
    vector_by_hash: dict[str, list[float]] = {}
    new_cache: dict[str, list[float]] = {}
    errors: list[str] = []
    seen_hashes: set[str] = set()
    unique_missing: list[EmbeddingWorkItem] = []
    for item in work_items:
        if item.content_hash in seen_hashes:
            continue
        cached_vector = cached.get(item.content_hash)
        if cached_vector is not None and len(cached_vector) == embedding.dimension:
            vector_by_hash[item.content_hash] = cached_vector
            seen_hashes.add(item.content_hash)
            continue
        if cached_vector is not None:
            logger.warning(
                "Embedding缓存维度不匹配,将重新向量化 document_id=%s chunk_id=%s expected=%s actual=%s",
                document.id,
                item.chunk.id,
                embedding.dimension,
                len(cached_vector),
            )
        seen_hashes.add(item.content_hash)
        unique_missing.append(item)

    effective_batch_size = _resolve_embedding_batch_size(provider, model_name, batch_size)
    if effective_batch_size != _positive_batch_size(batch_size, 100):
        logger.info(
            "Embedding批大小按服务限制调整 provider=%s model=%s configured=%s effective=%s",
            provider,
            model_name,
            batch_size,
            effective_batch_size,
        )

    aborted_by_permanent_error = False
    for batch in _batched(unique_missing, effective_batch_size):
        try:
            _merge_vectors(
                batch,
                await embedding.embed([item.enhanced_text for item in batch]),
                embedding.dimension,
                vector_by_hash,
                new_cache,
            )
        except Exception as exc:
            failure = _classify_embedding_error(exc)
            server_limit = _extract_embedding_batch_limit(failure.message)
            if server_limit and len(batch) > server_limit:
                fallback = await _vectorize_limited_batches(
                    embedding=embedding,
                    batch=batch,
                    limit=server_limit,
                    document=document,
                    provider=provider,
                    model_name=model_name,
                    vector_by_hash=vector_by_hash,
                    new_cache=new_cache,
                )
                errors.extend(fallback.errors)
                if fallback.aborted_by_permanent_error:
                    aborted_by_permanent_error = True
                    break
                continue
            if not failure.permanent and len(batch) > 1:
                fallback = await _vectorize_one_by_one(
                    embedding=embedding,
                    batch=batch,
                    document=document,
                    provider=provider,
                    model_name=model_name,
                    vector_by_hash=vector_by_hash,
                    new_cache=new_cache,
                )
                errors.extend(fallback.errors)
                if fallback.aborted_by_permanent_error:
                    aborted_by_permanent_error = True
                    break
                continue
            errors.extend(
                _record_embedding_failure(document, item, provider, model_name, failure)
                for item in batch
            )
            if failure.permanent:
                aborted_by_permanent_error = True
                break

    return VectorizationResult(
        vector_by_hash=vector_by_hash,
        new_cache=new_cache,
        errors=errors,
        aborted_by_permanent_error=aborted_by_permanent_error,
    )


async def _vectorize_one_by_one(
    *,
    embedding: Any,
    batch: list[EmbeddingWorkItem],
    document: KnowledgeDocument,
    provider: str,
    model_name: str,
    vector_by_hash: dict[str, list[float]],
    new_cache: dict[str, list[float]],
) -> VectorizationResult:
    """批量请求失败时逐条补救,尽量隔离坏 Chunk。"""
    errors: list[str] = []
    for item in batch:
        try:
            _merge_vectors(
                [item],
                await embedding.embed([item.enhanced_text]),
                embedding.dimension,
                vector_by_hash,
                new_cache,
            )
        except Exception as exc:
            failure = _classify_embedding_error(exc)
            errors.append(_record_embedding_failure(document, item, provider, model_name, failure))
            if failure.permanent:
                return VectorizationResult(vector_by_hash, new_cache, errors, True)
    return VectorizationResult(vector_by_hash, new_cache, errors, False)


async def _vectorize_limited_batches(
    *,
    embedding: Any,
    batch: list[EmbeddingWorkItem],
    limit: int,
    document: KnowledgeDocument,
    provider: str,
    model_name: str,
    vector_by_hash: dict[str, list[float]],
    new_cache: dict[str, list[float]],
) -> VectorizationResult:
    """服务端提示批大小过大时,按返回上限拆分后重试。"""
    errors: list[str] = []
    safe_limit = _positive_batch_size(limit, 1)
    logger.info(
        "Embedding批大小超过服务端限制,拆分重试 document_id=%s provider=%s model=%s limit=%s",
        document.id,
        provider,
        model_name,
        safe_limit,
    )
    for limited_batch in _batched(batch, safe_limit):
        try:
            _merge_vectors(
                limited_batch,
                await embedding.embed([item.enhanced_text for item in limited_batch]),
                embedding.dimension,
                vector_by_hash,
                new_cache,
            )
        except Exception as exc:
            failure = _classify_embedding_error(exc)
            if not failure.permanent and len(limited_batch) > 1:
                fallback = await _vectorize_one_by_one(
                    embedding=embedding,
                    batch=limited_batch,
                    document=document,
                    provider=provider,
                    model_name=model_name,
                    vector_by_hash=vector_by_hash,
                    new_cache=new_cache,
                )
                errors.extend(fallback.errors)
                if fallback.aborted_by_permanent_error:
                    return VectorizationResult(vector_by_hash, new_cache, errors, True)
                continue
            errors.extend(
                _record_embedding_failure(document, item, provider, model_name, failure)
                for item in limited_batch
            )
            if failure.permanent:
                return VectorizationResult(vector_by_hash, new_cache, errors, True)
    return VectorizationResult(vector_by_hash, new_cache, errors, False)


def _merge_vectors(
    batch: list[EmbeddingWorkItem],
    vectors: list[list[float]],
    dimension: int,
    vector_by_hash: dict[str, list[float]],
    new_cache: dict[str, list[float]],
) -> None:
    """校验批量返回结果并写入本轮内存缓存。"""
    if len(vectors) != len(batch):
        raise ValueError(f"Embedding API 返回数量不匹配: 期望 {len(batch)}, 实际 {len(vectors)}")
    for item, vector in zip(batch, vectors, strict=True):
        if len(vector) != dimension:
            raise ValueError(f"Embedding 维度不匹配: 期望 {dimension}, 实际 {len(vector)}")
        vector_by_hash[item.content_hash] = vector
        new_cache[item.content_hash] = vector


async def _upsert_vector_rows(
    *,
    milvus: MilvusStore,
    document: KnowledgeDocument,
    work_items: list[EmbeddingWorkItem],
    vector_by_hash: dict[str, list[float]],
    batch_size: int,
) -> UpsertResult:
    """将已获得向量的 Chunk 批量写入 Milvus,并回填数据库主键。"""
    row_items = [
        (item, _build_milvus_row(item.chunk, document, item.metadata, vector, item.content_hash))
        for item in work_items
        if (vector := vector_by_hash.get(item.content_hash)) is not None
    ]
    success_count = 0
    errors: list[str] = []
    bm25_chunks: list[dict[str, Any]] = []
    for batch in _batched(row_items, _positive_batch_size(batch_size, 1000)):
        try:
            batch_success, batch_bm25 = await _upsert_batch(milvus, batch)
            success_count += batch_success
            bm25_chunks.extend(batch_bm25)
        except Exception as exc:
            if len(batch) > 1:
                fallback = await _upsert_rows_one_by_one(milvus, document, batch)
                success_count += fallback.success_count
                errors.extend(fallback.errors)
                bm25_chunks.extend(fallback.bm25_chunks)
                continue
            failure = _classify_embedding_error(exc)
            errors.append(_record_milvus_failure(document, batch[0][0], failure))
    return UpsertResult(success_count=success_count, errors=errors, bm25_chunks=bm25_chunks)


async def _upsert_rows_one_by_one(
    milvus: MilvusStore,
    document: KnowledgeDocument,
    batch: list[tuple[EmbeddingWorkItem, dict[str, Any]]],
) -> UpsertResult:
    """Milvus 批量写入失败时逐条补救,便于定位问题数据。"""
    success_count = 0
    errors: list[str] = []
    bm25_chunks: list[dict[str, Any]] = []
    for item in batch:
        try:
            batch_success, batch_bm25 = await _upsert_batch(milvus, [item])
            success_count += batch_success
            bm25_chunks.extend(batch_bm25)
        except Exception as exc:
            failure = _classify_embedding_error(exc)
            errors.append(_record_milvus_failure(document, item[0], failure))
    return UpsertResult(success_count=success_count, errors=errors, bm25_chunks=bm25_chunks)


async def _upsert_batch(
    milvus: MilvusStore, batch: list[tuple[EmbeddingWorkItem, dict[str, Any]]]
) -> tuple[int, list[dict[str, Any]]]:
    """执行一次 Milvus 批量 upsert,返回成功数量和 BM25 增量数据。"""
    ids = await asyncio.to_thread(milvus.upsert, [row for _, row in batch])
    if len(ids) != len(batch):
        raise RuntimeError(f"Milvus 返回主键数量不匹配: 期望 {len(batch)}, 实际 {len(ids)}")
    bm25_chunks: list[dict[str, Any]] = []
    for (item, _), vector_id in zip(batch, ids, strict=True):
        item.chunk.vector_id = vector_id
        bm25_chunks.append(
            {
                "chunk_id": str(item.chunk.id),
                "text": item.chunk.text,
                "kb_id": str(item.chunk.kb_id),
                "document_id": str(item.chunk.document_id),
                "metadata": item.metadata,
            }
        )
    return len(batch), bm25_chunks


def _record_embedding_failure(
    document: KnowledgeDocument,
    item: EmbeddingWorkItem,
    provider: str,
    model_name: str,
    failure: EmbeddingErrorInfo,
) -> str:
    """记录单个 Chunk 的向量化失败日志并返回错误摘要。"""
    logger.warning(
        "Embedding失败 document_id=%s user_id=%s chunk_id=%s provider=%s model=%s "
        "status=%s code=%s permanent=%s message=%s",
        document.id,
        document.user_id,
        item.chunk.id,
        provider,
        model_name,
        failure.status_code,
        failure.code,
        failure.permanent,
        failure.message,
    )
    return _format_chunk_error(item.chunk.id, failure)


def _record_milvus_failure(
    document: KnowledgeDocument, item: EmbeddingWorkItem, failure: EmbeddingErrorInfo
) -> str:
    """记录单个 Chunk 的 Milvus 入库失败日志并返回错误摘要。"""
    logger.warning(
        "Milvus入库失败 document_id=%s user_id=%s chunk_id=%s status=%s code=%s message=%s",
        document.id,
        document.user_id,
        item.chunk.id,
        failure.status_code,
        failure.code,
        failure.message,
    )
    return _format_chunk_error(item.chunk.id, failure)


def _batched(items: list[Any], batch_size: int) -> list[list[Any]]:
    """按固定大小切分列表。"""
    return [items[start : start + batch_size] for start in range(0, len(items), batch_size)]


def _positive_batch_size(value: int, default: int) -> int:
    """配置值非法时回退到默认批大小。"""
    return value if isinstance(value, int) and value > 0 else default


async def _handle_task(
    task: dict[str, Any], milvus: MilvusStore, cache: EmbeddingCache | None
) -> None:
    """处理单文档 Chunk，单 Chunk 失败不影响其他 Chunk。"""
    document_id = int(task["document_id"])
    async with AsyncSessionLocal() as db:
        document = await db.get(KnowledgeDocument, document_id)
        if document is None:
            logger.warning("Embedding文档不存在 document_id=%s", document_id)
            return
        kb = await db.get(KnowledgeBase, document.kb_id)
        if kb is None:
            await _mark_document_failure(db, document, "Knowledge base not found")
            return
        task_log = await _find_task_log(db, document_id)
        document.embedding_status = "processing"
        document.error_message = None
        if task_log:
            task_log.status = "running"
            task_log.started_at = datetime.now()
        await db.commit()

        result = await db.execute(
            select(KnowledgeChunk)
            .where(
                KnowledgeChunk.document_id == document_id,
                KnowledgeChunk.vector_id.is_(None),
            )
            .order_by(KnowledgeChunk.chunk_index)
        )
        chunks = list(result.scalars().all())
        if not chunks:
            document.embedding_status = "completed"
            document.embedding_count = document.chunk_count
            document.embedding_failed_count = 0
            if task_log:
                task_log.status = "completed"
                task_log.output_result = {"success_count": 0, "skipped_count": document.chunk_count}
                task_log.finished_at = datetime.now()
            await db.commit()
            return

        runtime = await resolve_embedding_runtime(
            db,
            document,
            kb,
            snapshot=task.get("runtime_snapshot") if isinstance(task.get("runtime_snapshot"), dict) else None,
        )
        provider = runtime.provider
        model_name = runtime.model_name
        api_base = runtime.api_base
        api_key = runtime.api_key
        dimension = runtime.dimension or settings.embedding_dim
        logger.info(
            "Embedding任务配置 document_id=%s user_id=%s provider=%s model=%s dimension=%s source=%s warnings=%s",
            document.id,
            document.user_id,
            provider,
            model_name,
            dimension,
            runtime.source,
            runtime.warnings,
        )
        embedding = EmbeddingFactory.create(
            provider,
            model_name,
            api_base or None,
            api_key or None,
            dimension=dimension,
        )
        enhancer = create_default_enhancer(settings.max_embedding_tokens, model_name)
        metadata_items = []
        for chunk in chunks:
            metadata = dict(chunk.metadata_ or {})
            metadata.update(
                {
                    "content": chunk.text,
                    "chunk_type": chunk.chunk_type,
                    "chunk_subtype": chunk.chunk_subtype,
                    "chunk_level": chunk.chunk_level,
                }
            )
            metadata_items.append(metadata)
        enhanced_texts = await enhancer.enhance_batch(metadata_items)
        tenant_ids = [str(item.get("tenant_id") or document.user_id) for item in metadata_items]
        hashes = [
            _compute_hash(cache, text, tenant_id, provider, model_name, embedding.dimension)
            for text, tenant_id in zip(enhanced_texts, tenant_ids, strict=True)
        ]
        cached = await cache.batch_get(hashes) if cache else {item: None for item in hashes}

        work_items = [
            EmbeddingWorkItem(chunk, metadata, enhanced_text, content_hash)
            for chunk, metadata, enhanced_text, content_hash in zip(
                chunks, metadata_items, enhanced_texts, hashes, strict=True
            )
        ]
        vectorization = await _vectorize_missing_items(
            embedding=embedding,
            work_items=work_items,
            cached=cached,
            batch_size=settings.embedding_batch_size,
            document=document,
            provider=provider,
            model_name=model_name,
        )
        upsert_result = await _upsert_vector_rows(
            milvus=milvus,
            document=document,
            work_items=work_items,
            vector_by_hash=vectorization.vector_by_hash,
            batch_size=settings.milvus_upsert_batch_size,
        )

        errors = [*vectorization.errors, *upsert_result.errors]
        if cache and vectorization.new_cache:
            await cache.batch_set(vectorization.new_cache)
        failed_count = len(chunks) - upsert_result.success_count
        completed_total = int(
            await db.scalar(
                select(func.count())
                .select_from(KnowledgeChunk)
                .where(
                    KnowledgeChunk.document_id == document_id,
                    KnowledgeChunk.vector_id.is_not(None),
                )
            )
            or 0
        )
        document.embedding_count = completed_total
        document.embedding_failed_count = failed_count
        if failed_count == 0:
            document.embedding_status = "completed"
        elif upsert_result.success_count > 0 or completed_total > 0:
            document.embedding_status = "partial_failed"
        else:
            document.embedding_status = "failed"
        document.error_message = "\n".join(errors)[:2000] if errors else None
        if task_log:
            task_log.status = "completed" if failed_count == 0 else "failed"
            task_log.output_result = {
                "success_count": upsert_result.success_count,
                "failed_count": failed_count,
                "cache_hit_count": sum(
                    1
                    for item in work_items
                    if (cached_vector := cached.get(item.content_hash)) is not None
                    and len(cached_vector) == embedding.dimension
                ),
                "cache_miss_unique_count": len(
                    {
                        item.content_hash
                        for item in work_items
                        if (cached_vector := cached.get(item.content_hash)) is None
                        or len(cached_vector) != embedding.dimension
                    }
                ),
                "embedding_batch_size": settings.embedding_batch_size,
                "effective_embedding_batch_size": _resolve_embedding_batch_size(
                    provider, model_name, settings.embedding_batch_size
                ),
                "milvus_upsert_batch_size": settings.milvus_upsert_batch_size,
                "enhanced_text_preview": enhanced_texts[:3],
                "runtime_config": runtime.to_public_dict(),
                "aborted_by_permanent_error": vectorization.aborted_by_permanent_error,
            }
            task_log.error_message = document.error_message
            task_log.finished_at = datetime.now()
        await db.commit()

        # BM25 是单机 MVP；向量成功后增量更新并立即持久化。
        if upsert_result.bm25_chunks:
            bm25 = BM25Retriever(
                tokenizer=JiebaTokenizer(settings.tokenizer_dict_path or None),
                index_dir=settings.bm25_index_dir,
            )
            if not await bm25.load():
                await bm25.rebuild_all(db)
            else:
                await bm25.append_chunks(upsert_result.bm25_chunks)
            await bm25.save()


def _compute_hash(
    cache: EmbeddingCache | None,
    text: str,
    tenant_id: str,
    provider: str,
    model_name: str,
    dimension: int,
) -> str:
    """缓存关闭时仍按相同规范生成 Milvus content_hash。"""
    if cache:
        return cache.compute_hash(text, tenant_id, provider, model_name, dimension)
    import hashlib

    raw = f"{tenant_id}:{provider}:{model_name}:{dimension}:{text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _build_milvus_row(
    chunk: KnowledgeChunk,
    document: KnowledgeDocument,
    metadata: dict[str, Any],
    vector: list[float],
    content_hash: str,
) -> dict[str, Any]:
    """只提取检索过滤必需的标量字段，不写入完整 metadata JSON。"""
    return {
        "embedding": vector,
        "chunk_id": str(chunk.id),
        "tenant_id": str(metadata.get("tenant_id") or document.user_id),
        "kb_id": str(chunk.kb_id),
        "document_id": str(chunk.document_id),
        "doc_type": str(metadata.get("doc_type") or ""),
        "chunk_type": str(chunk.chunk_type or ""),
        "chunk_subtype": str(chunk.chunk_subtype or ""),
        "chunk_level": str(chunk.chunk_level or ""),
        "legal_level": str(metadata.get("legal_level") or ""),
        "version": str(metadata.get("version") or document.version or ""),
        "is_latest": bool(metadata.get("is_latest", document.is_latest)),
        "page_start": int(metadata.get("page_start") or 0),
        "page_end": int(metadata.get("page_end") or 0),
        "content_hash": content_hash,
        "law_name": str(metadata.get("law_name") or "")[:200],
        "article_no": str(metadata.get("article_no") or metadata.get("article") or "")[:40],
    }


async def _find_task_log(db, document_id: int) -> TaskLog | None:
    """查找文档最近一条向量化任务日志。"""
    result = await db.execute(
        select(TaskLog)
        .where(TaskLog.task_type == "chunk_embedding", TaskLog.resource_id == document_id)
        .order_by(TaskLog.created_at.desc())
    )
    return result.scalars().first()


async def _mark_document_failure(db, document: KnowledgeDocument, message: str) -> None:
    """记录无法开始处理的文档级失败。"""
    document.embedding_status = "failed"
    document.error_message = message[:2000]
    await db.commit()


async def _record_unhandled_failure(task: dict[str, Any], exc: Exception) -> None:
    """发生文档级异常时另开会话回写 failed，避免状态永久停在 processing。"""
    document_id = int(task.get("document_id") or 0)
    if not document_id:
        return
    async with AsyncSessionLocal() as db:
        document = await db.get(KnowledgeDocument, document_id)
        task_log = await _find_task_log(db, document_id)
        message = str(exc)[:2000] or exc.__class__.__name__
        if document:
            document.embedding_status = "failed"
            document.embedding_failed_count = max(
                (document.chunk_count or 0) - (document.embedding_count or 0), 0
            )
            document.error_message = message
        if task_log:
            task_log.status = "failed"
            task_log.error_message = message
            task_log.finished_at = datetime.now()
        await db.commit()


if __name__ == "__main__":
    asyncio.run(main())
