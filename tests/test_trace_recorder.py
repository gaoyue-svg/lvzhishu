"""run/step trace 落库测试（doc 21 §4.5/§5.1）。"""

import asyncio
import unittest
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from backend.config import settings

from agent_service.orchestrator.run_state import MultiAgentRun, StepTrace
from agent_service.orchestrator.trace_recorder import (
    _derive_status,
    _summarize_agent_results,
    finalize_run,
    persist_run_trace,
)


class FakeSession:
    """模拟 AsyncSession：记录 add 的对象与 commit。"""

    def __init__(self) -> None:
        self.added: list[object] = []
        self.committed = False

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def _make_run(**overrides) -> MultiAgentRun:
    """构造带完整 step_traces / agent_results 的 run。"""
    run = MultiAgentRun(
        plan_id="plan-1",
        query="测试问题",
        trace_id="trace-1",
        intent={"entry_hint": "law_qa"},
        plan={"steps": []},
        review={"passed": True},
        final_answer="答案 [1]",
        final_citations=[{"index": 1, "text": "法条"}],
        needs_human_review=False,
    )
    run.step_traces.append(StepTrace(step_id="s1", agent="law_qa", status="success", latency_ms=12))
    run.agent_results.append(
        {
            "agent": "law_qa",
            "output_summary": "summary",
            "_step_id": "s1",
            "answer": "x" * 500,  # 超长答案应被截断
            "context_text": "LARGE",  # 不应进入摘要
            "chunks": ["big"],
        }
    )
    for key, value in overrides.items():
        setattr(run, key, value)
    return run


class TestStatusDerivation(unittest.TestCase):
    """状态推导。"""

    def test_error_wins(self):
        self.assertEqual(_derive_status(error="boom", needs_human_review=False), "failed")
        self.assertEqual(_derive_status(error="boom", needs_human_review=True), "failed")

    def test_hitl(self):
        self.assertEqual(_derive_status(error="", needs_human_review=True), "hitl")

    def test_success(self):
        self.assertEqual(_derive_status(error="", needs_human_review=False), "success")


class TestSummarize(unittest.TestCase):
    """Agent 产出摘要。"""

    def test_truncates_answer_and_drops_full_text(self):
        summary = _summarize_agent_results(_make_run().agent_results)[0]
        self.assertEqual(summary["agent"], "law_qa")
        self.assertEqual(summary["_step_id"], "s1")
        self.assertLessEqual(len(summary["answer"]), 200)
        self.assertNotIn("context_text", summary)
        self.assertNotIn("chunks", summary)


class TestPersistRunTrace(IsolatedAsyncioTestCase):
    """落库与 best-effort。"""

    @patch("backend.database.AsyncSessionLocal")
    async def test_persist_writes_row(self, session_factory):
        """正常路径：字段写入 + commit。"""
        fake = FakeSession()
        session_factory.return_value = fake
        run = _make_run()
        await persist_run_trace(run, {"conversation_id": "10", "user_id": "5"}, started=100.0, status="success", error="")
        self.assertTrue(fake.committed)
        self.assertEqual(len(fake.added), 1)
        row = fake.added[0]
        self.assertEqual(row.trace_id, "trace-1")
        self.assertEqual(row.conversation_id, 10)
        self.assertEqual(row.user_id, 5)
        self.assertEqual(row.status, "success")
        self.assertEqual(len(row.step_traces), 1)
        self.assertEqual(len(row.agent_results_summary), 1)
        self.assertEqual(row.needs_human_review, 0)

    @patch("backend.database.AsyncSessionLocal")
    async def test_persist_best_effort_on_db_error(self, session_factory):
        """DB 失败只 warning，不抛异常。"""
        session_factory.return_value.__aenter__ = AsyncMock(side_effect=RuntimeError("db down"))
        run = _make_run()
        await persist_run_trace(run, {"user_id": "1"}, started=0.0, status="success", error="")  # 不应抛出

    @patch("backend.config.settings.harness_enabled", False)
    async def test_disabled_skips(self, *args):
        """harness_enabled=False 直接跳过。"""
        with patch("backend.database.AsyncSessionLocal") as session_factory:
            await persist_run_trace(_make_run(), {"user_id": "1"}, started=0.0, status="success", error="")
            session_factory.assert_not_called()

    async def test_no_trace_id_skips(self):
        """无 trace_id 跳过落库。"""
        run = _make_run(trace_id="")
        with patch("backend.database.AsyncSessionLocal") as session_factory:
            await persist_run_trace(run, {}, started=0.0, status="success", error="")
            session_factory.assert_not_called()


class TestFinalizeRun(IsolatedAsyncioTestCase):
    """统一收尾入口。"""

    @patch("backend.config.settings.harness_enabled", False)
    async def test_disabled_returns_early(self, *args):
        """总开关关闭时快速返回。"""
        await finalize_run(_make_run(), {"user_id": "1"}, started=0.0)  # 不抛即可

    @patch("backend.config.settings.evaluation_enabled", False)
    @patch("backend.database.AsyncSessionLocal")
    async def test_finalize_persists_trace(self, session_factory, *args):
        """finalize 触发 run 落库。"""
        fake = FakeSession()
        session_factory.return_value = fake
        await finalize_run(_make_run(), {"conversation_id": "7", "user_id": "3"}, started=0.0)
        self.assertTrue(fake.committed)
        self.assertEqual(len(fake.added), 1)


if __name__ == "__main__":
    unittest.main()
