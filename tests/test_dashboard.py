"""首页业务统计规则测试。"""

import unittest
from unittest.mock import AsyncMock, MagicMock

from backend.services.dashboard import (
    _build_stats,
    _get_activity_counts,
    _get_system_status,
    _get_usage_trend,
    _is_document_generation_query,
)


class DashboardIntentTests(unittest.TestCase):
    """文书生成应按用户真实请求统计，而不依赖 Supervisor 会话类型。"""

    def test_document_generation_requests(self) -> None:
        self.assertTrue(_is_document_generation_query("生成一份劳动合同"))
        self.assertTrue(_is_document_generation_query("请给我离婚诉讼书的模板"))
        self.assertTrue(_is_document_generation_query("帮我起草一份律师函"))

    def test_general_legal_questions_are_not_documents(self) -> None:
        self.assertFalse(_is_document_generation_query("劳动合同解除需要支付多少补偿"))
        self.assertFalse(_is_document_generation_query("我需要保存什么证据吗"))


class DashboardStatsTests(unittest.IsolatedAsyncioTestCase):
    def test_contracts_and_documents_are_merged(self) -> None:
        stats = _build_stats(kb_count=3, ai_calls=61, contracts=7, documents=6, legal_searches=9)

        self.assertEqual([item.label for item in stats], ["AI调用次数", "知识库数量", "合同与文书", "法规检索次数"])
        self.assertEqual(stats[2].value, 13)
        self.assertEqual(stats[2].unit, "份")
        self.assertEqual(stats[3].value, 9)
        self.assertEqual(stats[3].unit, "次")

    async def test_activity_counts_include_real_legal_search_traces(self) -> None:
        db = MagicMock()
        db.scalar = AsyncMock(side_effect=[61, 7, 9])
        messages = MagicMock()
        messages.__iter__.return_value = iter(["请生成一份劳动合同", "普通法律问题"])
        db.scalars = AsyncMock(return_value=messages)

        counts = await _get_activity_counts(db, user_id=1)

        self.assertEqual(counts, {"ai_calls": 61, "contracts": 7, "documents": 1, "legal_searches": 9})


class DashboardTrendTests(unittest.IsolatedAsyncioTestCase):
    """趋势区间必须真正改变查询窗口和返回点数。"""

    async def test_supported_ranges_return_matching_point_count(self) -> None:
        empty_result = MagicMock()
        empty_result.all.return_value = []
        for days in (7, 14, 30):
            db = MagicMock()
            db.execute = AsyncMock(side_effect=[empty_result, empty_result, empty_result, empty_result])
            points = await _get_usage_trend(db, user_id=1, days=days)
            self.assertEqual(len(points), days)

    async def test_unsupported_range_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            await _get_usage_trend(MagicMock(), user_id=1, days=8)


class DashboardSystemStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_system_status_uses_real_user_data(self) -> None:
        rag_result = MagicMock()
        rag_result.scalars.return_value.all.return_value = [120, 80]
        document_result = MagicMock()
        document_result.all.return_value = [
            ("completed", "completed"),
            ("completed", "processing"),
            ("failed", "failed"),
        ]
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[rag_result, document_result])

        statuses = await _get_system_status(db, user_id=7)

        self.assertEqual([item.label for item in statuses], ["RAG检索", "Embedding队列", "文档解析"])
        self.assertEqual(statuses[0].value, 100)
        self.assertIn("完成 2 次", statuses[0].description)
        self.assertIn("平均 100 ms", statuses[0].description)
        self.assertTrue(statuses[0].has_data)
        self.assertEqual(statuses[1].value, 33)
        self.assertIn("完成 1", statuses[1].description)
        self.assertIn("处理中 1", statuses[1].description)
        self.assertIn("失败 1", statuses[1].description)
        self.assertEqual(statuses[2].value, 67)

    async def test_system_status_distinguishes_no_data_from_zero_percent(self) -> None:
        rag_result = MagicMock()
        rag_result.scalars.return_value.all.return_value = []
        document_result = MagicMock()
        document_result.all.return_value = []
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[rag_result, document_result])

        statuses = await _get_system_status(db, user_id=7)

        self.assertEqual(statuses[0].description, "近24小时暂无检索记录")
        self.assertEqual(statuses[1].description, "暂无向量化文档")
        self.assertEqual(statuses[2].description, "暂无解析文档")
        self.assertTrue(all(item.has_data is False for item in statuses))


if __name__ == "__main__":
    unittest.main()
