"""本文件从最终检索 Chunk 构建可定位 PDF 原文的法律引用。"""

from typing import Any

from .models import Citation


async def build_citations(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """提取引用展示、版本与页码字段。

    text 保留 200 字片段用于紧凑展示；full_text 携带完整 chunk 原文，
    供前端点击引用后弹窗查看全文。
    """
    citations = []
    for chunk in chunks:
        metadata = dict(chunk.get("metadata") or {})
        text = str(chunk.get("text") or metadata.get("content") or "")
        citation = Citation(
            chunk_id=str(chunk.get("chunk_id") or metadata.get("id") or ""),
            law_name=metadata.get("law_name"),
            article_no=metadata.get("article_no") or metadata.get("article"),
            hierarchy_path=metadata.get("hierarchy_path"),
            text=text[:200],
            full_text=text,
            score=float(chunk.get("final_score") or chunk.get("score") or 0.0),
            version=metadata.get("version"),
            effective_date=metadata.get("effective_date"),
            page_start=metadata.get("page_start"),
            page_end=metadata.get("page_end"),
            char_start=metadata.get("char_start"),
            char_end=metadata.get("char_end"),
            source_uri=metadata.get("source_uri"),
        )
        citations.append(citation.to_dict())
    return citations
