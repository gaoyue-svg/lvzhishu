"""打印指定查询最近一次 RAG Trace 的关键召回与排序信息。"""

from __future__ import annotations

import asyncio
import json
import sys

from sqlalchemy import desc, select

from backend.database import AsyncSessionLocal, engine
from backend.models.task import RagTrace


def summarize(items: list[dict] | None) -> list[dict]:
    result = []
    for item in items or []:
        metadata = item.get("metadata") or {}
        result.append(
            {
                "chunk_id": item.get("chunk_id"),
                "law_name": item.get("law_name") or metadata.get("law_name"),
                "article_no": item.get("article_no") or metadata.get("article_no"),
                "doc_type": item.get("doc_type") or metadata.get("doc_type"),
                "legal_level": item.get("legal_level") or metadata.get("legal_level"),
                "legal_domain": item.get("legal_domain") or metadata.get("legal_domain"),
                "keywords": item.get("keywords") or metadata.get("keywords"),
                "text": str(item.get("text") or metadata.get("content") or "")[:90],
                "bm25": item.get("bm25_score"),
                "semantic": item.get("milvus_score"),
                "rrf": item.get("rrf_score"),
                "final": item.get("final_score") or item.get("score"),
                "components": item.get("score_components"),
            }
        )
    return result


async def main(term: str) -> None:
    async with AsyncSessionLocal() as db:
        trace = (
            await db.execute(
                select(RagTrace)
                .where(RagTrace.original_query.contains(term))
                .order_by(desc(RagTrace.created_at))
                .limit(1)
            )
        ).scalar_one_or_none()
        if trace is None:
            raise SystemExit(f"No trace found for: {term}")
        details = trace.expanded_queries or {}
        payload = {
            "trace_id": trace.trace_id,
            "query": trace.original_query,
            "rewritten": trace.rewritten_query,
            "intent": details.get("query_intent"),
            "bm25_raw_query": details.get("bm25_raw_query"),
            "bm25": summarize(trace.bm25_results),
            "milvus": summarize(trace.milvus_results),
            "reranked": summarize(trace.reranked_results),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "醉驾"))
