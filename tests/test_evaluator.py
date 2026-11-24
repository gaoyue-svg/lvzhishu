"""在线确定性评估测试（doc 21 §4.2）。"""

import unittest
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from backend.config import settings

from agent_service.evaluator.online import compute_citation_score, compute_coverage, compute_online_scores
from agent_service.evaluator.recorder import record_online
from agent_service.orchestrator.run_state import MultiAgentRun


class TestCitationScore(unittest.TestCase):
    """引用编号完整性。"""

    def test_no_refs_is_perfect(self):
        self.assertEqual(compute_citation_score("答案", []), 1.0)

    def test_all_refs_valid(self):
        citations = [{"index": 1}, {"index": 2}]
        self.assertEqual(compute_citation_score("答案 [1][2]", citations), 1.0)

    def test_missing_ref_lowers(self):
        citations = [{"index": 1}, {"index": 2}]
        self.assertEqual(compute_citation_score("答案 [1][9]", citations), 0.5)

    def test_refs_without_any_citation(self):
        self.assertEqual(compute_citation_score("答案 [1]", []), 0.0)


class TestCoverage(unittest.TestCase):
    """引用覆盖度。"""

    def test_no_citations_is_perfect(self):
        self.assertEqual(compute_coverage("答案", []), 1.0)

    def test_all_citations_used(self):
        citations = [{"index": 1}, {"index": 2}]
        self.assertEqual(compute_coverage("答案 [1][2]", citations), 1.0)

    def test_partial_usage(self):
        citations = [{"index": 1}, {"index": 2}, {"index": 3}]
        self.assertEqual(compute_coverage("答案 [1]", citations), round(1 / 3, 4))

    def test_none_used(self):
        citations = [{"index": 1}, {"index": 2}]
        self.assertEqual(compute_coverage("无引用", citations), 0.0)


class TestOnlineScores(unittest.TestCase):
    """汇总 + detail 明细。"""

    def test_detail_lists_failed_refs(self):
        scores = compute_online_scores("答案 [1][8]", [{"index": 1}])
        self.assertEqual(scores["detail"]["failed_refs"], [8])
        self.assertEqual(scores["citation_score"], 0.5)
        # coverage = used(1) / total(1) = 1.0；overall = 0.5*0.5 + 0.5*1.0 = 0.75
        self.assertEqual(scores["overall"], 0.75)


class FakeSession:
    """模拟 AsyncSession。"""

    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class TestRecordOnline(IsolatedAsyncioTestCase):
    """在线评估落库。"""

    @patch("backend.database.AsyncSessionLocal")
    async def test_record_writes_online_row(self, session_factory):
        fake = FakeSession()
        session_factory.return_value = fake
        run = MultiAgentRun(plan_id="p", query="q", trace_id="trace-x", final_answer="答案 [1]", final_citations=[{"index": 1}])
        await record_online(run, {})
        self.assertEqual(len(fake.added), 1)
        row = fake.added[0]
        self.assertEqual(row.mode, "online")
        self.assertEqual(row.citation_score, 1.0)
        self.assertEqual(row.coverage, 1.0)
        self.assertEqual(row.trace_id, "trace-x")

    @patch("backend.config.settings.evaluation_enabled", False)
    async def test_disabled_skips(self, *args):
        with patch("backend.database.AsyncSessionLocal") as session_factory:
            run = MultiAgentRun(plan_id="p", query="q", trace_id="trace-x")
            await record_online(run, {})
            session_factory.assert_not_called()

    @patch("backend.database.AsyncSessionLocal")
    async def test_db_error_best_effort(self, session_factory):
        session_factory.return_value.__aenter__ = AsyncMock(side_effect=RuntimeError("down"))
        run = MultiAgentRun(plan_id="p", query="q", trace_id="trace-x")
        await record_online(run, {})  # 不抛


if __name__ == "__main__":
    unittest.main()
