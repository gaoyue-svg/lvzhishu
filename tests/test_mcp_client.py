"""本文件测试 MCP 客户端（doc 20 必应中文搜索 MCP 接入）：归一化、白名单、降级契约。

使用 mock ClientSession，不依赖真实网络；WebSearchTool 的 bing_mcp 分支验证 Agent 零改动。
"""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agent_service.mcp.client import MCPClientManager, get_mcp_manager, set_mcp_manager
from agent_service.tools.web_search import WebSearchTool, _normalize_search_result
from backend.config import settings


class FakeBlock:
    """模拟 MCP TextContent 块。"""

    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class FakeResult:
    """模拟 mcp.CallToolResult。"""

    def __init__(self, text: str | None = None, structured=None, is_error: bool = False) -> None:
        self.content = [FakeBlock(text)] if text is not None else []
        self.structuredContent = structured
        self.is_error = is_error


class FakeSession:
    """模拟 mcp.ClientSession，支持 call_tool / list_tools。"""

    def __init__(self, results=None, tools=None) -> None:
        self._results = list(results or [])
        self._tools = tools or [
            SimpleNamespace(name="bing_search", description="必应搜索", input_schema={"type": "object"})
        ]

    async def call_tool(self, name, arguments=None):
        if self._results:
            return self._results.pop(0)
        return FakeResult(text='{"query":"q","results":[]}')

    async def list_tools(self):
        return SimpleNamespace(tools=self._tools)

    async def initialize(self):
        return SimpleNamespace(serverInfo=SimpleNamespace(name="mock", version="1"))


class TestMCPClient(unittest.IsolatedAsyncioTestCase):
    """MCPClientManager 归一化与白名单。"""

    async def test_call_tool_normalizes_text_json(self):
        mgr = MCPClientManager(server_url="http://x", timeout=5)
        fake = FakeSession(
            results=[FakeResult(text='{"query":"q","results":[{"title":"A","url":"http://a","snippet":"aa"}]}')]
        )
        with patch.object(MCPClientManager, "_connect", new_callable=AsyncMock) as connect:
            connect.side_effect = lambda: setattr(mgr, "_session", fake)
            raw = await mgr.call_tool("bing_search", {"query": "q"})
        self.assertEqual(raw["query"], "q")
        self.assertEqual(len(raw["results"]), 1)

    async def test_call_tool_prefers_structured_content(self):
        mgr = MCPClientManager(server_url="http://x", timeout=5)
        fake = FakeSession(results=[FakeResult(structured={"results": [{"title": "S"}]})])
        with patch.object(MCPClientManager, "_connect", new_callable=AsyncMock) as connect:
            connect.side_effect = lambda: setattr(mgr, "_session", fake)
            raw = await mgr.call_tool("bing_search", {"query": "q"})
        self.assertEqual(raw["results"][0]["title"], "S")

    async def test_whitelist_rejects_unknown_tool(self):
        mgr = MCPClientManager(server_url="http://x", allowed_tools={"bing_search"})
        with self.assertRaises(ValueError):
            await mgr.call_tool("evil_tool", {})

    async def test_call_tool_raises_on_error_result(self):
        mgr = MCPClientManager(server_url="http://x", timeout=5, retry=0)
        fake = FakeSession(results=[FakeResult(text="err", is_error=True)])
        with patch.object(MCPClientManager, "_connect", new_callable=AsyncMock) as connect:
            connect.side_effect = lambda: setattr(mgr, "_session", fake)
            with self.assertRaises(RuntimeError):
                await mgr.call_tool("bing_search", {"query": "q"})

    async def test_connect_failure_returns_false(self):
        mgr = MCPClientManager(server_url="http://x", timeout=5, retry=0)
        with patch.object(MCPClientManager, "_connect", new_callable=AsyncMock, side_effect=RuntimeError("no server")):
            self.assertFalse(await mgr.ensure_connected())


class TestNormalizeSearchResult(unittest.TestCase):
    """bing_search 返回归一化为 WebSearchTool 契约。"""

    def test_maps_citations(self):
        raw = {
            "query": "q",
            "results": [{"title": "A", "url": "http://a", "snippet": "摘要内容"}],
            "totalResults": 1,
        }
        norm = _normalize_search_result(raw, 5)
        self.assertTrue(norm["available"])
        self.assertEqual(len(norm["citations"]), 1)
        cite = norm["citations"][0]
        self.assertEqual(cite["source_type"], "web")
        self.assertEqual(cite["title"], "A")
        self.assertEqual(cite["url"], "http://a")
        self.assertEqual(cite["text"], "摘要内容")

    def test_empty_results(self):
        norm = _normalize_search_result({"query": "q", "results": []}, 5)
        self.assertTrue(norm["available"])
        self.assertEqual(norm["citations"], [])


class TestWebSearchBingMcp(unittest.IsolatedAsyncioTestCase):
    """WebSearchTool bing_mcp 分支：Agent 零改动 + 降级契约。"""

    async def test_bing_mcp_degrades_when_not_initialized(self):
        tool = WebSearchTool()
        with patch("agent_service.tools.web_search.get_mcp_manager", return_value=None), \
             patch.object(settings, "web_search_provider", "bing_mcp"):
            result = await tool.execute(query="正当防卫", max_results=3)
        self.assertFalse(result["available"])
        self.assertIn("未初始化", result["message"])

    async def test_bing_mcp_real_call(self):
        class FakeManager:
            async def call_tool(self, name, arguments):
                return {
                    "query": arguments["query"],
                    "results": [{"title": "B", "url": "http://b", "snippet": "案例"}],
                    "totalResults": 1,
                }

        tool = WebSearchTool()
        with patch("agent_service.tools.web_search.get_mcp_manager", return_value=FakeManager()), \
             patch.object(settings, "web_search_provider", "bing_mcp"), \
             patch.object(settings, "bing_mcp_tool_name", "bing_search"):
            result = await tool.execute(query="正当防卫 类似案例", max_results=5)
        self.assertTrue(result["available"])
        self.assertEqual(len(result["citations"]), 1)
        self.assertEqual(result["citations"][0]["source_type"], "web")

    async def test_bing_mcp_call_failure_degrades(self):
        class BoomManager:
            async def call_tool(self, name, arguments):
                raise ConnectionError("server down")

        tool = WebSearchTool()
        with patch("agent_service.tools.web_search.get_mcp_manager", return_value=BoomManager()), \
             patch.object(settings, "web_search_provider", "bing_mcp"):
            result = await tool.execute(query="q", max_results=3)
        self.assertFalse(result["available"])
        self.assertIn("不可用", result["message"])


class TestModuleHolder(unittest.IsolatedAsyncioTestCase):
    """模块级持有者 set/get。"""

    async def test_set_get(self):
        set_mcp_manager(None)
        self.assertIsNone(get_mcp_manager())
        mgr = MCPClientManager(server_url="http://x")
        set_mcp_manager(mgr)
        self.assertIs(get_mcp_manager(), mgr)
        set_mcp_manager(None)


if __name__ == "__main__":
    unittest.main()
