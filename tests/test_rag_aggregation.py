"""RAG 指标聚合测试（doc 21 Phase 3）。"""

import unittest
from unittest import IsolatedAsyncioTestCase

from agent_service.metrics.rag_aggregation import aggregate_rag_metrics


class FakeRow:
    """模拟 rag_trace 查询行。"""

    def __init__(self, total_latency_ms, retrieval_latency_ms, citation_count, merged_results):
        self.total_latency_ms = total_latency_ms
        self.retrieval_latency_ms = retrieval_latency_ms
        self.citation_count = citation_count
        self.merged_results = merged_results


class FakeDB:
    """模拟 db.execute 返回行。"""

    def __init__(self, rows):
        self.rows = rows

    async def execute(self, statement):
        return self

    def all(self):
        return self.rows


class TestRagAggregation(IsolatedAsyncioTestCase):
    """聚合逻辑。"""

    async def test_empty(self):
        result = await aggregate_rag_metrics(FakeDB([]))
        self.assertEqual(result["total_retrievals"], 0)
        self.assertEqual(result["citation_rate"], 0.0)

    async def test_computes_metrics(self):
        rows = [
            FakeRow(100, 50, 2, [{"chunk_id": "1"}, {"chunk_id": "2"}, {"chunk_id": "3"}]),
            FakeRow(200, 80, 0, [{"chunk_id": "1"}]),
            FakeRow(300, 100, 1, [{"chunk_id": "1"}, {"chunk_id": "2"}]),
        ]
        result = await aggregate_rag_metrics(FakeDB(rows))
        self.assertEqual(result["total_retrievals"], 3)
        self.assertEqual(result["citation_rate"], round(2 / 3, 4))  # 有引用的 2/3
        self.assertEqual(result["avg_citation_count"], 1.0)         # (2+0+1)/3
        self.assertEqual(result["avg_total_latency_ms"], 200.0)
        self.assertEqual(result["avg_retrieval_latency_ms"], round((50 + 80 + 100) / 3, 1))
        # precision_proxy = avg_citation / avg_retrieved = 1.0 / ((3+1+2)/3) = 1/2
        self.assertEqual(result["precision_proxy"], 0.5)


if __name__ == "__main__":
    unittest.main()
