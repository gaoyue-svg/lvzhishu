"""将现有知识库从旧 Embedding 模型迁移到本地 BGE-large-zh-v1.5。"""

from __future__ import annotations

import asyncio

import httpx
from redis.asyncio import Redis
from sqlalchemy import select, text, update

from backend.config import settings
from backend.database import AsyncSessionLocal, engine
from backend.models.knowledge import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from backend.models.llm_config import UserLlmConfig
from backend.models.task import TaskLog
from backend.worker.task_queue import CHUNK_EMBEDDING_STREAM, TaskQueue
from embedding_service.services.embedding import trigger_embedding
from rag_service.retrieval.milvus_client import MilvusStore


MODEL = "BAAI/bge-large-zh-v1.5"
PROVIDER = "bge"
API_BASE = "http://127.0.0.1:8080"
DIMENSION = 1024
CACHE_PATTERN = "lawrag:embed_cache:*"


async def verify_embedding_service() -> None:
    """在改动任何持久化数据前验证本地模型服务和向量维度。"""
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{API_BASE}/embed",
            json={"inputs": ["中华人民共和国劳动合同法"]},
        )
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, list) or not payload or len(payload[0]) != DIMENSION:
        actual = len(payload[0]) if payload and isinstance(payload[0], list) else "invalid"
        raise RuntimeError(f"BGE 向量维度不正确: expected={DIMENSION}, actual={actual}")
    print(f"BGE service verified: model={MODEL}, dimension={DIMENSION}")


async def rebuild_milvus_collection() -> None:
    """删除旧维度 Collection，并按 1024 维重新创建。"""
    store = await asyncio.to_thread(MilvusStore, settings.milvus_host, settings.milvus_port)
    exists = await asyncio.to_thread(store.client.has_collection, store.collection_name)
    if exists:
        await asyncio.to_thread(store.client.drop_collection, store.collection_name)
    await asyncio.to_thread(store.init_collection, DIMENSION)
    actual = await asyncio.to_thread(store.get_collection_dim)
    if actual != DIMENSION:
        raise RuntimeError(f"Milvus Collection 维度不正确: expected={DIMENSION}, actual={actual}")
    print(f"Milvus collection rebuilt: {store.collection_name}, dimension={actual}")


async def clear_embedding_redis_state(redis: Redis) -> int:
    """只清理向量缓存和旧向量任务流，不影响其他 Redis 数据。"""
    deleted = 0
    batch: list[str] = []
    async for key in redis.scan_iter(match=CACHE_PATTERN, count=500):
        batch.append(key)
        if len(batch) >= 500:
            deleted += int(await redis.delete(*batch))
            batch.clear()
    if batch:
        deleted += int(await redis.delete(*batch))
    await redis.delete(CHUNK_EMBEDDING_STREAM)
    print(f"Redis embedding state cleared: cache_keys={deleted}")
    return deleted


async def update_database_and_enqueue(redis: Redis) -> tuple[int, int]:
    """更新运行配置、重置向量状态，并重新提交所有已解析文档。"""
    async with AsyncSessionLocal() as db:
        configs = list(
            (
                await db.execute(
                    select(UserLlmConfig).where(UserLlmConfig.config_type == "embedding")
                )
            )
            .scalars()
            .all()
        )
        for config in configs:
            config.provider = PROVIDER
            config.model_name = MODEL
            config.api_base = API_BASE
            config.api_key_encrypted = ""
            config.dimension = DIMENSION
            config.is_active = 1

        await db.execute(update(KnowledgeBase).values(embedding_model=MODEL))
        await db.execute(update(KnowledgeChunk).values(vector_id=None))
        await db.execute(
            update(KnowledgeDocument)
            .where(KnowledgeDocument.parse_status == "completed")
            .values(
                embedding_status="pending",
                embedding_count=0,
                embedding_failed_count=0,
                error_message=None,
            )
        )
        await db.execute(
            update(TaskLog)
            .where(
                TaskLog.task_type == "chunk_embedding",
                TaskLog.status.in_(("pending", "running")),
            )
            .values(status="failed", error_message="Embedding model migrated to local BGE")
        )
        await db.commit()

        document_ids = list(
            (
                await db.execute(
                    select(KnowledgeDocument.id)
                    .where(
                        KnowledgeDocument.parse_status == "completed",
                        KnowledgeDocument.chunk_count > 0,
                    )
                    .order_by(KnowledgeDocument.id)
                )
            )
            .scalars()
            .all()
        )
        queue = TaskQueue(redis)
        for document_id in document_ids:
            await trigger_embedding(db, queue, document_id)
        await db.commit()
        print(
            f"Database updated: embedding_configs={len(configs)}, "
            f"documents_enqueued={len(document_ids)}"
        )
        return len(configs), len(document_ids)


async def main() -> None:
    await verify_embedding_service()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis.ping()
        await rebuild_milvus_collection()
        await clear_embedding_redis_state(redis)
        await update_database_and_enqueue(redis)
    finally:
        await redis.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
