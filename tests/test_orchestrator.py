"""本文件测试 v2 多 Agent 编排层（doc 19）：Agent Card、Plan DAG、执行器、审查、合成、管线。

全部使用假 Agent/LLM，不依赖真实 DB/Milvus/Redis，验证数据契约与五层链路闭环。
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from agent_service.agents.registry import AgentCardRegistry, get_registry
from agent_service.citation import CitationValidator
from agent_service.orchestrator import (
    IntentLayer,
    MultiAgentPipeline,
    PlanExecutor,
    Planner,
    QueryRewriteLayer,
    Reviewer,
    Synthesizer,
)
from agent_service.orchestrator.plan import PlanDAG, PlanStep, default_single_step_plan, resolve_input_ref
from agent_service.orchestrator.run_state import MultiAgentRun, SlotStore
from agent_service.orchestrator.workflow import build_preset_plan, match_preset_workflow


class FakeAgent:
    """按 agent_key 返回固定产出的假 Agent，模拟真实子 Agent 行为。"""

    def __init__(self, key: str) -> None:
        self.key = key

    async def invoke_for_supervisor(self, inp: str, shared, *, overrides=None):
        if self.key == "contract_clause":
            return {
                "agent": self.key, "chunks": [{"chunk_id": "1", "text": "付款条款", "article_no": "1"}],
                "citations": [], "answer": "条款已解析", "context_text": "clauses ctx", "output_summary": "1条条款",
            }
        if self.key == "contract_rule":
            return {
                "agent": self.key, "chunks": [], "citations": [], "answer": "规则检测完成",
                "tool_calls": [{"name": "contract_risk_rules", "result": {"risks": [{"code": "R1", "level": "high"}]}}],
                "context_text": "", "output_summary": "命中1条风险",
            }
        if self.key == "contract_rag":
            return {
                "agent": self.key, "chunks": [{"chunk_id": "9", "text": "民法典合同编"}],
                "citations": [{"source_type": "law", "chunk_id": "9", "index": 1}],
                "answer": "法条依据", "context_text": "law ctx", "output_summary": "1条法条",
            }
        if self.key == "contract_risk_report":
            return {
                "agent": self.key, "chunks": [], "citations": [], "answer": "风险报告 JSON",
                "context_text": "", "output_summary": "报告生成",
            }
        return {"agent": self.key, "chunks": [], "citations": [], "answer": f"{self.key}答案", "context_text": "", "output_summary": "ok"}


class FakeManager:
    """create_agent 返回假 Agent。"""

    def create_agent(self, key: str, **kwargs):
        return FakeAgent(key)


class FakeLLM:
    """chat_json 返回决策 dict，stream 逐字产出。"""

    def __init__(self, payload=None, text="最终答案") -> None:
        self.payload = payload or {"entry_hint": "contract_review", "risk_level": "low"}
        self.text = text

    async def chat_json(self, *args, **kwargs):
        return self.payload

    async def stream(self, messages, **kwargs):
        for piece in self.text:
            yield piece


class FakeValidator:
    """L1 引用校验恒通过。"""

    async def validate(self, **kwargs):
        return {"passed": True, "failed_ids": [], "reasons": []}


class TestAgentCardRegistry(unittest.TestCase):
    """Agent Card 注册表与白名单派生。"""

    def test_loads_nine_cards(self):
        registry = get_registry()
        self.assertEqual(len(registry.list()), 9)
        self.assertIn("contract_review", registry.allowed_agents())
        self.assertIn("contract_clause", registry.allowed_agents())
        self.assertIn("contract_elements", registry.allowed_agents())

    def test_validate_plan_ok(self):
        plan = build_preset_plan("contract_review", query="审查合同")
        self.assertIsNotNone(plan)
        errors = get_registry().validate_plan([s.model_dump() for s in plan.steps], max_steps=8)
        self.assertEqual(errors, [])

    def test_validate_plan_rejects_unknown_agent(self):
        errors = get_registry().validate_plan([{"step_id": "s1", "agent": "not_a_card", "deps": []}], max_steps=4)
        self.assertTrue(any("未在 Agent Card 注册表" in e for e in errors))

    def test_validate_plan_rejects_cycle(self):
        steps = [
            {"step_id": "a", "agent": "law_qa", "deps": ["b"]},
            {"step_id": "b", "agent": "article_locate", "deps": ["a"]},
        ]
        errors = get_registry().validate_plan(steps, max_steps=4)
        self.assertTrue(any("循环依赖" in e for e in errors))

    def test_validate_plan_requires_synthesize(self):
        errors = get_registry().validate_plan(
            [{"step_id": "s1", "agent": "law_qa", "deps": []}], max_steps=4
        )
        self.assertTrue(any("缺少 synthesize" in e for e in errors))


class TestPlanDataContract(unittest.TestCase):
    """Plan 数据契约解析。"""

    def test_resolve_input_ref(self):
        slots = SlotStore()
        slots.set("clauses", ["a", "b"])
        self.assertEqual(
            resolve_input_ref("$user.document_id", user={"document_id": "42"}, intent={}, slots=slots), "42"
        )
        self.assertEqual(
            resolve_input_ref("$intent.domain", user={}, intent={"domain": "civil"}, slots=slots), "civil"
        )
        self.assertEqual(resolve_input_ref("slot.clauses", user={}, intent={}, slots=slots), ["a", "b"])
        self.assertEqual(resolve_input_ref("plain", user={}, intent={}, slots=slots), "plain")
        self.assertIsNone(resolve_input_ref("slot.missing", user={}, intent={}, slots=slots))

    def test_default_single_step_plan(self):
        plan = default_single_step_plan("article_locate", "如何认定正当防卫", plan_id="p")
        agents = [s.agent for s in plan.steps]
        self.assertEqual(agents, ["article_locate", "synthesize"])


class TestPresetWorkflow(unittest.TestCase):
    """合同审查预置工作流。"""

    def test_match_contract_review(self):
        intent = {"entry_hint": "contract_review"}
        shared = {"document_id": "42"}
        self.assertEqual(match_preset_workflow(intent, shared), "contract_review")

    def test_preset_steps_order(self):
        plan = build_preset_plan("contract_review", query="审查合同")
        self.assertEqual(
            [s.agent for s in plan.steps],
            ["contract_clause", "contract_rule", "contract_rag", "contract_risk_report", "synthesize"],
        )


class TestPlanExecutor(unittest.IsolatedAsyncioTestCase):
    """执行器：slot 表 + 拓扑执行 + 数据契约。"""

    async def test_contract_workflow_slots(self):
        plan = build_preset_plan("contract_review", query="审查合同")
        run = MultiAgentRun(plan_id="p1", query="审查合同")
        shared = {"query": "审查合同", "document_id": "42", "user_id": "1", "tenant_id": "1", "kb_ids": []}
        executor = PlanExecutor(FakeManager(), llm=FakeLLM(), db=None)
        ok = await executor.execute(plan, run, shared)
        self.assertTrue(ok)
        self.assertEqual([r["agent"] for r in run.agent_results], [
            "contract_clause", "contract_rule", "contract_rag", "contract_risk_report",
        ])
        slots = run.slots
        self.assertIn("clauses", slots.as_dict())
        self.assertIn("rule_risks", slots.as_dict())
        self.assertIn("law_cites", slots.as_dict())
        self.assertEqual(len(slots.get("clauses") or []), 1)
        self.assertEqual(len(slots.get("rule_risks") or []), 1)

    async def test_step_failure_returns_false(self):
        class BoomAgent(FakeAgent):
            async def invoke_for_supervisor(self, inp, shared, *, overrides=None):
                raise RuntimeError("boom")

        class BoomManager(FakeManager):
            def create_agent(self, key: str, **kwargs):
                return BoomAgent(key)

        plan = default_single_step_plan("law_qa", "test")
        run = MultiAgentRun(plan_id="p", query="test")
        executor = PlanExecutor(BoomManager(), llm=FakeLLM(), db=None, step_retry=0)
        ok = await executor.execute(plan, run, {"query": "test", "kb_ids": []})
        self.assertFalse(ok)
        self.assertTrue(any(t.status == "failed" for t in run.step_traces))


class TestReviewer(unittest.IsolatedAsyncioTestCase):
    """审查层 L1 确定性检查，引用完整性复用真实 CitationValidator。"""

    def _run(self, results):
        run = MultiAgentRun(plan_id="p", query="q")
        run.agent_results = list(results)
        return run

    async def test_l1_passes(self):
        run = self._run([{"_step_id": "s1", "agent": "law_qa", "answer": "答案[1]", "citations": [{"index": 1}]}])
        review = await Reviewer(CitationValidator(), None, l2_enabled=False).review(run)
        self.assertTrue(review["passed"])

    async def test_l1_rejects_orphan_citation(self):
        run = self._run([{"_step_id": "s1", "agent": "law_qa", "answer": "答案[9]", "citations": [{"index": 1}]}])
        review = await Reviewer(CitationValidator(), None, l2_enabled=False).review(run)
        self.assertFalse(review["passed"])
        self.assertIn("s1", review["failed_steps"])

    async def test_high_risk_sets_human_review(self):
        run = self._run([{"_step_id": "s1", "agent": "law_qa", "answer": "答案", "citations": []}])
        run.intent = {"risk_level": "high"}
        review = await Reviewer(CitationValidator(), None, l2_enabled=False).review(run)
        self.assertTrue(review["needs_human_review"])


class TestSynthesizer(unittest.IsolatedAsyncioTestCase):
    """合成层：引用合并 + 流式 + context 截断。"""

    async def test_merge_and_rewrite(self):
        results = [
            {"agent": "law_qa", "answer": "根据[1]", "citations": [{"index": 1, "chunk_id": "c1"}], "context_text": "x" * 100},
            {"agent": "article_locate", "answer": "依据[1]", "citations": [{"index": 1, "chunk_id": "c2"}], "context_text": "y" * 100},
        ]
        tokens = []
        synth = Synthesizer(FakeLLM(text="合并答案"), context_max_tokens=10)
        result = await synth.synthesize("q", results, on_token=lambda piece: tokens.append(piece))
        self.assertEqual(result["answer"], "合并答案")
        self.assertEqual(len(result["citations"]), 2)
        self.assertGreater(len(tokens), 0)
        # context_max_tokens 生效：传给 LLM 的 user prompt 不应包含超长原文
        self.assertNotIn("x" * 100, str(result))

    async def test_no_results_fallback(self):
        synth = Synthesizer(FakeLLM())
        result = await synth.synthesize("q", [])
        self.assertIn("未能生成答案", result["answer"])

    async def test_dangling_citations_are_removed_before_streaming(self):
        results = [{"agent": "contract_risk_report", "answer": "风险报告", "citations": []}]
        tokens = []
        synth = Synthesizer(FakeLLM(text="依据法律规定[1][2]，该条款存在风险。"))
        result = await synth.synthesize("审查合同", results, on_token=tokens.append)
        self.assertEqual(result["answer"], "依据法律规定，该条款存在风险。")
        self.assertEqual(tokens, [result["answer"]])


class TestPipeline(unittest.IsolatedAsyncioTestCase):
    """v2 全链路：意图→规划→执行→审查→合成，产出 SSE 事件。"""

    async def test_pipeline_contract_review(self):
        manager = FakeManager()
        llm = FakeLLM(text="审查报告")
        intent_layer = IntentLayer(llm)
        planner = Planner(llm)
        executor = PlanExecutor(manager, llm=llm, db=None)
        reviewer = Reviewer(FakeValidator(), llm, l2_enabled=False)
        synthesizer = Synthesizer(llm)
        pipeline = MultiAgentPipeline(
            query_rewrite_layer=QueryRewriteLayer(llm), intent_layer=intent_layer,
            planner=planner, executor=executor,
            reviewer=reviewer, synthesizer=synthesizer,
        )
        shared = {
            "query": "审查合同", "document_id": "42", "user_id": "1", "tenant_id": "1",
            "kb_ids": [], "uploaded_files": [], "available_kbs": [], "legal_memory": None, "history_summary": "",
        }
        events = [event async for event in pipeline.run(shared)]
        joined = "".join(events)
        self.assertIn('"event": "v2_intent"', joined)
        self.assertIn('"event": "v2_plan"', joined)
        self.assertIn('"event": "v2_review"', joined)
        self.assertIn('"event": "final"', joined)
        self.assertTrue(shared.get("final_answer"))
        self.assertEqual(len(shared.get("final_citations") or []), 1)


if __name__ == "__main__":
    unittest.main()
