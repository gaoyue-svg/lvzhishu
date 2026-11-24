"""本文件测试编排层查询改写（QueryRewriteLayer）的规则/LLM 两级逻辑。"""

from __future__ import annotations

import json
import unittest

from agent_service.llm.base import BaseLLM
from agent_service.orchestrator.query_rewrite import QueryRewriteLayer
from agent_service.router.models import RouterInput
from agent_service.router.rules import generate_candidates


class FakeLLM(BaseLLM):
    """测试用 LLM，可固定返回 JSON 或模拟调用失败，并统计调用次数。"""

    def __init__(self, json_payload: dict | None = None, raise_error: bool = False) -> None:
        self.calls = 0
        self.json_payload = json_payload or {
            "rewritten_query": "劳动合同解除 经济补偿 咨询",
            "keywords": ["经济补偿"],
            "notes": "",
        }
        self.raise_error = raise_error

    @property
    def model_name(self) -> str:
        return "fake"

    @property
    def supports_tool_call(self) -> bool:
        return False

    async def chat(self, messages, **kwargs) -> str:
        self.calls += 1
        if self.raise_error:
            raise RuntimeError("llm down")
        return json.dumps(self.json_payload, ensure_ascii=False)

    async def stream(self, messages, **kwargs):
        yield ""

    async def chat_with_tools(self, messages, tools, **kwargs):
        from agent_service.llm.base import LLMToolResult

        return LLMToolResult()


class QueryRewriteTests(unittest.IsolatedAsyncioTestCase):
    """覆盖规则改写、LLM 增强、失败兜底与状态写入。"""

    async def test_typo_fixed_by_rules(self) -> None:
        """常见错别字"案列"应被规则表纠正为"案例"，且不触发 LLM。"""
        llm = FakeLLM()
        layer = QueryRewriteLayer(llm, llm_enabled=False)
        state = {"query": "帮我搜索一下近几年热门案列"}

        meta = await layer.rewrite(state)

        self.assertEqual(state["query"], "帮我搜索一下近几年热门案例")
        self.assertEqual(state["original_query"], "帮我搜索一下近几年热门案列")
        self.assertEqual(state["rewrite_meta"]["method"], "rules")
        self.assertEqual(meta["rewritten_query"], "帮我搜索一下近几年热门案例")
        self.assertEqual(llm.calls, 0)

    async def test_colloquial_expansion(self) -> None:
        """口语"借钱不还"应扩展为法律术语。"""
        layer = QueryRewriteLayer(FakeLLM(), llm_enabled=False)
        state = {"query": "借钱不还怎么办"}

        await layer.rewrite(state)

        self.assertIn("民间借贷", state["query"])
        self.assertEqual(state["original_query"], "借钱不还怎么办")

    async def test_llm_enabled_uses_llm_output(self) -> None:
        """开启 LLM 增强后应调用 LLM 并使用其改写结果。"""
        llm = FakeLLM(json_payload={"rewritten_query": "劳动合同解除 经济补偿 咨询", "keywords": [], "notes": ""})
        layer = QueryRewriteLayer(llm, llm_enabled=True)
        state = {"query": "被开除有赔偿吗"}

        meta = await layer.rewrite(state)

        self.assertEqual(llm.calls, 1)
        self.assertEqual(state["query"], "劳动合同解除 经济补偿 咨询")
        self.assertEqual(meta["method"], "llm")

    async def test_llm_failure_falls_back_to_rules(self) -> None:
        """LLM 调用失败时应回退规则结果，不抛错。"""
        llm = FakeLLM(raise_error=True)
        layer = QueryRewriteLayer(llm, llm_enabled=True, retry=0)
        state = {"query": "帮忙看下热门案列"}

        meta = await layer.rewrite(state)

        self.assertEqual(llm.calls, 1)
        self.assertIn("案例", state["query"])
        self.assertEqual(meta["method"], "rules")

    async def test_disabled_noop(self) -> None:
        """总开关关闭时不改写，不写 meta，不调 LLM。"""
        llm = FakeLLM()
        layer = QueryRewriteLayer(llm, enabled=False, llm_enabled=True)
        state = {"query": "民法典第585条是什么"}

        meta = await layer.rewrite(state)

        self.assertEqual(meta, {})
        self.assertEqual(state["query"], "民法典第585条是什么")
        self.assertEqual(llm.calls, 0)

    async def test_rewrite_routes_to_case_analysis(self) -> None:
        """改写后"热门案例"应能被意图规则路由到 case_analysis（修复错别字路由误判）。"""
        layer = QueryRewriteLayer(FakeLLM(), llm_enabled=False)
        state = {"query": "帮我搜索一下近几年热门案列"}
        await layer.rewrite(state)

        candidates = generate_candidates(RouterInput(user_query=state["query"]))
        agents = [c.agent for c in candidates]
        self.assertIn("case_analysis", agents)
        self.assertNotIn("law_qa", agents or ["law_qa"])  # 不应再落入默认 law_qa


if __name__ == "__main__":
    unittest.main()
