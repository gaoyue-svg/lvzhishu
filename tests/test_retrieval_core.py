"""本文件测试上下文增强、父级规则摘要、路由、RRF、重排、引用与上下文构建。"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from backend.models.knowledge import KnowledgeChunk, KnowledgeDocument
from backend.services.parser import (
    _is_legacy_word_document,
    _markdown_to_law_text,
    _remove_repeated_page_boundaries,
    chunk_document,
    extract_metadata,
    parse_document,
)
from backend.worker.task_queue import TaskQueue
from embedding_service.embedding.context_enhancer import create_default_enhancer
from embedding_service.worker.embedding import (
    EmbeddingWorkItem,
    _upsert_vector_rows,
    _vectorize_missing_items,
)
from backend.services.law_parser import ChunkGenerator, LawParser
from rag_service.retrieval.citation import build_citations
from rag_service.retrieval.context_builder import ContextBuilder
from rag_service.retrieval.parent_chunk import ParentChunkBuilder
from rag_service.retrieval.query_rewrite import RuleQueryRewriter
from rag_service.retrieval.query_router import QueryRouter
from rag_service.retrieval.reranker import RuleLegalReranker
from rag_service.retrieval.retriever import HybridRetriever
from rag_service.routers.retrieval import _filter_relevant_law_results


class ParserMarkdownTests(unittest.IsolatedAsyncioTestCase):
    """验证 PDF/Word 先转 Markdown 再进入法律解析链路。"""

    def test_law_parser_builds_tree_before_chunking(self) -> None:
        """LawParser 应先建立编章节树,ChunkGenerator 再按法条边界切分。"""
        markdown = (
            "# 中华人民共和国测试法\n\n"
            "发布说明\n\n"
            "## 第一编 总则\n\n"
            "## 第一章 基本规定\n\n"
            "### 第一节 一般规定\n\n"
            "第一条 为了测试法律树解析，制定本法。\n\n"
            "第二条 本法适用于测试场景。"
        )
        tree = LawParser().parse(markdown)
        self.assertEqual(len(tree.iter_nodes("book")), 1)
        self.assertEqual(len(tree.iter_nodes("chapter")), 1)
        self.assertEqual(len(tree.iter_nodes("section")), 1)
        self.assertEqual([article.article_no for article in tree.articles], ["第一条", "第二条"])

        chunks = ChunkGenerator().generate(tree, chunk_size=1)
        article_chunks = [chunk for chunk in chunks if chunk["chunk_type"] == "article"]
        self.assertEqual(len(article_chunks), 2)
        self.assertEqual(article_chunks[0]["metadata"]["hierarchy_path"], "第一编 总则 > 第一章 基本规定 > 第一节 一般规定 > 第一条")
        self.assertEqual(article_chunks[0]["text"], "第一条 为了测试法律树解析，制定本法。")

    def test_cross_page_article_continuation_and_reference_are_not_split(self) -> None:
        """跨页枚举应归入原条文，后文条号引用不得生成重复 Article。"""
        markdown = (
            "第三十八条 用人单位有下列情形之一的，劳动者可以解除劳动合同：\n"
            "（一）未按照劳动合同约定提供劳动条件的；\n"
            "<!-- page:12 -->\n12\n"
            "（二）未及时足额支付劳动报酬的；\n"
            "第三十九条 劳动者有下列情形之一的，用人单位可以解除劳动合同。\n"
            "劳动者可以依照第三十八条的规定解除劳动合同。"
        )
        tree = LawParser().parse(markdown)
        article_numbers = [article.article_no for article in tree.articles]
        self.assertEqual(article_numbers, ["第三十八条", "第三十九条"])
        self.assertIn("（二）未及时足额支付劳动报酬的", tree.articles[0].text)
        self.assertNotIn("\n12\n", tree.articles[0].text)

    def test_repeated_headers_and_page_numbers_are_removed(self) -> None:
        """重复页眉和孤立页码应在进入法律解析器前被清除。"""
        pages = [
            (1, "公报 2019·1\n第一条 正文。\n— 162 —", []),
            (2, "公报 2019·1\n第二条 正文。\n— 163 —", []),
            (3, "公报 2019·1\n第三条 正文。\n— 164 —", []),
        ]
        cleaned = _remove_repeated_page_boundaries(pages)
        combined = "\n".join(text for _, text in cleaned)
        self.assertNotIn("公报 2019·1", combined)
        self.assertNotIn("163", combined)
        self.assertIn("第二条 正文。", combined)

    async def test_law_metadata_prefers_filename_over_pdf_fragment(self) -> None:
        """PDF 首行残句即使含“法”字，也不得被识别为法律名。"""
        metadata = await extract_metadata(
            "的处分；构成犯罪的，依法追究刑事责任：\n第二十一条 正文",
            "law",
            "《中华人民共和国劳动法》.pdf",
        )
        self.assertEqual(metadata["law_name"], "《中华人民共和国劳动法》")
        self.assertEqual(metadata["title"], "《中华人民共和国劳动法》")

    async def test_docx_markdown_can_feed_article_parser(self) -> None:
        """Word 标题转 Markdown 后仍应能切出法条并补齐层级。"""
        from docx import Document

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "test-law.docx"
            document = Document()
            document.add_heading("中华人民共和国测试法", level=1)
            document.add_heading("第一编 总则", level=2)
            document.add_heading("第一章 基本规定", level=2)
            document.add_heading("第一节 一般规定", level=3)
            document.add_paragraph("第一条 为了测试文档入库解析链路，制定本法。")
            document.save(path)

            markdown = await parse_document(str(path), "docx")
            self.assertIn("# 中华人民共和国测试法", markdown)
            self.assertIn("## 第一编 总则", markdown)

            chunks = await chunk_document(markdown, "law", filename="test-law.docx")
            article = next(chunk for chunk in chunks if chunk["chunk_type"] == "article")
            self.assertEqual(article["metadata"]["article"], "第一条")
            self.assertEqual(article["metadata"]["part_no"], "第一编")
            self.assertEqual(article["metadata"]["chapter_no"], "第一章")
            self.assertEqual(article["metadata"]["section_no"], "第一节")

    def test_legacy_word_magic_is_detected_even_with_docx_suffix(self) -> None:
        """扩展名错误的 Word 97-2003 文件应进入自动转换链路。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "legacy.docx"
            path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"legacy-word")
            self.assertTrue(_is_legacy_word_document(path))

            modern = Path(tmp_dir) / "modern.docx"
            modern.write_bytes(b"PK\x03\x04" + b"ooxml")
            self.assertFalse(_is_legacy_word_document(modern))

    def test_markdown_table_converts_as_single_text_block(self) -> None:
        """Markdown 表格应去掉分隔行并保留表头与数据行关系。"""
        text = _markdown_to_law_text(
            "| 编号 | 名称 |\n"
            "| --- | --- |\n"
            "| 第一条 | 总则 |\n"
        )
        self.assertIn("表格：", text)
        self.assertIn("编号\t名称", text)
        self.assertIn("第一条\t总则", text)
        self.assertNotIn("---", text)


class ModelSchemaTests(unittest.TestCase):
    """验证代码依赖的 ORM 字段不会被迁移或模型回退误删。"""

    def test_document_persists_raw_markdown(self) -> None:
        """解析 Worker 和父级重建依赖 raw_markdown 跨 Session 持久化。"""
        self.assertIn("raw_markdown", KnowledgeDocument.__table__.c)
        self.assertEqual(KnowledgeDocument.__table__.c.raw_markdown.comment, "解析后的Markdown原文")


class ContextEnhancerTests(unittest.IsolatedAsyncioTestCase):
    """验证叶子增强和父级跳过规则。"""

    async def test_law_enhancement_keeps_hierarchy_and_content(self) -> None:
        """法条增强应包含法律层级与原文。"""
        enhancer = create_default_enhancer(max_tokens=500)
        text = await enhancer.enhance(
            {
                "chunk_type": "law",
                "chunk_level": "article",
                "law_name": "中华人民共和国民法典",
                "part_no": "第二编",
                "part_title": "物权",
                "chapter_no": "第五章",
                "section_no": "第一节",
                "article_no": "第二百四十六条",
                "content": "矿藏、水流、海域属于国家所有。",
            }
        )
        self.assertIn("【中华人民共和国民法典】", text)
        self.assertIn("【第二百四十六条】", text)
        self.assertTrue(text.endswith("矿藏、水流、海域属于国家所有。"))

    async def test_parent_chunk_skips_enhancement(self) -> None:
        """父级 Chunk 应直接使用规则摘要正文。"""
        enhancer = create_default_enhancer(max_tokens=500)
        text = await enhancer.enhance(
            {"chunk_type": "law", "chunk_level": "chapter", "content": "【第五章】\n规则摘要"}
        )
        self.assertEqual(text, "【第五章】\n规则摘要")


class ParentChunkTests(unittest.TestCase):
    """验证父级稳定 ID 与规则摘要模板。"""

    def test_stable_parent_id(self) -> None:
        """节级稳定 ID 应严格遵守文档格式。"""
        uid = ParentChunkBuilder.build_parent_chunk_id(
            "civil_code_2025", "section", "第二编", "第五章", "第一节"
        )
        self.assertEqual(uid, "civil_code_2025:section:第二编:第五章:第一节")

    def test_section_summary_has_article_list(self) -> None:
        """节摘要应包含条数、主题与全部条号。"""
        text = ParentChunkBuilder().generate_section_content(
            {"section_no": "第一节", "section_title": "国家所有权"},
            [
                {"article_no": "第二百四十六条", "content": "矿藏、水流属于国家所有。"},
                {"article_no": "第二百四十七条", "content": "城市土地属于国家所有。"},
            ],
        )
        self.assertIn("本节包含 2 条", text)
        self.assertIn("第二百四十六条、第二百四十七条", text)

    def test_hierarchy_postprocessor_enriches_articles(self) -> None:
        """阶段三后处理应从原文标题回填 Article 的编章节路径。"""
        chunks = [
            {
                "chunk_type": "article",
                "text": "第二百四十六条 矿藏属于国家所有。",
                "metadata": {"article": "第二百四十六条"},
            }
        ]
        source = (
            "第二编 物权\n第五章 国家所有权和集体所有权\n"
            "第一节 国家所有权\n第二百四十六条 矿藏属于国家所有。"
        )
        ParentChunkBuilder.enrich_hierarchy_metadata(chunks, source)
        metadata = chunks[0]["metadata"]
        self.assertEqual(metadata["part_no"], "第二编")
        self.assertEqual(metadata["chapter_no"], "第五章")
        self.assertEqual(metadata["section_no"], "第一节")
        self.assertTrue(metadata["hierarchy_path"].endswith("第二百四十六条"))

    def test_effective_date_normalization(self) -> None:
        """Parser 的中文生效日期应转换为检索统一使用的 Unix 秒。"""
        timestamp = ParentChunkBuilder._to_unix_timestamp("2021年1月1日")
        self.assertEqual(timestamp, 1609459200)

    def test_parent_specs_build_book_chapter_and_section(self) -> None:
        """层级完整的 Article 应生成编、章、节三类父级。"""
        metadata = {
            "chunk_type": "law",
            "part_no": "第二编",
            "part_title": "物权",
            "chapter_no": "第五章",
            "chapter_title": "国家所有权",
            "section_no": "第一节",
            "section_title": "国家所有权",
            "article_no": "第二百四十六条",
            "content": "矿藏属于国家所有。",
        }
        chunks = [KnowledgeChunk(text=metadata["content"], metadata_=metadata)]
        document = SimpleNamespace(id=1, is_latest=True)
        specs = ParentChunkBuilder()._build_parent_specs(document, chunks)
        self.assertEqual({item["chunk_level"] for item in specs.values()}, {"book", "chapter", "section"})


class QueryAndRankingTests(unittest.IsolatedAsyncioTestCase):
    """验证查询重写、历史版本路由、RRF 与固定权重重排。"""

    async def test_rule_rewrite_and_historical_route(self) -> None:
        """口语应映射法律术语，历史问题应移除最新版过滤。"""
        rewritten = await RuleQueryRewriter().rewrite("2020年当时借钱不还怎么办")
        intent = await QueryRouter().route(rewritten.original_query)
        self.assertIn("民间借贷", rewritten.legal_query)
        self.assertEqual(intent.filters["version"], "2020")
        self.assertIsNone(intent.filters["is_latest"])

    async def test_default_rerank_formula(self) -> None:
        """默认分数应包含双路一致性和法律领域评分。"""
        ranked = await RuleLegalReranker().rerank(
            "测试",
            [
                {
                    "chunk_id": "1",
                    "milvus_score": 0.8,
                    "bm25_score": 0.6,
                    "metadata": {
                        "legal_level": "basic_law",
                        "chunk_level": "article",
                        "is_latest": True,
                    },
                }
            ],
        )
        self.assertAlmostEqual(ranked[0]["final_score"], 0.755)

    async def test_drunk_driving_query_expands_and_routes_to_criminal_domain(self) -> None:
        """醉驾口语应扩展到危险驾驶罪，并优先刑事法律领域。"""
        rewritten = await RuleQueryRewriter().rewrite("醉驾会被判刑吗？")
        intent = await QueryRouter().route(rewritten.original_query)
        self.assertIn("醉酒驾驶", rewritten.keyword_query)
        self.assertIn("危险驾驶罪", rewritten.entity_list)
        self.assertEqual(intent.filters["legal_domain"], "criminal")

    async def test_agreement_and_domain_make_correct_drunk_driving_article_rank_first(self) -> None:
        """双路命中的危险驾驶罪应排在仅命中“判刑”的一般条款之前。"""
        ranked = await RuleLegalReranker().rerank(
            "醉驾会被判刑吗？",
            [
                {
                    "chunk_id": "wrong",
                    "bm25_score": 1.0,
                    "text": "被判刑的犯罪分子又犯罪的，应当作出判决。",
                    "law_name": "中华人民共和国刑法",
                    "metadata": {"chunk_level": "article", "is_latest": True},
                },
                {
                    "chunk_id": "correct",
                    "bm25_score": 0.8,
                    "milvus_score": 0.65,
                    "text": "危险驾驶罪：醉酒驾驶机动车的，处拘役，并处罚金。",
                    "law_name": "中华人民共和国刑法",
                    "metadata": {"chunk_level": "article", "is_latest": True},
                },
            ],
            context={
                "query_keywords": ["醉酒驾驶", "危险驾驶罪", "拘役", "罚金"],
                "legal_domain": "criminal",
            },
        )
        self.assertEqual(ranked[0]["chunk_id"], "correct")

    def test_law_search_result_count_is_relevance_driven(self) -> None:
        """法规检索的 top_k 是上限，低相关结果不应为了凑数返回。"""
        results = [
            {"chunk_id": "1", "score": 0.80},
            {"chunk_id": "2", "score": 0.58},
            {"chunk_id": "3", "score": 0.40},
            {"chunk_id": "4", "score": 0.20},
        ]
        filtered = _filter_relevant_law_results(results)
        self.assertEqual([item["chunk_id"] for item in filtered], ["1"])

    def test_rrf_uses_router_weights(self) -> None:
        """双路共同命中的条目应累加两路 RRF 权重。"""
        merged = HybridRetriever._rrf_merge(
            [{"chunk_id": "1", "bm25_score": 1.0}],
            [{"chunk_id": "1", "milvus_score": 0.9}],
            {"bm25": 0.4, "semantic": 0.6},
        )
        self.assertAlmostEqual(merged[0]["rrf_score"], 1.0 / 61.0)

    def test_legal_candidates_deduplicate_same_document_article(self) -> None:
        """旧数据中同文档同条号的残缺片段应合并并保留最长正文。"""
        candidates = [
            {
                "chunk_id": "1", "document_id": 9, "text": "第一百八十八条第一款规定的普通诉讼时效",
                "rrf_score": 0.3, "metadata": {"article_no": "第一百八十八条", "hierarchy_path": "第一编 > 第九章 > 第一百八十八条"},
            },
            {
                "chunk_id": "2", "document_id": 9,
                "text": "第一百八十八条【普通诉讼时效】向人民法院请求保护民事权利的诉讼时效期间为三年。法律另有规定的，依照其规定。",
                "rrf_score": 0.2, "metadata": {"article_no": "第一百八十八条", "hierarchy_path": "第一编 > 第九章 > 第一百八十八条"},
            },
        ]
        deduplicated = HybridRetriever._deduplicate_legal_candidates(candidates)
        self.assertEqual(len(deduplicated), 1)
        self.assertEqual(deduplicated[0]["chunk_id"], "2")
        self.assertEqual(deduplicated[0]["rrf_score"], 0.3)

    async def test_hybrid_retriever_produces_full_empty_trace(self) -> None:
        """双路无命中时也应返回完整可调试 Trace，而不是抛出异常。"""

        class FakeBM25:
            async def search(self, *args, **kwargs):
                """返回空 BM25 命中。"""
                return []

        class FakeMilvus:
            def search(self, *args, **kwargs):
                """返回空 Milvus 命中。"""
                return []

        class FakeEmbedding:
            dimension = 3

            async def embed(self, texts):
                """返回固定三维查询向量。"""
                return [[0.1, 0.2, 0.3] for _ in texts]

        retriever = HybridRetriever(
            bm25=FakeBM25(),
            milvus=FakeMilvus(),
            embedding=FakeEmbedding(),
            reranker=RuleLegalReranker(),
            query_rewriter=RuleQueryRewriter(),
            query_router=QueryRouter(),
            db=None,
        )
        result = await retriever.retrieve("矿藏属于谁", ["1"])
        self.assertEqual(result.chunks, [])
        self.assertIn("reranked_results", result.trace)
        self.assertEqual(result.trace["milvus_query_vector_dim"], 3)


class CitationAndContextTests(unittest.IsolatedAsyncioTestCase):
    """验证引用定位字段和带编号上下文。"""

    async def test_citation_and_context(self) -> None:
        """引用应保留页码与可空字符偏移，上下文编号应对应引用。"""
        chunks = [
            {
                "chunk_id": "1",
                "text": "矿藏、水流、海域属于国家所有。",
                "final_score": 0.9,
                "metadata": {
                    "law_name": "中华人民共和国民法典",
                    "article_no": "第二百四十六条",
                    "page_start": 32,
                    "page_end": 32,
                    "char_start": None,
                    "char_end": None,
                    "source_uri": "documents/civil-code.pdf",
                },
            }
        ]
        citations = await build_citations(chunks)
        context = await ContextBuilder().build(chunks, citations, max_tokens=100)
        self.assertEqual(citations[0]["page_start"], 32)
        self.assertIsNone(citations[0]["char_start"])
        self.assertTrue(context.context_text.startswith("[1]"))
        self.assertEqual(context.citation_map[1]["chunk_id"], "1")


class TaskQueueTests(unittest.TestCase):
    """验证 Redis Stream 坏消息不会在反序列化阶段击穿 Worker 主循环。"""

    def test_invalid_payload_is_marked(self) -> None:
        """非法 JSON 应转换为可单条失败处理的标记对象。"""
        self.assertEqual(TaskQueue._decode_payload("not-json"), {"_invalid_payload": True})


class EmbeddingWorkerBatchTests(unittest.IsolatedAsyncioTestCase):
    """验证 Embedding Worker 的批量向量化与批量入库辅助逻辑。"""

    async def test_vectorization_dedupes_cache_and_batches(self) -> None:
        """缓存命中和重复 content_hash 不应重复请求 Embedding API。"""

        class FakeEmbedding:
            dimension = 3

            def __init__(self) -> None:
                self.calls: list[list[str]] = []

            async def embed(self, texts):
                self.calls.append(list(texts))
                return [[float(len(text)), 0.0, 1.0] for text in texts]

        embedding = FakeEmbedding()
        document = SimpleNamespace(id=10, user_id=20)
        items = [
            _make_embedding_item(1, "cached", "cached text"),
            _make_embedding_item(2, "h1", "text one"),
            _make_embedding_item(3, "h2", "text two"),
            _make_embedding_item(4, "h1", "text one duplicated"),
            _make_embedding_item(5, "h3", "text three"),
        ]
        cached = {"cached": [0.1, 0.2, 0.3], "h1": None, "h2": None, "h3": None}

        result = await _vectorize_missing_items(
            embedding=embedding,
            work_items=items,
            cached=cached,
            batch_size=2,
            document=document,
            provider="fake",
            model_name="fake-embedding",
        )

        self.assertEqual(embedding.calls, [["text one", "text two"], ["text three"]])
        self.assertEqual(result.vector_by_hash["cached"], [0.1, 0.2, 0.3])
        self.assertIn("h1", result.vector_by_hash)
        self.assertIn("h3", result.new_cache)
        self.assertEqual(result.errors, [])
        self.assertFalse(result.aborted_by_permanent_error)

    async def test_upsert_vectors_batches_rows_and_sets_vector_ids(self) -> None:
        """Milvus 写入应按批执行,并把返回主键写回各 Chunk。"""

        class FakeMilvus:
            def __init__(self) -> None:
                self.calls: list[list[str]] = []

            def upsert(self, rows):
                self.calls.append([row["chunk_id"] for row in rows])
                return [f"vector-{row['chunk_id']}" for row in rows]

        milvus = FakeMilvus()
        document = SimpleNamespace(id=10, user_id=20, version="v1", is_latest=True)
        items = [_make_embedding_item(index, f"h{index}", f"text {index}") for index in range(1, 6)]
        vectors = {f"h{index}": [0.1, 0.2, 0.3] for index in range(1, 6)}

        result = await _upsert_vector_rows(
            milvus=milvus,
            document=document,
            work_items=items,
            vector_by_hash=vectors,
            batch_size=2,
        )

        self.assertEqual(milvus.calls, [["1", "2"], ["3", "4"], ["5"]])
        self.assertEqual(result.success_count, 5)
        self.assertEqual(result.errors, [])
        self.assertEqual(len(result.bm25_chunks), 5)
        self.assertEqual([item.chunk.vector_id for item in items], [f"vector-{index}" for index in range(1, 6)])

    async def test_qwen_vectorization_clamps_batch_size_to_service_limit(self) -> None:
        """Qwen/DashScope Embedding 单批不应超过 20 条。"""

        class FakeQwenEmbedding:
            dimension = 3

            def __init__(self) -> None:
                self.calls: list[int] = []

            async def embed(self, texts):
                self.calls.append(len(texts))
                if len(texts) > 20:
                    raise AssertionError("Qwen batch limit exceeded")
                return [[1.0, 0.0, 0.0] for _ in texts]

        embedding = FakeQwenEmbedding()
        document = SimpleNamespace(id=10, user_id=20)
        items = [
            _make_embedding_item(index, f"h{index}", f"text {index}")
            for index in range(1, 26)
        ]
        cached = {item.content_hash: None for item in items}

        result = await _vectorize_missing_items(
            embedding=embedding,
            work_items=items,
            cached=cached,
            batch_size=100,
            document=document,
            provider="qwen",
            model_name="qwen3.7-text-embedding",
        )

        self.assertEqual(embedding.calls, [20, 5])
        self.assertEqual(len(result.vector_by_hash), 25)
        self.assertEqual(result.errors, [])
        self.assertFalse(result.aborted_by_permanent_error)

    async def test_vectorization_retries_smaller_batch_from_server_limit_error(self) -> None:
        """服务端返回 batch limit 时应拆成小批重试。"""

        class BatchLimitError(Exception):
            status_code = 400

        class FakeLimitedEmbedding:
            dimension = 3

            def __init__(self) -> None:
                self.calls: list[int] = []

            async def embed(self, texts):
                self.calls.append(len(texts))
                if len(texts) > 20:
                    raise BatchLimitError(
                        "Value error, batch size is invalid, it should not be larger than 20."
                    )
                return [[1.0, 0.0, 0.0] for _ in texts]

        embedding = FakeLimitedEmbedding()
        document = SimpleNamespace(id=10, user_id=20)
        items = [
            _make_embedding_item(index, f"h{index}", f"text {index}")
            for index in range(1, 26)
        ]
        cached = {item.content_hash: None for item in items}

        result = await _vectorize_missing_items(
            embedding=embedding,
            work_items=items,
            cached=cached,
            batch_size=100,
            document=document,
            provider="unknown",
            model_name="unknown-embedding",
        )

        self.assertEqual(embedding.calls, [25, 20, 5])
        self.assertEqual(len(result.vector_by_hash), 25)
        self.assertEqual(result.errors, [])
        self.assertFalse(result.aborted_by_permanent_error)


def _make_embedding_item(chunk_id: int, content_hash: str, text: str) -> EmbeddingWorkItem:
    """构造不依赖数据库 Session 的 Worker 测试项。"""
    chunk = SimpleNamespace(
        id=chunk_id,
        text=text,
        kb_id=100,
        document_id=10,
        chunk_type="paragraph",
        chunk_subtype=None,
        chunk_level="paragraph",
        metadata_={},
        vector_id=None,
    )
    return EmbeddingWorkItem(
        chunk=chunk,
        metadata={"tenant_id": "20", "content": text},
        enhanced_text=text,
        content_hash=content_hash,
    )


if __name__ == "__main__":
    unittest.main()
