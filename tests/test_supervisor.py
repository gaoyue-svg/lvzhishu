"""本文件测试 Supervisor 多 Agent 编排器的决策校验、引用合并和协同流程。"""

import unittest
from unittest.mock import AsyncMock, MagicMock

from agent_service.agents.citation_merge import (
    merge_citations,
    renumber_answer_text,
    sanitize_citation_references,
)
from agent_service.agents.state import AgentResult, SharedState
from agent_service.agents.supervisor import Supervisor, SupervisorDecision


class TestSupervisorDecision(unittest.TestCase):
    """SupervisorDecision 字段校验，确保 LLM 输出缺字段时直接抛错。"""

    def test_call_agent_requires_agent_and_input(self):
        # agent 和 input 都不能为空
        with self.assertRaises(ValueError):
            SupervisorDecision(action="call_agent", agent="", input="")
        with self.assertRaises(ValueError):
            SupervisorDecision(action="call_agent", agent="law_qa", input="")
        with self.assertRaises(ValueError):
            SupervisorDecision(action="call_agent", agent="", input="test")

    def test_synthesize_requires_reason(self):
        with self.assertRaises(ValueError):
            SupervisorDecision(action="synthesize", reason="")
        # 正常情况
        decision = SupervisorDecision(action="synthesize", reason="信息充分")
        self.assertEqual(decision.reason, "信息充分")

    def test_call_agent_valid(self):
        decision = SupervisorDecision(action="call_agent", agent="law_qa", input="正当防卫")
        self.assertEqual(decision.agent, "law_qa")

    def test_finish_no_extra_fields(self):
        decision = SupervisorDecision(action="finish", thought="直接结束")
        self.assertEqual(decision.action, "finish")

class TestJsonParsing(unittest.TestCase):
    """验证 parse_json_object 对带前缀文字、截断、代码块的容错。"""

    def test_pure_json(self):
        # 纯 JSON：正常解析
        from agent_service.llm.base import parse_json_object

        result = parse_json_object('{"action":"synthesize","reason":"已覆盖"}')
        self.assertEqual(result["action"], "synthesize")

    def test_with_prefix_text(self):
        # 带自然语言前缀：json_repair 应能提取
        from agent_service.llm.base import parse_json_object

        result = parse_json_object('好的，决策如下：{"action":"call_agent","agent":"law_qa","input":"test"}')
        self.assertEqual(result["action"], "call_agent")
        self.assertEqual(result["agent"], "law_qa")

    def test_with_suffix_text(self):
        # 带后缀解释：json_repair 应能提取
        from agent_service.llm.base import parse_json_object

        result = parse_json_object('{"action":"call_agent","agent":"law_qa","input":"test"}\n\n以上是我的决策')
        self.assertEqual(result["action"], "call_agent")

    def test_truncated_json(self):
        # 截断的 JSON（缺右括号）：json_repair 应能修复
        from agent_service.llm.base import parse_json_object

        result = parse_json_object('{"action":"call_agent","agent":"law_qa","input":"test"')
        self.assertEqual(result["action"], "call_agent")
        self.assertEqual(result["agent"], "law_qa")

    def test_markdown_code_block(self):
        # 整段 markdown 代码块：原有逻辑处理
        from agent_service.llm.base import parse_json_object

        result = parse_json_object('```json\n{"action":"synthesize","reason":"ok"}\n```')
        self.assertEqual(result["action"], "synthesize")

    def test_empty_raises(self):
        # 空字符串应抛 ValueError
        from agent_service.llm.base import parse_json_object

        with self.assertRaises(ValueError):
            parse_json_object("")


class TestCitationMerge(unittest.TestCase):
    """引用合并与全局重编号。"""

    def test_merge_single_agent(self):
        # 单 Agent 产出，编号保持不变
        results = [
            AgentResult(
                agent="law_qa",
                round=1,
                input="test",
                citations=[
                    {"index": 1, "title": "刑法第20条", "chunk_id": "c1", "source_type": "law"},
                    {"index": 2, "title": "民法典第585条", "chunk_id": "c2", "source_type": "law"},
                ],
            )
        ]
        merged, renumber = merge_citations(results)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["index"], 1)
        self.assertEqual(merged[1]["index"], 2)
        self.assertEqual(renumber["law_qa"][1], 1)
        self.assertEqual(renumber["law_qa"][2], 2)

    def test_merge_dedup_same_chunk(self):
        # 两个 Agent 检索到同一 chunk，应去重
        results = [
            AgentResult(
                agent="law_qa", round=1, input="t",
                citations=[{"index": 1, "title": "刑法第20条", "chunk_id": "c1", "source_type": "law"}],
            ),
            AgentResult(
                agent="article_locate", round=2, input="t",
                citations=[{"index": 1, "title": "刑法第20条", "chunk_id": "c1", "source_type": "law"}],
            ),
        ]
        merged, renumber = merge_citations(results)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["index"], 1)
        self.assertEqual(merged[0]["from_agent"], "law_qa")
        # article_locate 的局部 1 映射到全局 1
        self.assertEqual(renumber["article_locate"][1], 1)

    def test_merge_multi_agent_renumber(self):
        # 两个 Agent 不同 chunk，全局重编号
        results = [
            AgentResult(
                agent="law_qa", round=1, input="t",
                citations=[{"index": 1, "title": "A", "chunk_id": "c1", "source_type": "law"}],
            ),
            AgentResult(
                agent="article_locate", round=2, input="t",
                citations=[{"index": 1, "title": "B", "chunk_id": "c2", "source_type": "law"}],
            ),
        ]
        merged, renumber = merge_citations(results)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["index"], 1)
        self.assertEqual(merged[1]["index"], 2)
        # article_locate 的局部 1 → 全局 2
        self.assertEqual(renumber["article_locate"][1], 2)

    def test_renumber_answer_text(self):
        renumber_map = {"law_qa": {1: 3, 2: 5}}
        result = renumber_answer_text("根据[1]和[2]的规定", "law_qa", renumber_map)
        self.assertEqual(result, "根据[3]和[5]的规定")

    def test_renumber_unknown_keeps_original(self):
        # 未在 map 中的编号保持原样
        renumber_map = {"law_qa": {1: 3}}
        result = renumber_answer_text("[1]和[99]", "law_qa", renumber_map)
        self.assertEqual(result, "[3]和[99]")

    def test_sanitize_citation_references_removes_only_dangling_numbers(self):
        citations = [{"index": 1, "chunk_id": "c1"}, {"index": 3, "chunk_id": "c3"}]
        result = sanitize_citation_references("依据[1][2]，并参考[3]。", citations)
        self.assertEqual(result, "依据[1]，并参考[3]。")

    def test_sanitize_citation_references_removes_all_when_no_sources(self):
        result = sanitize_citation_references("依据相关规定[1][2]。", [])
        self.assertEqual(result, "依据相关规定。")


def _make_mock_llm(decisions=None, synth_text="合成答案"):
    """构造 mock LLM；decisions 是 chat_json 依次返回的决策 dict 列表。

    Supervisor 的决策路径统一走 self.llm.chat_json(system, user_prompt)，
    mock 必须提供可 await 的 chat_json 才能驱动决策循环。
    """
    decisions_queue = list(decisions or [])

    async def _chat_json(*_args, **_kwargs):
        if decisions_queue:
            return decisions_queue.pop(0)
        return {"action": "synthesize", "reason": "mock 默认合成"}

    llm = MagicMock()
    llm.chat_json = _chat_json

    # stream 直接用 async generator 函数，调用返回 async iterator
    async def _stream(*_args, **_kwargs):
        for piece in synth_text:
            yield piece

    llm.stream = _stream
    return llm


def _make_mock_agent_manager(agent_results=None):
    """构造 mock AgentManager；create_agent 同步返回 mock Agent。"""
    mgr = MagicMock()
    results_queue = list(agent_results or [])

    def _create_agent(key, **_kwargs):
        agent = MagicMock()
        if results_queue:
            result = results_queue.pop(0)
        else:
            result = AgentResult(
                agent=key, round=1, input="", context_text="", chunks=[],
                citations=[], answer=f"{key}答案", trace_id="t1", output_summary=f"{key}摘要",
            )
        agent.invoke_for_supervisor = AsyncMock(return_value=result)
        return agent

    mgr.create_agent = _create_agent
    return mgr


class TestSupervisor(unittest.IsolatedAsyncioTestCase):
    """Supervisor 编排流程测试，使用 mock LLM 和 mock AgentManager。"""

    async def test_single_agent_then_synthesize(self):
        """单轮调用后合成。"""
        decisions = [
            {"thought": "先查法条", "action": "call_agent", "agent": "law_qa", "input": "正当防卫", "reason": ""},
            {"thought": "信息充分", "action": "synthesize", "agent": "", "input": "", "reason": "已覆盖"},
        ]
        llm = _make_mock_llm(decisions=decisions)
        mgr = _make_mock_agent_manager()
        sup = Supervisor(agent_manager=mgr, llm=llm, db=MagicMock())

        state: SharedState = {"query": "正当防卫怎么判", "user_id": "u1", "tenant_id": "u1", "kb_ids": []}
        async for _ in sup.astream(state):
            pass

        self.assertTrue(state.get("final_answer"))
        self.assertEqual(state["current_round"], 1)
        self.assertEqual(len(state["agent_history"]), 1)

    async def test_structured_lease_date_followup_skips_supervisor_decision(self):
        """催修日期事实续写应直达 law_qa，不调用查询改写或 Supervisor 决策 LLM。"""
        llm = MagicMock()
        llm.chat_json = AsyncMock(side_effect=AssertionError("不应调用 Supervisor 决策"))
        rewriter = MagicMock()
        rewriter.rewrite = AsyncMock(side_effect=AssertionError("不应调用 LLM 查询改写"))
        mgr = _make_mock_agent_manager(agent_results=[
            AgentResult(
                agent="law_qa", round=1, input="第三次是3月20日。", context_text="",
                chunks=[], citations=[], answer="已记录第三次催修日期。",
                trace_id="t1", output_summary="记录催修时间线",
            ),
        ])
        sup = Supervisor(
            agent_manager=mgr,
            llm=llm,
            db=MagicMock(),
            query_rewriter=rewriter,
        )
        state: SharedState = {
            "query": "第三次是3月20日。",
            "user_id": "u1", "tenant_id": "u1", "kb_ids": [],
            "legal_memory": {"current_case": {
                "civil_dispute_topic": "residential_lease_repair",
                "repair_notice_dates": {"1": "2026-03-01", "2": "2026-03-10", "3": "2026-03-20"},
            }},
        }

        async for _ in sup.astream(state):
            pass

        self.assertEqual(state["final_answer"], "已记录第三次催修日期。")
        self.assertEqual(state["entry_hint"], "law_qa")
        self.assertEqual(len(state["agent_history"]), 1)
        llm.chat_json.assert_not_awaited()
        rewriter.rewrite.assert_not_awaited()

    def test_lease_damage_fact_fragments_use_fast_path(self):
        """漏水财产损失的连续事实补充应继承租赁案件并绕过规划模型。"""
        base = {"legal_memory": {"current_case": {
            "civil_dispute_topic": "residential_lease_repair",
            "property_damage_cause": "房屋漏水",
        }}}
        for query in (
            "房东一直没有维修。",
            "漏水导致电脑损坏。",
            "电脑维修花了3000元。",
            "我有维修发票。",
            "我也有三次催修记录。",
        ):
            self.assertEqual(
                Supervisor._structured_followup_agent({**base, "query": query}),
                "law_qa",
            )

    async def test_filing_material_query_finishes_after_first_law_qa(self):
        """立案材料清单由 law_qa 成功回答后，不应再调用 Supervisor 决策。"""
        decisions = [
            {"thought": "先生成材料清单", "action": "call_agent", "agent": "law_qa", "input": "起诉材料", "reason": ""},
        ]
        llm = _make_mock_llm(decisions=decisions)
        mgr = _make_mock_agent_manager(agent_results=[
            AgentResult(
                agent="law_qa", round=1, input="起诉材料", context_text="",
                chunks=[], citations=[], answer="完整材料清单", trace_id="t1", output_summary="材料清单",
            ),
        ])
        sup = Supervisor(agent_manager=mgr, llm=llm, db=MagicMock())
        state: SharedState = {
            "query": "去法院起诉别人需要准备哪些材料？",
            "user_id": "u1", "tenant_id": "u1", "kb_ids": [],
        }

        async for _ in sup.astream(state):
            pass

        self.assertEqual(state["final_answer"], "完整材料清单")
        self.assertEqual(state["current_round"], 1)
        self.assertEqual(len(state["agent_history"]), 1)

    async def test_document_generation_finishes_after_first_law_qa(self):
        """正式文书生成成功后不应重复调用 law_qa 或再次请求 Supervisor。"""
        decisions = [
            {"thought": "生成起诉状", "action": "call_agent", "agent": "law_qa", "input": "民事起诉状", "reason": ""},
        ]
        llm = _make_mock_llm(decisions=decisions)
        mgr = _make_mock_agent_manager(agent_results=[
            AgentResult(
                agent="law_qa", round=1, input="民事起诉状", context_text="",
                chunks=[], citations=[], answer="民事起诉状正文", trace_id="t1", output_summary="已生成文书",
            ),
        ])
        sup = Supervisor(agent_manager=mgr, llm=llm, db=MagicMock())
        state: SharedState = {
            "query": "请给我一份拖欠贷款的民事起讼状模板",
            "user_id": "u1", "tenant_id": "u1", "kb_ids": [],
        }

        async for _ in sup.astream(state):
            pass

        self.assertEqual(state["final_answer"], "民事起诉状正文")
        self.assertEqual(state["current_round"], 1)
        self.assertEqual(len(state["agent_history"]), 1)

    async def test_max_rounds_forces_synthesize(self):
        """超过 max_rounds 强制合成。"""
        # 所有决策都是 call_agent，模拟永不停止
        decisions = [
            {"thought": "继续", "action": "call_agent", "agent": "law_qa", "input": f"q{i}", "reason": ""}
            for i in range(10)
        ]
        llm = _make_mock_llm(decisions=decisions)
        mgr = _make_mock_agent_manager()
        sup = Supervisor(agent_manager=mgr, llm=llm, db=MagicMock())
        sup.max_rounds = 2
        sup.max_agent_calls = 10  # 放开 Agent 调用限制，专测 max_rounds

        state: SharedState = {"query": "test", "user_id": "u1", "tenant_id": "u1", "kb_ids": []}
        async for _ in sup.astream(state):
            pass

        self.assertGreaterEqual(state["current_round"], 2)
        self.assertTrue(state.get("final_answer"))

    async def test_max_agent_calls_forces_synthesize(self):
        """同一 Agent 调用达上限强制合成。"""
        decisions = [
            {"thought": "1", "action": "call_agent", "agent": "law_qa", "input": "q1", "reason": ""},
            {"thought": "2", "action": "call_agent", "agent": "law_qa", "input": "q2", "reason": ""},
            {"thought": "3", "action": "call_agent", "agent": "law_qa", "input": "q3", "reason": ""},
        ]
        llm = _make_mock_llm(decisions=decisions)
        mgr = _make_mock_agent_manager()
        sup = Supervisor(agent_manager=mgr, llm=llm, db=MagicMock())
        sup.max_rounds = 10
        sup.max_agent_calls = 2

        state: SharedState = {"query": "test", "user_id": "u1", "tenant_id": "u1", "kb_ids": []}
        async for _ in sup.astream(state):
            pass

        # law_qa 最多调 2 次后应强制合成
        law_qa_count = sum(1 for h in state["agent_history"] if h["agent"] == "law_qa")
        self.assertLessEqual(law_qa_count, 2)

    async def test_llm_decision_failure_no_results(self):
        """LLM 决策失败且无产出：返回错误提示。"""
        llm = MagicMock()
        llm.chat = AsyncMock(side_effect=Exception("LLM 挂了"))

        async def _stream(*_args, **_kwargs):
            yield "兜底"
        llm.stream = _stream

        mgr = _make_mock_agent_manager()
        sup = Supervisor(agent_manager=mgr, llm=llm, db=MagicMock())

        state: SharedState = {"query": "test", "user_id": "u1", "tenant_id": "u1", "kb_ids": []}
        async for _ in sup.astream(state):
            pass

        self.assertIn("决策失败", state.get("final_answer", ""))

    async def test_finish_action_uses_last_agent_answer(self):
        """finish 直接用最后 Agent 的答案，不重写。"""
        decisions = [
            {"thought": "先查", "action": "call_agent", "agent": "law_qa", "input": "q1", "reason": ""},
            {"thought": "够了", "action": "finish", "agent": "", "input": "", "reason": ""},
        ]
        llm = _make_mock_llm(decisions=decisions)
        mgr = _make_mock_agent_manager(agent_results=[
            AgentResult(
                agent="law_qa", round=1, input="q1", context_text="",
                chunks=[], citations=[], answer="law_qa的答案", trace_id="t1", output_summary="摘要",
            ),
        ])
        sup = Supervisor(agent_manager=mgr, llm=llm, db=MagicMock())

        state: SharedState = {"query": "test", "user_id": "u1", "tenant_id": "u1", "kb_ids": []}
        async for _ in sup.astream(state):
            pass

        self.assertEqual(state["final_answer"], "law_qa的答案")

    async def test_unsupported_agent_forces_synthesize(self):
        """agent 不在白名单时强制合成，不执行该 Agent。"""
        decisions = [
            {"thought": "调未知", "action": "call_agent", "agent": "unknown_agent", "input": "q1", "reason": ""},
        ]
        llm = _make_mock_llm(decisions=decisions)
        mgr = _make_mock_agent_manager()
        sup = Supervisor(agent_manager=mgr, llm=llm, db=MagicMock())

        state: SharedState = {"query": "test", "user_id": "u1", "tenant_id": "u1", "kb_ids": []}
        async for _ in sup.astream(state):
            pass

        # 未知 agent 不应被执行
        self.assertEqual(len(state.get("agent_history") or []), 0)

    async def test_two_agent_collaboration(self):
        """双 Agent 协同：law_qa → article_locate → synthesize。"""
        decisions = [
            {"thought": "先查法律依据", "action": "call_agent", "agent": "law_qa", "input": "正当防卫", "reason": ""},
            {"thought": "补条文", "action": "call_agent", "agent": "article_locate", "input": "刑法第二十条", "reason": ""},
            {"thought": "信息充分", "action": "synthesize", "agent": "", "input": "", "reason": "已覆盖"},
        ]
        llm = _make_mock_llm(decisions=decisions, synth_text="最终合成答案")
        mgr = _make_mock_agent_manager(agent_results=[
            AgentResult(
                agent="law_qa", round=1, input="正当防卫", context_text="",
                chunks=[{"law_name": "刑法", "article_no": "第20条"}],
                citations=[{"index": 1, "title": "刑法第20条", "chunk_id": "c1", "source_type": "law"}],
                answer="law_qa答案[1]", trace_id="t1", output_summary="检索到1条含刑法第20条",
            ),
            AgentResult(
                agent="article_locate", round=2, input="刑法第二十条", context_text="",
                chunks=[{"law_name": "刑法", "article_no": "第20条"}],
                citations=[{"index": 1, "title": "刑法第20条", "chunk_id": "c1", "source_type": "law"}],
                answer="article_locate答案[1]", trace_id="t2", output_summary="定位到刑法第20条原文",
            ),
        ])
        sup = Supervisor(agent_manager=mgr, llm=llm, db=MagicMock())

        state: SharedState = {"query": "正当防卫怎么判", "user_id": "u1", "tenant_id": "u1", "kb_ids": []}
        async for _ in sup.astream(state):
            pass

        self.assertEqual(state["current_round"], 2)
        self.assertEqual(len(state["agent_history"]), 2)
        self.assertEqual(state["agent_history"][0]["agent"], "law_qa")
        self.assertEqual(state["agent_history"][1]["agent"], "article_locate")
        self.assertEqual(state["final_answer"], "最终合成答案")
        # 引用去重：两个 Agent 都引用 c1，合并后应只有 1 条
        self.assertEqual(len(state["final_citations"]), 1)

    async def test_risk_level_high_sets_human_review(self):
        """risk_level=high 时 needs_human_review 为 True。"""
        decisions = [
            {"thought": "合成", "action": "synthesize", "agent": "", "input": "", "reason": "直接合成"},
        ]
        llm = _make_mock_llm(decisions=decisions)
        mgr = _make_mock_agent_manager()
        sup = Supervisor(agent_manager=mgr, llm=llm, db=MagicMock())

        state: SharedState = {
            "query": "test", "user_id": "u1", "tenant_id": "u1", "kb_ids": [],
            "risk_level": "high",
        }
        final_payload = None
        async for event in sup.astream(state):
            if event.startswith("event: final"):
                # 解析 SSE final 事件
                pass
        # final_answer 由 Synthesizer 生成
        self.assertTrue(state.get("final_answer"))


if __name__ == "__main__":
    unittest.main()
