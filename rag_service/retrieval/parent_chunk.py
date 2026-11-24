"""本文件在解析完成后以规则模板构建可幂等更新的编、章、节父级 Chunk。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import re
from collections import defaultdict
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.knowledge import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from backend.utils.tokenizer import count_tokens

PARENT_LEVELS = {"book", "chapter", "section"}
DOC_TYPE_MAP = {
    "law": "statute",
    "judicial": "judicial_doc",
    "case": "case_file",
    "contract": "contract_doc",
    "enterprise": "policy",
}


class ParentChunkBuilder:
    """维护父子层级；父级稳定 ID 放入 metadata.id，子级仅保存 parent_chunk_id。"""

    def __init__(self, milvus=None):
        """可选注入 Milvus，以便增量重建时同步清理失效父级向量。"""
        self.milvus = milvus

    @staticmethod
    def enrich_hierarchy_metadata(
        parsed_chunks: list[dict[str, Any]], source_text: str
    ) -> None:
        """扫描法律原文标题并为 Parser 产出的 Article 补齐编、章、节层级 metadata。"""
        numeral = r"[一二三四五六七八九十百千万零〇0-9]+"
        pattern = re.compile(
            rf"(?m)^\s*(?:#{{1,6}}\s*)?(?P<hierarchy>第{numeral}(?:编|章|节))[ \t]*(?P<title>[^\n]*)$"
            rf"|(?P<article>第{numeral}条)"
        )
        current: dict[str, str] = {}
        article_hierarchy: dict[str, dict[str, str]] = {}
        for match in pattern.finditer(source_text):
            heading = match.group("hierarchy")
            if heading:
                title = (match.group("title") or "").strip().lstrip("#").strip()
                if heading.endswith("编"):
                    current = {"part_no": heading, "part_title": title}
                elif heading.endswith("章"):
                    current.pop("section_no", None)
                    current.pop("section_title", None)
                    current.update({"chapter_no": heading, "chapter_title": title})
                else:
                    current.update({"section_no": heading, "section_title": title})
                continue
            article_no = match.group("article")
            if article_no:
                article_hierarchy.setdefault(article_no, dict(current))

        for chunk in parsed_chunks:
            metadata = chunk.setdefault("metadata", {})
            article_no = metadata.get("article_no") or metadata.get("article")
            hierarchy = article_hierarchy.get(str(article_no))
            if not hierarchy:
                continue
            metadata.update(hierarchy)
            metadata["article_no"] = article_no
            path_parts = []
            for number_key, title_key in (
                ("part_no", "part_title"),
                ("chapter_no", "chapter_title"),
                ("section_no", "section_title"),
            ):
                value = ParentChunkBuilder._title(metadata.get(number_key), metadata.get(title_key))
                if value:
                    path_parts.append(value)
            path_parts.append(str(article_no))
            metadata["hierarchy_path"] = " > ".join(path_parts)

    @staticmethod
    def build_parent_chunk_id(
        document_id: str,
        chunk_level: str,
        part_no: str = "",
        chapter_no: str = "",
        section_no: str = "",
        article_no: str = "",
    ) -> str:
        """按文档与非空层级字段生成稳定 ID。"""
        values = [document_id, chunk_level]
        fields = {
            "book": (part_no,),
            "chapter": (part_no, chapter_no),
            "section": (part_no, chapter_no, section_no),
            "article": (article_no,),
        }.get(chunk_level, (part_no, chapter_no, section_no, article_no))
        values.extend(str(value).strip() for value in fields if value)
        return ":".join(values)

    async def normalize_document_chunks(
        self,
        db: AsyncSession,
        document: KnowledgeDocument,
        kb: KnowledgeBase,
    ) -> list[KnowledgeChunk]:
        """在不改动 Parser 的前提下补齐阶段三检索 metadata 与独立列。"""
        result = await db.execute(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.document_id == document.id)
            .order_by(KnowledgeChunk.chunk_index)
        )
        chunks = list(result.scalars().all())
        needs_legacy_hierarchy = any(
            chunk.chunk_type == "article" and not (chunk.metadata_ or {}).get("hierarchy_path")
            for chunk in chunks
        )
        if kb.kb_type in {"law", "judicial"} and document.raw_markdown and needs_legacy_hierarchy:
            parsed_chunks = [
                {
                    "chunk_type": chunk.chunk_type,
                    "text": chunk.text,
                    "metadata": dict(chunk.metadata_ or {}),
                }
                for chunk in chunks
            ]
            self.enrich_hierarchy_metadata(parsed_chunks, document.raw_markdown)
            for chunk, parsed in zip(chunks, parsed_chunks, strict=False):
                chunk.metadata_ = parsed["metadata"]
        for chunk in chunks:
            metadata = dict(chunk.metadata_ or {})
            parser_type = chunk.chunk_type
            large_type = kb.kb_type if kb.kb_type in DOC_TYPE_MAP else "enterprise"
            is_article = large_type in {"law", "judicial"} and parser_type == "article"
            subtype = self._resolve_subtype(large_type, is_article, metadata, chunk.text)
            level = (
                "article" if is_article
                else "clause" if large_type == "contract"
                else metadata.get("chunk_level") or "paragraph"
            )
            article_no = metadata.get("article_no") or metadata.get("article")
            version = metadata.get("version") or document.version or self._extract_version(
                document.filename
            )
            if document.version is None and version:
                document.version = str(version)
            effective_date = self._to_unix_timestamp(
                metadata.get("effective_date") or document.effective_date
            )
            if document.effective_date is None and effective_date is not None:
                document.effective_date = effective_date

            metadata.update(
                {
                    "content": chunk.text,
                    "tenant_id": str(document.user_id),
                    "kb_id": str(document.kb_id),
                    "document_id": str(document.id),
                    "chunk_index": chunk.chunk_index,
                    "doc_type": metadata.get("doc_type") or DOC_TYPE_MAP.get(large_type, "policy"),
                    "chunk_type": large_type,
                    "chunk_subtype": subtype,
                    "chunk_level": level,
                    "article_no": article_no,
                    "version": str(version) if version else None,
                    "effective_date": effective_date,
                    "is_latest": document.is_latest,
                    "page_start": metadata.get("page_start"),
                    "page_end": metadata.get("page_end"),
                    "char_start": metadata.get("char_start"),
                    "char_end": metadata.get("char_end"),
                    "source_uri": metadata.get("source_uri") or document.oss_key,
                    "parent_chunk_id": chunk.parent_chunk_id,
                }
            )
            if not metadata.get("id"):
                metadata["id"] = self.build_parent_chunk_id(
                    str(document.id), "article", article_no=str(article_no or chunk.chunk_index)
                )
            chunk.chunk_type = large_type
            chunk.chunk_level = level
            chunk.chunk_subtype = subtype
            chunk.metadata_ = metadata
        await db.flush()
        return chunks

    async def build_for_document(self, db: AsyncSession, document_id: str | int) -> int:
        """为整份文档生成或更新所有具备层级 metadata 的父级 Chunk。"""
        document = await db.get(KnowledgeDocument, int(document_id))
        if document is None:
            return 0
        kb = await db.get(KnowledgeBase, document.kb_id)
        if kb is None:
            return 0
        chunks = await self.normalize_document_chunks(db, document, kb)
        articles = [chunk for chunk in chunks if chunk.chunk_level == "article"]
        desired = self._build_parent_specs(document, articles)

        existing_result = await db.execute(
            select(KnowledgeChunk).where(
                KnowledgeChunk.document_id == document.id,
                KnowledgeChunk.chunk_level.in_(PARENT_LEVELS),
            )
        )
        existing = list(existing_result.scalars().all())
        existing_by_uid = {
            str((chunk.metadata_ or {}).get("id")): chunk
            for chunk in existing
            if (chunk.metadata_ or {}).get("id")
        }
        next_index = int(
            await db.scalar(
                select(func.coalesce(func.max(KnowledgeChunk.chunk_index), -1)).where(
                    KnowledgeChunk.document_id == document.id
                )
            )
            or 0
        ) + 1

        for uid, spec in desired.items():
            chunk = existing_by_uid.get(uid)
            if chunk is None:
                chunk = KnowledgeChunk(
                    document_id=document.id,
                    kb_id=document.kb_id,
                    chunk_index=next_index,
                    text=spec["text"],
                    token_count=count_tokens(spec["text"]),
                )
                next_index += 1
                db.add(chunk)
            content_changed = chunk.text != spec["text"]
            chunk.parent_chunk_id = spec["parent_chunk_id"]
            chunk.chunk_type = spec["chunk_type"]
            chunk.chunk_level = spec["chunk_level"]
            chunk.chunk_subtype = None
            chunk.text = spec["text"]
            chunk.token_count = count_tokens(spec["text"])
            if content_changed:
                chunk.vector_id = None
            chunk.metadata_ = spec["metadata"]

        stale_ids = [chunk.id for uid, chunk in existing_by_uid.items() if uid not in desired]
        if stale_ids:
            if self.milvus is not None:
                await asyncio.to_thread(
                    self.milvus.delete_by_chunk_ids, [str(item) for item in stale_ids]
                )
            await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.id.in_(stale_ids)))

        # Article 的父级引用也在此后处理阶段统一更新。
        for article in articles:
            metadata = dict(article.metadata_ or {})
            parent_uid = self._article_parent_uid(str(document.id), metadata)
            article.parent_chunk_id = parent_uid
            metadata["parent_chunk_id"] = parent_uid
            article.metadata_ = metadata

        await db.flush()
        document.chunk_count = len(articles) + len(desired) + len(
            [chunk for chunk in chunks if chunk.chunk_level not in PARENT_LEVELS | {"article"}]
        )
        return len(desired)

    async def rebuild_for_articles(self, db: AsyncSession, article_chunk_ids: list[str]) -> int:
        """按受影响 Article 所属文档重建父链，稳定 ID 保证已有父级为原位更新。"""
        numeric_ids = [int(item) for item in article_chunk_ids if str(item).isdigit()]
        if not numeric_ids:
            return 0
        result = await db.execute(
            select(KnowledgeChunk.document_id).where(KnowledgeChunk.id.in_(numeric_ids)).distinct()
        )
        return sum(
            [await self.build_for_document(db, document_id) for document_id in result.scalars().all()]
        )

    def generate_section_content(
        self, section_meta: dict[str, Any], child_articles: list[dict[str, Any]]
    ) -> str:
        """用标题、正文前十字主题与条号列表生成节级规则摘要。"""
        title = self._title(section_meta.get("section_no"), section_meta.get("section_title"))
        topics = self._unique(
            self._topic(str(article.get("content") or article.get("text") or ""))
            for article in child_articles
        )
        article_numbers = self._unique(str(article.get("article_no") or "") for article in child_articles)
        return (
            f"【{title}】\n本节包含 {len(child_articles)} 条，主题包括：{'、'.join(topics[:8]) or title}。"
            f"\n条文列表：{'、'.join(article_numbers)}"
        )

    def generate_chapter_content(
        self, chapter_meta: dict[str, Any], child_sections: list[dict[str, Any]]
    ) -> str:
        """用章标题与子节主题生成章级规则摘要。"""
        title = self._title(chapter_meta.get("chapter_no"), chapter_meta.get("chapter_title"))
        lines = [f"【{title}】", f"本章共 {len(child_sections)} 节，规定了相关法律规则："]
        for section in child_sections:
            section_title = self._title(section.get("section_no"), section.get("section_title"))
            lines.append(f"{section_title} — {self._first_sentence(str(section.get('content') or ''))}")
        return "\n".join(lines)

    def generate_book_content(
        self, book_meta: dict[str, Any], child_chapters: list[dict[str, Any]]
    ) -> str:
        """用编标题与章标题列表生成编级规则摘要。"""
        title = self._title(book_meta.get("part_no"), book_meta.get("part_title"))
        chapters = self._unique(
            self._title(item.get("chapter_no"), item.get("chapter_title")) for item in child_chapters
        )
        return f"【{title}】\n本编共 {len(chapters)} 章。\n章节列表：{'、'.join(chapters)}"

    def _build_parent_specs(
        self, document: KnowledgeDocument, articles: list[KnowledgeChunk]
    ) -> dict[str, dict[str, Any]]:
        """根据 Article metadata 分组生成全部父级规格。"""
        doc_id = str(document.id)
        article_dicts = [dict(chunk.metadata_ or {}, text=chunk.text) for chunk in articles]
        specs: dict[str, dict[str, Any]] = {}

        section_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        chapter_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        book_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for metadata in article_dicts:
            part_no = str(metadata.get("part_no") or "")
            chapter_no = str(metadata.get("chapter_no") or "")
            section_no = str(metadata.get("section_no") or "")
            if section_no:
                section_groups[(part_no, chapter_no, section_no)].append(metadata)
            if chapter_no:
                chapter_groups[(part_no, chapter_no)].append(metadata)
            if part_no:
                book_groups[part_no].append(metadata)

        section_summaries: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for (part_no, chapter_no, section_no), children in section_groups.items():
            first = children[0]
            uid = self.build_parent_chunk_id(doc_id, "section", part_no, chapter_no, section_no)
            parent_uid = (
                self.build_parent_chunk_id(doc_id, "chapter", part_no, chapter_no)
                if chapter_no else self.build_parent_chunk_id(doc_id, "book", part_no) if part_no else None
            )
            content = self.generate_section_content(first, children)
            spec = self._parent_spec(document, first, uid, parent_uid, "section", content)
            specs[uid] = spec
            section_summaries[(part_no, chapter_no)].append(dict(first, id=uid, content=content))

        chapter_summaries: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for (part_no, chapter_no), children in chapter_groups.items():
            first = children[0]
            uid = self.build_parent_chunk_id(doc_id, "chapter", part_no, chapter_no)
            parent_uid = self.build_parent_chunk_id(doc_id, "book", part_no) if part_no else None
            sections = section_summaries[(part_no, chapter_no)]
            if sections:
                content = self.generate_chapter_content(first, sections)
            else:
                topics = self._unique(self._topic(str(item.get("content") or "")) for item in children)
                title = self._title(first.get("chapter_no"), first.get("chapter_title"))
                content = f"【{title}】\n本章包含 {len(children)} 条，主题包括：{'、'.join(topics[:10])}。"
            specs[uid] = self._parent_spec(document, first, uid, parent_uid, "chapter", content)
            chapter_summaries[part_no].append(dict(first, id=uid, content=content))

        for part_no, children in book_groups.items():
            first = children[0]
            uid = self.build_parent_chunk_id(doc_id, "book", part_no)
            chapters = chapter_summaries[part_no]
            content = self.generate_book_content(first, chapters) if chapters else (
                f"【{self._title(first.get('part_no'), first.get('part_title'))}】\n"
                f"本编包含 {len(children)} 条法律规则。"
            )
            specs[uid] = self._parent_spec(document, first, uid, None, "book", content)
        return specs

    def _parent_spec(
        self,
        document: KnowledgeDocument,
        source: dict[str, Any],
        uid: str,
        parent_uid: str | None,
        level: str,
        content: str,
    ) -> dict[str, Any]:
        """从子级公共 metadata 构造精简但兼容的父级 metadata。"""
        metadata = dict(source)
        metadata.update(
            {
                "id": uid,
                "content": content,
                "chunk_type": source.get("chunk_type") or "law",
                "chunk_subtype": None,
                "chunk_level": level,
                "parent_chunk_id": parent_uid,
                "article_no": None,
                "is_latest": document.is_latest,
            }
        )
        metadata.pop("text", None)
        return {
            "text": content,
            "parent_chunk_id": parent_uid,
            "chunk_type": str(metadata["chunk_type"]),
            "chunk_level": level,
            "metadata": metadata,
        }

    def _article_parent_uid(self, doc_id: str, metadata: dict[str, Any]) -> str | None:
        """选择 Article 实际存在的最近父级。"""
        part_no = str(metadata.get("part_no") or "")
        chapter_no = str(metadata.get("chapter_no") or "")
        section_no = str(metadata.get("section_no") or "")
        if section_no:
            return self.build_parent_chunk_id(doc_id, "section", part_no, chapter_no, section_no)
        if chapter_no:
            return self.build_parent_chunk_id(doc_id, "chapter", part_no, chapter_no)
        if part_no:
            return self.build_parent_chunk_id(doc_id, "book", part_no)
        return None

    @staticmethod
    def _title(number: Any, title: Any) -> str:
        """组合编号和标题并去除多余空白。"""
        return " ".join(str(value).strip() for value in (number, title) if value).strip()

    @staticmethod
    def _topic(text: str) -> str:
        """从法条正文去掉条号后提取前十个字符作为规则主题。"""
        value = re.sub(r"^第[一二三四五六七八九十百千万零〇0-9]+条\s*", "", text).strip()
        return value[:10].rstrip("，。；：")

    @staticmethod
    def _first_sentence(text: str) -> str:
        """提取用于父级摘要的首句并限制长度。"""
        return re.split(r"[。！？\n]", text, maxsplit=1)[0][:80]

    @staticmethod
    def _unique(values) -> list[str]:
        """按出现顺序去重并过滤空字符串。"""
        return list(dict.fromkeys(value for value in values if value))

    @staticmethod
    def _resolve_subtype(
        chunk_type: str,
        is_article: bool,
        metadata: dict[str, Any],
        text: str,
    ) -> str | None:
        """为阶段二未细分的案例、合同和企业制度补充可检索子类型。"""
        if is_article:
            return "article"
        if metadata.get("chunk_subtype"):
            return str(metadata["chunk_subtype"])
        if chunk_type == "case":
            if "本院认为" in text or "法院认为" in text:
                return "court_view"
            if "判决如下" in text or "裁判如下" in text:
                return "judgment_result"
            return "case_basic_info"
        if chunk_type == "contract":
            clause_type = str(metadata.get("clause_type") or "")
            for keyword, subtype in (
                ("付款", "payment"), ("违约", "liability"),
                ("解除", "termination"), ("争议", "dispute"),
            ):
                if keyword in clause_type or keyword in text[:100]:
                    return subtype
            return "clause"
        if chunk_type == "enterprise":
            return "policy_rule"
        return None

    @staticmethod
    def _to_unix_timestamp(value: Any) -> int | None:
        """将 Parser 可能产生的中文日期安全转换为 Unix 秒。"""
        if value in (None, ""):
            return None
        if isinstance(value, (int, float)):
            return int(value)
        text = str(value).strip()
        if text.isdigit():
            return int(text)
        match = re.fullmatch(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
        if not match:
            return None
        year, month, day = (int(item) for item in match.groups())
        return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp())

    @staticmethod
    def _extract_version(filename: str) -> str | None:
        """从文件名中提取明确出现的四位年份作为版本号。"""
        matches = re.findall(r"(?:19|20)\d{2}", filename or "")
        return matches[-1] if matches else None
