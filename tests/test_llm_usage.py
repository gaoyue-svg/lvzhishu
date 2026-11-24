"""LLM 用量采集与落库测试（doc 21 §4.3/§5.2）。"""

import asyncio
import unittest
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from agent_service.llm.usage import (
    LlmUsageRecord,
    UsageCollector,
    estimate_cost,
    flush_usage,
    get_current_collector,
    record_usage,
    reset_usage_collector,
    set_usage_collector,
)
from agent_service.llm.providers.openai_provider import OpenAICompatibleLLM


class TestCollector(unittest.TestCase):
    """收集器与成本估算。"""

    def test_add_and_total(self):
        collector = UsageCollector()
        collector.add(LlmUsageRecord(provider="deepseek", model="deepseek-chat", prompt_tokens=10, completion_tokens=5))
        self.assertEqual(len(collector.records), 1)
        self.assertEqual(collector.total_tokens, 15)

    def test_estimate_cost_known_model(self):
        cost = estimate_cost("deepseek-chat", 1000, 1000)
        self.assertGreater(cost, 0)

    def test_estimate_cost_unknown_model(self):
        self.assertEqual(estimate_cost("unknown-model", 1000, 1000), 0.0)

    def test_record_usage_without_collector_noop(self):
        """未绑定 collector 时忽略（避免误入别处 collector）。"""
        record_usage(provider="deepseek", model="deepseek-chat", prompt_tokens=1, completion_tokens=1)
        self.assertIsNone(get_current_collector())


class TestProviderCapture(IsolatedAsyncioTestCase):
    """provider 层采集真实 usage。"""

    def _make_llm(self, create_result):
        client = AsyncMock()
        client.chat.completions.create.return_value = create_result
        return OpenAICompatibleLLM("test-model", client=client)

    async def test_chat_captures_usage(self):
        usage = MagicMock()
        usage.prompt_tokens = 10
        usage.completion_tokens = 5
        resp = MagicMock()
        resp.choices = [MagicMock(message=MagicMock(content="hi"))]
        resp.usage = usage
        llm = self._make_llm(resp)

        collector = UsageCollector()
        token = set_usage_collector(collector)
        try:
            content = await llm.chat([{"role": "user", "content": "你好"}])
        finally:
            reset_usage_collector(token)
        self.assertEqual(content, "hi")
        self.assertEqual(len(collector.records), 1)
        record = collector.records[0]
        self.assertEqual(record.prompt_tokens, 10)
        self.assertEqual(record.completion_tokens, 5)
        self.assertEqual(record.provider, "openai")
        self.assertEqual(record.model, "test-model")

    async def test_stream_estimates_tokens(self):
        async def _chunks():
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content="答"))])
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content="案"))])

        client = AsyncMock()
        client.chat.completions.create.return_value = _chunks()
        llm = OpenAICompatibleLLM("test-model", client=client)

        collector = UsageCollector()
        token = set_usage_collector(collector)
        try:
            parts = [piece async for piece in llm.stream([{"role": "user", "content": "问题"}])]
        finally:
            reset_usage_collector(token)
        self.assertEqual("".join(parts), "答案")
        self.assertEqual(len(collector.records), 1)
        record = collector.records[0]
        self.assertGreaterEqual(record.prompt_tokens + record.completion_tokens, 1)


class FakeSession:
    """模拟 AsyncSession。"""

    def __init__(self) -> None:
        self.added: list[object] = []
        self.committed = False

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def add_all(self, objs: list[object]) -> None:
        self.added.extend(objs)

    async def commit(self) -> None:
        self.committed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class TestFlushUsage(IsolatedAsyncioTestCase):
    """冲刷到 llm_usage 表。"""

    @patch("backend.database.AsyncSessionLocal")
    async def test_flush_writes_rows(self, session_factory):
        fake = FakeSession()
        session_factory.return_value = fake
        collector = UsageCollector()
        collector.add(LlmUsageRecord(provider="deepseek", model="deepseek-chat", prompt_tokens=10, completion_tokens=5, purpose="agent"))
        await flush_usage(collector, trace_id="trace-1", user_id=3)
        self.assertTrue(fake.committed)
        self.assertEqual(len(fake.added), 1)
        row = fake.added[0]
        self.assertEqual(row.trace_id, "trace-1")
        self.assertEqual(row.user_id, 3)
        self.assertEqual(row.total_tokens, 15)
        self.assertEqual(row.purpose, "agent")

    @patch("backend.database.AsyncSessionLocal")
    async def test_flush_best_effort_on_error(self, session_factory):
        session_factory.return_value.__aenter__ = AsyncMock(side_effect=RuntimeError("db down"))
        collector = UsageCollector()
        collector.add(LlmUsageRecord(provider="deepseek", model="deepseek-chat"))
        await flush_usage(collector, trace_id="trace-1")  # 不抛

    async def test_flush_empty_noop(self):
        with patch("backend.database.AsyncSessionLocal") as session_factory:
            await flush_usage(None, trace_id="trace-1")
            await flush_usage(UsageCollector(), trace_id="trace-1")
            session_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
