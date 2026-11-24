"""输出 BGE 知识库迁移进度与 Milvus 状态。"""

from __future__ import annotations

import asyncio

from sqlalchemy import func, select

from backend.config import settings
from backend.database import AsyncSessionLocal, engine
from backend.models.knowledge import KnowledgeChunk, KnowledgeDocument
from backend.models.llm_config import UserLlmConfig
from embedding_service.embedding.embedding import BGEEmbedding
from rag_service.retrieval.milvus_client import MilvusStore


async def main() -> None:
    async with AsyncSessionLocal() as db:
        status_rows = (
            await db.execute(
                select(KnowledgeDocument.embedding_status, func.count())
                .where(KnowledgeDocument.parse_status == "completed")
                .group_by(KnowledgeDocument.embedding_status)
            )
        ).all()
        total_chunks = int(await db.scalar(select(func.count()).select_from(KnowledgeChunk)) or 0)
        embedded_chunks = int(
            await db.scalar(
                select(func.count())
                .select_from(KnowledgeChunk)
                .where(KnowledgeChunk.vector_id.is_not(None))
            )
            or 0
        )
        configs = list(
            (
                await db.execute(
                    select(
                        UserLlmConfig.user_id,
                        UserLlmConfig.provider,
                        UserLlmConfig.model_name,
                        UserLlmConfig.api_base,
                        UserLlmConfig.dimension,
                        UserLlmConfig.is_active,
                    ).where(UserLlmConfig.config_type == "embedding")
                )
            ).all()
        )
    store = await asyncio.to_thread(MilvusStore, settings.milvus_host, settings.milvus_port)
    dimension = await asyncio.to_thread(store.get_collection_dim)
    stats = await asyncio.to_thread(
        store.client.get_collection_stats,
        collection_name=store.collection_name,
    )
    print(f"documents={dict(status_rows)}")
    print(f"chunks={embedded_chunks}/{total_chunks}")
    print(f"milvus_dimension={dimension} milvus_rows={stats.get('row_count')}")
    print(f"embedding_configs={[tuple(item) for item in configs]}")
    embedding = BGEEmbedding(
        model_name="BAAI/bge-large-zh-v1.5",
        api_base="http://127.0.0.1:8080",
        dimension=1024,
    )
    query_vector = (await embedding.embed(["劳动合同解除有哪些法定情形"]))[0]
    hits = await asyncio.to_thread(store.search, query_vector, 3)
    print(
        "semantic_search_hits="
        + str(
            [
                {
                    "chunk_id": (hit.get("entity") or {}).get("chunk_id"),
                    "law_name": (hit.get("entity") or {}).get("law_name"),
                    "article_no": (hit.get("entity") or {}).get("article_no"),
                    "score": round(float(hit.get("distance") or 0), 4),
                }
                for hit in hits
            ]
        )
    )
    await embedding.client.aclose()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
