"""运行“醉驾会被判刑吗”真实混合检索回归探针。"""

from __future__ import annotations

import asyncio
import json

from backend.config import settings
from backend.database import AsyncSessionLocal, engine
from embedding_service.embedding.embedding import BGEEmbedding
from rag_service.retrieval.bm25 import BM25Retriever
from rag_service.retrieval.milvus_client import MilvusStore
from rag_service.retrieval.query_rewrite import RuleQueryRewriter
from rag_service.retrieval.query_router import QueryRouter
from rag_service.retrieval.reranker import RuleLegalReranker
from rag_service.retrieval.retriever import HybridRetriever
from rag_service.retrieval.tokenizer import JiebaTokenizer


async def main() -> None:
    bm25 = BM25Retriever(
        tokenizer=JiebaTokenizer(settings.tokenizer_dict_path or None),
        index_dir=settings.bm25_index_dir,
    )
    if not await bm25.load():
        raise RuntimeError("BM25 index is unavailable")
    embedding = BGEEmbedding(
        model_name="BAAI/bge-large-zh-v1.5",
        api_base="http://127.0.0.1:8080",
        dimension=1024,
    )
    async with AsyncSessionLocal() as db:
        retriever = HybridRetriever(
            bm25=bm25,
            milvus=MilvusStore(settings.milvus_host, settings.milvus_port),
            embedding=embedding,
            reranker=RuleLegalReranker(),
            query_rewriter=RuleQueryRewriter(),
            query_router=QueryRouter(),
            db=db,
        )
        result = await retriever.retrieve(
            "醉驾会被判刑吗？",
            kb_ids=None,
            top_k=15,
            rerank_top_k=10,
        )
        print(
            json.dumps(
                [
                    {
                        "rank": index,
                        "law_name": hit.metadata.get("law_name"),
                        "article_no": hit.metadata.get("article_no"),
                        "text": hit.text[:100],
                        "score": round(hit.final_score, 4),
                        "bm25": hit.bm25_score,
                        "semantic": hit.milvus_score,
                    }
                    for index, hit in enumerate(result.chunks, start=1)
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
    await embedding.client.aclose()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
