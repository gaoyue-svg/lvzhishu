"""本文件测试阶段四 LLMFactory 与 OpenAI 兼容大模型客户端基础能力。"""

from __future__ import annotations

import unittest

from agent_service.llm import LLMFactory, LLMMessage
from agent_service.llm.providers.openai_provider import OpenAICompatibleLLM


class FakeStream:
    """模拟 OpenAI SDK 的异步流式返回。"""

    def __init__(self, chunks):
        """保存待返回的流式 chunk。"""
        self.chunks = list(chunks)

    def __aiter__(self):
        """返回异步迭代器自身。"""
        return self

    async def __anext__(self):
        """逐个返回模拟 chunk。"""
        if not self.chunks:
            raise StopAsyncIteration
        return self.chunks.pop(0)


class FakeCompletions:
    """记录请求参数并返回预设响应。"""

    def __init__(self, response):
        """保存模拟响应。"""
        self.response = response
        self.calls = []

    async def create(self, **kwargs):
        """模拟 chat.completions.create。"""
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            return FakeStream(self.response)
        return self.response


class FakeClient:
    """提供 OpenAI SDK 兼容的 chat.completions 结构。"""

    def __init__(self, response):
        """初始化模拟客户端。"""
        self.chat = type("FakeChat", (), {"completions": FakeCompletions(response)})()


class LLMFactoryTests(unittest.IsolatedAsyncioTestCase):
    """覆盖 LLM 工厂和 provider 的核心调用约定。"""

    def test_builtin_providers_registered(self) -> None:
        """内置 provider 应在导入时注册。"""
        self.assertIn("openai", LLMFactory.providers())
        self.assertIn("deepseek", LLMFactory.providers())
        self.assertIn("qwen", LLMFactory.providers())

    def test_factory_creates_openai_compatible_llm(self) -> None:
        """Factory 应能创建 OpenAI 兼容客户端。"""
        llm = LLMFactory.create("openai", "gpt-test", client=FakeClient({"choices": []}))
        self.assertIsInstance(llm, OpenAICompatibleLLM)
        self.assertEqual(llm.model_name, "gpt-test")

    async def test_chat_returns_text_and_sends_defaults(self) -> None:
        """chat 应返回文本，并带上模型、温度和 token 配置。"""
        fake = FakeClient({"choices": [{"message": {"content": "你好"}}]})
        llm = LLMFactory.create(
            "openai",
            "gpt-test",
            client=fake,
            default_temperature=0.2,
            default_max_tokens=128,
        )
        text = await llm.chat([LLMMessage(role="user", content="hi")])
        call = fake.chat.completions.calls[0]
        self.assertEqual(text, "你好")
        self.assertEqual(call["model"], "gpt-test")
        self.assertEqual(call["temperature"], 0.2)
        self.assertEqual(call["max_tokens"], 128)
        self.assertFalse(call["stream"])

    async def test_chat_json_parses_object(self) -> None:
        """chat_json 应启用 JSON response_format 并解析对象。"""
        fake = FakeClient({"choices": [{"message": {"content": '{"agent":"law_qa"}'}}]})
        llm = LLMFactory.create("openai", "gpt-test", client=fake)
        payload = await llm.chat_json("system", "user")
        call = fake.chat.completions.calls[0]
        self.assertEqual(payload["agent"], "law_qa")
        self.assertEqual(call["response_format"], {"type": "json_object"})

    async def test_stream_yields_text_chunks(self) -> None:
        """stream 应把 provider chunk 转成纯文本增量。"""
        fake = FakeClient([
            {"choices": [{"delta": {"content": "你"}}]},
            {"choices": [{"delta": {"content": "好"}}]},
            {"choices": [{"delta": {}}]},
        ])
        llm = LLMFactory.create("openai", "gpt-test", client=fake)
        chunks = [chunk async for chunk in llm.stream([{"role": "user", "content": "hi"}])]
        self.assertEqual(chunks, ["你", "好"])
        self.assertTrue(fake.chat.completions.calls[0]["stream"])

    async def test_chat_with_tools_standardizes_tool_calls(self) -> None:
        """chat_with_tools 应屏蔽 OpenAI tool_calls 原始结构差异。"""
        fake = FakeClient(
            {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "function": {
                                        "name": "search_law",
                                        "arguments": '{"query":"民法典"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        )
        llm = LLMFactory.create("openai", "gpt-test", client=fake)
        result = await llm.chat_with_tools(
            [{"role": "user", "content": "查法条"}],
            tools=[{"type": "function", "function": {"name": "search_law"}}],
        )
        self.assertIsNone(result.content)
        self.assertEqual(result.tool_calls[0].id, "call_1")
        self.assertEqual(result.tool_calls[0].name, "search_law")
        self.assertEqual(result.tool_calls[0].args["query"], "民法典")


if __name__ == "__main__":
    unittest.main()
