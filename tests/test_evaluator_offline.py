"""离线 LLM-as-Judge 测试（doc 21 Phase 3）：打分归一化、抽样、入队、落库。"""

import unittest
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from backend.config import settings

from agent_service.evaluator.judge import _normalize, judge_offline
from agent_service.evaluator.recorder import _sampled, enqueue_offline, record_offline


class TestNormalize(unittest.TestCase):
    """打分归一化。"""

    def test_clamps_and_overall(self):
        scores = _normalize({"grounded_score": 0.8, "hallucination": 0.1, "failed_claims": ["a"], "reason": "ok"})
        self.assertEqual(scores["grounded_score"], 0.8)
        self.assertEqual(scores["hallucination"], 0.1)
        self.assertEqual(scores["overall"], round((0.8 + 0.9) / 2, 4))
        self.assertEqual(scores["detail"]["failed_claims"], ["a"])

    def test_out_of_range_clamped(self):
        scores = _normalize({"grounded_score": 5, "hallucination": -3})
        self.assertEqual(scores["grounded_score"], 1.0)
        self.assertEqual(scores["hallucination"], 0.0)

    def test_non_numeric_defaults(self):
        scores = _normalize({"grounded_score": "bad", "hallucination": None})
        self.assertEqual(scores["grounded_score"], 0.5)
        self.assertEqual(scores["hallucination"], 0.5)


class FakeJudgeLLM:
    """judge 用的假 LLM。"""

    def __init__(self, payload=None, error: Exception | None = None):
        self.payload = payload or {"grounded_score": 0.7, "hallucination": 0.2}
        self.error = error

    async def chat_json(self, *args, **kwargs):
        if self.error is not None:
            raise self.error
        return self.payload


class TestJudgeOffline(IsolatedAsyncioTestCase):
    """judge_offline 打分。"""

    async def test_scores_answer(self):
        llm = FakeJudgeLLM()
        scores = await judge_offline("答案 [1]", [{"index": 1, "text": "法条"}], llm)
        self.assertEqual(scores["grounded_score"], 0.7)
        self.assertEqual(scores["hallucination"], 0.2)

    async def test_empty_answer_skips(self):
        scores = await judge_offline("", [], FakeJudgeLLM())
        self.assertIsNone(scores["grounded_score"])
        self.assertEqual(scores["detail"]["skipped"], "无最终答案")

    async def test_llm_error_skips(self):
        scores = await judge_offline("答案", [], FakeJudgeLLM(error=RuntimeError("boom")))
        self.assertIsNone(scores["grounded_score"])
        self.assertIn("skipped", scores["detail"])


class TestSampled(unittest.TestCase):
    """抽样判定。"""

    @patch.object(settings, "evaluation_sample_rate", 0.0)
    def test_zero_never_sampled(self):
        self.assertFalse(_sampled("trace-x"))

    @patch.object(settings, "evaluation_sample_rate", 1.0)
    def test_one_always_sampled(self):
        self.assertTrue(_sampled("trace-x"))

    @patch.object(settings, "evaluation_sample_rate", 0.05)
    def test_deterministic(self):
        self.assertEqual(_sampled("trace-x"), _sampled("trace-x"))
        # 少量样本中至少有一个被采样
        self.assertTrue(any(_sampled(f"trace-{i}") for i in range(50)))


class TestEnqueueOffline(IsolatedAsyncioTestCase):
    """入队离线评审。"""

    @patch.object(settings, "evaluation_sample_rate", 1.0)
    @patch("backend.database.redis_client", new_callable=AsyncMock)
    async def test_enqueues_when_sampled(self, redis):
        await enqueue_offline("trace-1", 3)
        redis.xadd.assert_awaited_once()

    @patch.object(settings, "evaluation_sample_rate", 0.0)
    @patch("backend.database.redis_client", new_callable=AsyncMock)
    async def test_skips_when_not_sampled(self, redis):
        await enqueue_offline("trace-1", 3)
        redis.xadd.assert_not_awaited()

    @patch.object(settings, "evaluation_sample_rate", 1.0)
    @patch("backend.database.redis_client", None)
    async def test_no_redis_skips(self, *args):
        await enqueue_offline("trace-1", 3)  # 不抛即可


class FakeSession:
    """模拟 AsyncSession：scalar 返回预设行，add 收集。"""

    def __init__(self, existing=None):
        self.existing = existing
        self.added: list[object] = []

    async def scalar(self, stmt):
        return self.existing

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class TestRecordOffline(IsolatedAsyncioTestCase):
    """离线分数落库 upsert。"""

    @patch("backend.database.AsyncSessionLocal")
    async def test_inserts_new_row(self, session_factory):
        fake = FakeSession(existing=None)
        session_factory.return_value = fake
        await record_offline("trace-1", 1, {"grounded_score": 0.8, "hallucination": 0.1, "overall": 0.85, "detail": {"reason": "ok"}})
        self.assertEqual(len(fake.added), 1)
        row = fake.added[0]
        self.assertEqual(row.mode, "offline")
        self.assertEqual(row.trace_id, "trace-1")
        self.assertEqual(row.grounded_score, 0.8)

    @patch("backend.database.AsyncSessionLocal")
    async def test_updates_existing_row(self, session_factory):
        existing = SimpleNamespace()
        fake = FakeSession(existing=existing)
        session_factory.return_value = fake
        await record_offline("trace-1", 1, {"grounded_score": 0.9, "hallucination": 0.05, "overall": 0.9, "detail": {}})
        self.assertEqual(len(fake.added), 0)
        self.assertEqual(existing.grounded_score, 0.9)

    async def test_invalid_scores_skips(self):
        with patch("backend.database.AsyncSessionLocal") as session_factory:
            await record_offline("trace-1", 1, {"grounded_score": None})
            session_factory.assert_not_called()


class SimpleNamespace:
    """轻量对象容器。"""

    def __init__(self):
        self.grounded_score = None
        self.hallucination = None
        self.overall = None
        self.detail = None


if __name__ == "__main__":
    unittest.main()
