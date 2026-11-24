"""本文件测试 case_analysis Agent 的工具调用链路，验证 web_search 工具的决策、执行和结果合并。"""

from __future__ import annotations

import unittest
from typing import Any

from agent_service.agents import AgentManager
from agent_service.citation import CitationValidator
from agent_service.llm.base import BaseLLM, LLMToolResult
from agent_service.tools import ToolRegistry
from agent_service.tools.base import BaseTool
from rag_service.retrieval.models import ChunkHit, ContextResult, RetrievalResult


class FakeLLM(BaseLLM):
    """测试用 LLM，稳定返回包含引用编号的答案。"""

    @property
    def model_name(self) -> str:
        """返回测试模型名。"""
        return "fake"

    @property
    def supports_tool_call(self) -> bool:
        """测试模型不需要真实工具调用。"""
        return False

    async def chat(self, messages, **kwargs) -> str:
        """返回稳定答案。"""
        _ = messages, kwargs
        return "根据检索和类案参考，可以参考该条规定处理。[1]"

    async def stream(self, messages, **kwargs):
        """模拟流式输出。"""
        _ = messages, kwargs
        for piece in ("根据检索和类案参考，", "可以参考该条规定处理。[1]"):
            yield piece

    async def chat_with_tools(self, messages, tools, **kwargs):
        """返回空工具调用结果。"""
        _ = messages, tools, kwargs
        return LLMToolResult()


class FakeRetriever:
    """测试用检索器，返回一条可引用法条。"""

    async def retrieve(self, user_query: str, kb_ids: list[str] | None = None, top_k: int = 15, rerank_top_k: int = 8):
        """返回稳定 RetrievalResult。"""
        _ = user_query, kb_ids, top_k, rerank_top_k
        return RetrievalResult(
            chunks=[
                ChunkHit(
                    chunk_id="1",
                    text="出租人应当履行租赁物维修义务。",
                    final_score=0.9,
                    metadata={
                        "law_name": "民法典",
                        "article_no": "第712条",
                        "hierarchy_path": "合同编/租赁合同",
                    },
                )
            ],
            trace={"rewritten_query": {"legal_query": "租赁维修义务"}, "query_intent": {"intent_type": "legal"}},
        )


class FakeContextBuilder:
    """测试用 ContextBuilder，避免依赖真实 token 计数。"""

    async def build(self, chunks, citations, max_tokens=4000, include_hierarchy=True):
        """返回固定上下文结构。"""
        _ = chunks, citations, max_tokens, include_hierarchy
        return ContextResult(context_text="[1] 《民法典》第712条:\n出租人应维修。", citation_map={}, token_count=20, chunk_count=1)


class FakeWebSearchTool(BaseTool):
    """模拟 Tavily 搜索成功返回的 web_search 工具，避免真实联网。"""

    @property
    def name(self) -> str:
        """返回工具唯一名称。"""
        return "web_search"

    @property
    def description(self) -> str:
        """返回工具用途描述。"""
        return "测试用 web_search"

    @property
    def parameters_schema(self) -> dict[str, Any]:
        """返回搜索参数定义。"""
        return {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        """返回模拟的成功搜索结果。"""
        return {
            "available": True,
            "results": [
                {"title": "类案参考1", "url": "https://example.com/case1", "content": "类似案例裁判规则..."}
            ],
            "citations": [
                {
                    "source_type": "web",
                    "title": "类案参考1",
                    "url": "https://example.com/case1",
                    "text": "类似案例裁判规则...",
                    "score": 0.95,
                }
            ],
        }


def build_case_analysis_agent(tool_registry: ToolRegistry):
    """构造一个注入了 fake 依赖的 CaseAnalysisAgent。"""
    manager = AgentManager(
        bm25=None,
        milvus=None,
        embedding=object(),
        query_rewriter=None,
        query_router=None,
        context_builder=FakeContextBuilder(),
        tool_registry=tool_registry,
        memory=None,
        citation_validator=CitationValidator(),
    )
    agent = manager.get_agent("case_analysis", llm=FakeLLM(), db=None)
    agent.retriever = FakeRetriever()
    return agent


class CaseAnalysisToolCallTests(unittest.IsolatedAsyncioTestCase):
    """覆盖 case_analysis Agent 工具调用的决策、执行、降级和结果合并。"""

    async def test_tool_decide_produces_web_search(self) -> None:
        """tool_decide_node 应产出 web_search 工具调用，query 包含原查询。"""
        agent = build_case_analysis_agent(ToolRegistry())
        state: dict[str, Any] = {"query": "租房漏水房东不修怎么办"}
        result = await agent.tool_decide_node(state)
        calls = result.get("pending_tool_calls") or []
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "web_search")
        self.assertIn("租房漏水房东不修怎么办", calls[0]["args"]["query"])
        self.assertEqual(calls[0]["args"]["max_results"], 5)

    async def test_tool_exec_degrades_without_tool_context(self) -> None:
        """无 ToolContext 时 web_search 应返回 available=False 降级结果，不抛异常。"""
        agent = build_case_analysis_agent(ToolRegistry())
        state: dict[str, Any] = {
            "query": "租房漏水房东不修怎么办",
            "pending_tool_calls": [
                {"name": "web_search", "args": {"query": "测试 类似案例", "max_results": 5}}
            ],
            "tool_calls": [],
        }
        result = await agent.tool_exec_node(state)
        tool_calls = result.get("tool_calls") or []
        self.assertEqual(len(tool_calls), 1)
        self.assertTrue(tool_calls[0]["ok"])
        self.assertFalse(tool_calls[0]["result"]["available"])
        self.assertEqual(tool_calls[0]["result"]["message"], "Tavily 未配置")

    async def test_tool_exec_with_fake_tool_returns_results(self) -> None:
        """web_search 成功返回时，工具结果应包含 available=True 和 citations。"""
        registry = ToolRegistry(tools=[FakeWebSearchTool()])
        agent = build_case_analysis_agent(registry)
        state: dict[str, Any] = {
            "query": "租房漏水房东不修怎么办",
            "pending_tool_calls": [
                {"name": "web_search", "args": {"query": "测试 类似案例", "max_results": 5}}
            ],
            "tool_calls": [],
        }
        result = await agent.tool_exec_node(state)
        tool_calls = result.get("tool_calls") or []
        self.assertEqual(len(tool_calls), 1)
        self.assertTrue(tool_calls[0]["ok"])
        self.assertTrue(tool_calls[0]["result"]["available"])
        self.assertEqual(len(tool_calls[0]["result"]["citations"]), 1)

    async def test_astream_emits_tool_events_and_merges_citations(self) -> None:
        """完整 astream 应输出 tool_decide/tool_exec 事件，web 引用合并到 citations。"""
        registry = ToolRegistry(tools=[FakeWebSearchTool()])
        agent = build_case_analysis_agent(registry)
        state: dict[str, Any] = {
            "query": "租房漏水房东不修怎么办",
            "kb_ids": [{"kb_id": "1"}],
            "risk_level": "low",
            "needs_human_review": False,
        }
        events = [event async for event in agent.astream(state)]
        joined = "".join(events)
        self.assertIn('"node": "tool_decide"', joined)
        self.assertIn('"node": "tool_exec"', joined)
        self.assertIn('"event": "final"', joined)
        # 工具调用应被记录在 state
        tool_calls = state.get("tool_calls") or []
        self.assertEqual(len(tool_calls), 1)
        self.assertEqual(tool_calls[0]["name"], "web_search")
        # citations 应包含检索引用 + web 引用
        citations = state.get("citations") or []
        source_types = {c.get("source_type") for c in citations}
        self.assertIn("web", source_types)

    async def test_astream_degrades_gracefully_without_tavily(self) -> None:
        """无 Tavily 配置时 astream 仍应正常完成，工具降级不阻塞流程。"""
        agent = build_case_analysis_agent(ToolRegistry())
        state: dict[str, Any] = {
            "query": "租房漏水房东不修怎么办",
            "kb_ids": [{"kb_id": "1"}],
            "risk_level": "low",
            "needs_human_review": False,
        }
        events = [event async for event in agent.astream(state)]
        joined = "".join(events)
        self.assertIn('"event": "final"', joined)
        tool_calls = state.get("tool_calls") or []
        self.assertEqual(len(tool_calls), 1)
        self.assertFalse(tool_calls[0]["result"]["available"])


if __name__ == "__main__":
    unittest.main()
