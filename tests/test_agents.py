"""本文件测试阶段四业务 Agent、工具注册表和引用校验的核心闭环。"""

from __future__ import annotations

import unittest
from typing import Any

from agent_service.agents import AgentManager
from agent_service.agents.law_qa import LawQaAgent
from agent_service.citation import CitationValidator
from agent_service.llm.base import BaseLLM
from agent_service.prompts import get_prompt
from agent_service.tools import ToolRegistry
from rag_service.retrieval.models import ChunkHit, RetrievalResult


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
        return "根据检索结果，可以参考该条规定处理。[1]"

    async def stream(self, messages, **kwargs):
        """模拟流式输出。"""
        _ = messages, kwargs
        for piece in ("根据检索结果，", "可以参考该条规定处理。[1]"):
            yield piece

    async def chat_with_tools(self, messages, tools, **kwargs):
        """返回空工具调用结果。"""
        _ = messages, tools, kwargs
        from agent_service.llm.base import LLMToolResult

        return LLMToolResult()


class FakeRetriever:
    """测试用检索器，返回一条可引用法条。"""

    async def retrieve(self, user_query: str, kb_ids: list[str] | None, top_k: int = 15, rerank_top_k: int = 8):
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
        from rag_service.retrieval.models import ContextResult

        return ContextResult(context_text="[1] 《民法典》第712条:\n出租人应维修。", citation_map={}, token_count=20, chunk_count=1)


class AgentCoreTests(unittest.IsolatedAsyncioTestCase):
    """覆盖四个业务 Agent 的注册和基础闭环。"""

    async def test_law_qa_agent_astream_outputs_final(self) -> None:
        """law_qa 应能完成检索、推理、引用和 final 事件输出。"""
        manager = AgentManager(
            bm25=None,
            milvus=None,
            embedding=object(),  # FakeRetriever 会替代实际 retriever，因此这里只占位。
            query_rewriter=None,
            query_router=None,
            context_builder=FakeContextBuilder(),
            tool_registry=ToolRegistry(),
            memory=None,
            citation_validator=CitationValidator(),
        )
        agent = manager.get_agent("law_qa", llm=FakeLLM(), db=None)
        agent.retriever = FakeRetriever()
        state: dict[str, Any] = {
            "query": "租房漏水房东不修怎么办",
            "kb_ids": [{"kb_id": "1"}],
            "risk_level": "low",
            "needs_human_review": False,
        }
        events = [event async for event in agent.astream(state)]
        self.assertIn('"event": "token"', "".join(events))
        self.assertIn('"event": "final"', "".join(events))
        self.assertIn("[1]", state["answer"])
        self.assertTrue(state["citation_validation"]["passed"])

    def test_manager_registers_all_router_keys(self) -> None:
        """AgentManager 注册 key 必须与 Agent Card 注册表一致（含合同多阶段子 Agent）。"""
        self.assertEqual(
            set(AgentManager.supported_agents()),
            {
                "law_qa",
                "article_locate",
                "contract_review",
                "case_analysis",
                "contract_clause",
                "contract_rule",
                "contract_rag",
                "contract_elements",
                "contract_risk_report",
            },
        )

    def test_traffic_question_expands_retrieval_dimensions(self) -> None:
        """交通事故问法应同时检索行政、民事和刑事量化标准。"""
        agent = object.__new__(LawQaAgent)
        query = agent._retrieval_query({"query": "开车闯红灯撞到人会怎么处罚"})
        for expected in (
            "交通违法记分", "交强险", "交通肇事罪", "入罪标准", "逃逸", "量刑",
            "不构成犯罪", "常见误区", "积极救助", "赔偿损失", "取得谅解", "缓刑",
        ):
            self.assertIn(expected, query)

    def test_non_traffic_question_keeps_original_retrieval_query(self) -> None:
        """无关场景不能被交通责任词污染。"""
        agent = object.__new__(LawQaAgent)
        self.assertEqual(agent._retrieval_query({"query": "租房漏水房东不修怎么办"}), "租房漏水房东不修怎么办")

    def test_traffic_medical_insurance_followup_uses_accident_compensation_context(self) -> None:
        """交通事故后的“医疗保险能赔吗”应检索医保第三人责任与车险顺序。"""
        agent = object.__new__(LawQaAgent)
        state = {
            "query": "医疗保险能赔吗",
            "original_query": "医疗保险能赔吗",
            "history_summary": "用户：我开车撞到了一个骑电动车的人。\n用户：交警认定我负主要责任。",
            "legal_memory": {"current_case": {"event_type": "交通事故", "liability": "主要"}},
        }
        self.assertEqual(agent._traffic_intent(state), "traffic_medical_expense")
        query = agent._retrieval_query(state)
        for expected in ("社会保险法第三十条", "第三人不支付", "第七十五条", "交强险", "商业第三者责任险"):
            self.assertIn(expected, query)

    def test_standalone_medical_insurance_question_is_not_polluted_by_traffic_terms(self) -> None:
        """没有交通事故上下文的医保问题不能套用交通事故专项规则。"""
        agent = object.__new__(LawQaAgent)
        state = {"query": "医疗保险能赔吗", "original_query": "医疗保险能赔吗", "history_summary": ""}
        self.assertEqual(agent._traffic_intent(state), "")
        self.assertEqual(agent._retrieval_query(state), "医疗保险能赔吗")

    def test_civil_filing_material_query_expands_procedural_terms(self) -> None:
        """民事起诉材料问题应定向召回登记立案规则和程序材料。"""
        agent = object.__new__(LawQaAgent)
        query = agent._retrieval_query({"query": "去法院起诉别人需要准备哪些材料？"})
        self.assertIn("最高人民法院关于人民法院登记立案若干问题的规定", query)
        self.assertIn("送达地址确认书", query)
        self.assertIn("网上立案", query)

    def test_lending_limitation_query_expands_start_and_interruption_rules(self) -> None:
        """借款诉讼时效问题应同时召回起算、未约定期限及中断规则。"""
        agent = object.__new__(LawQaAgent)
        query = agent._retrieval_query({"query": "借钱给朋友一直不还，我最晚多久必须起诉？"})
        for expected in (
            "第一百八十八条",
            "第一百九十五条",
            "最高人民法院关于审理民事案件适用诉讼时效制度若干问题的规定",
            "约定还款日期",
            "未约定还款日期",
            "宽限期届满次日",
            "明确拒绝还款",
            "中断证据",
        ):
            self.assertIn(expected, query)

    def test_lending_followups_inherit_structured_timeline(self) -> None:
        agent = object.__new__(LawQaAgent)
        case = {
            "civil_dispute_topic": "private_lending",
            "loan_amount_text": "10万元",
            "loan_due_date_text": "2024年6月30日前还款",
            "debt_acknowledgment_channel": "微信",
            "debt_acknowledgment_date_text": "2025年（具体日期待确认）",
            "repayment_promise_text": "年底一定还",
            "repayment_promise_deadline_text": "2025年年底（具体日期待确认）",
        }
        state = {
            "query": "泛化后的时效问题",
            "original_query": "那现在诉讼时效应该从什么时候重新算？",
            "history_summary": "用户：我借给朋友10万元。\n用户：借条写的是2024年6月30日前还款。",
            "legal_memory": {"current_case": case},
        }
        self.assertEqual(agent._loan_limitation_intent(state), "loan_limitation_interruption")
        query = agent._retrieval_query(state)
        for expected in ("10万元", "2024年6月30日前还款", "2025年（具体日期待确认）", "第一百九十五条"):
            self.assertIn(expected, query)

    def test_lending_fact_recall_is_identified_separately(self) -> None:
        agent = object.__new__(LawQaAgent)
        state = {
            "query": "总结案件",
            "original_query": "我借给朋友了多少钱，借条显示还款日期吗？他有说过要还吗？",
            "history_summary": "用户：我借给朋友10万元。",
            "legal_memory": {"current_case": {"civil_dispute_topic": "private_lending", "loan_amount_text": "10万元"}},
        }
        self.assertEqual(agent._loan_limitation_intent(state), "loan_fact_recall")

    def test_lease_repair_followup_does_not_drift_to_debt_collection(self) -> None:
        agent = object.__new__(LawQaAgent)
        state = {
            "query": "用户多次催告并持有聊天记录，下一步如何维权",
            "original_query": "我已经催过三次，还有微信聊天记录。",
            "history_summary": "用户：我租的房子一直漏水，房东不维修怎么办？",
            "legal_memory": {"current_case": {
                "civil_dispute_topic": "residential_lease_repair",
                "lease_user_role": "tenant",
                "rental_defect": "房屋漏水",
                "landlord_repair_status": "经通知仍未维修",
                "repair_notice_count": 3,
                "repair_notice_evidence": "微信聊天记录",
            }},
        }
        self.assertEqual(agent._lease_repair_intent(state), "lease_repair_notice_evidence")
        self.assertEqual(agent._loan_limitation_intent(state), "")
        query = agent._retrieval_query(state)
        for expected in ("房屋租赁", "第七百一十二条", "第七百一十三条", "repair_notice_count=3"):
            self.assertIn(expected, query)
        self.assertNotIn("民间借贷", query)
        self.assertNotIn("本金利息", query)

    def test_lease_repair_followups_use_distinct_intents_and_retrieval_terms(self) -> None:
        agent = object.__new__(LawQaAgent)
        case = {
            "civil_dispute_topic": "residential_lease_repair",
            "rental_defect": "房屋漏水",
            "repair_notice_count": 3,
            "repair_notice_evidence": "微信聊天记录",
            "rental_habitability_impact": "租赁房屋部分或全部无法居住",
        }
        base = {
            "history_summary": "用户：我租的房子一直漏水。\n用户：我已经催过三次，还有微信聊天记录。",
            "legal_memory": {"current_case": case},
        }

        notice = {**base, "original_query": "我已经催过三次，还有微信聊天记录。"}
        self.assertEqual(agent._lease_repair_intent(notice), "lease_repair_notice_evidence")
        notice_query = agent._retrieval_query(notice)
        self.assertIn("电子数据", notice_query)
        self.assertNotIn("押金返还", notice_query)

        termination = {**base, "original_query": "漏水已经导致卧室无法居住，我能解除合同吗？"}
        self.assertEqual(agent._lease_repair_intent(termination), "lease_repair_termination")
        termination_query = agent._retrieval_query(termination)
        self.assertIn("合同目的不能实现", termination_query)
        self.assertIn("第五百六十五条", termination_query)
        self.assertNotIn("押金扣除项目", termination_query)

        settlement = {**base, "original_query": "押金和剩余租金怎么办？"}
        self.assertEqual(agent._lease_repair_intent(settlement), "lease_repair_settlement")
        settlement_query = agent._retrieval_query(settlement)
        self.assertIn("押金返还", settlement_query)
        self.assertIn("剩余预付租金", settlement_query)
        self.assertNotIn("电子数据 原始载体", settlement_query)

    def test_lease_notice_date_fragment_inherits_rental_timeline(self) -> None:
        agent = object.__new__(LawQaAgent)
        state = {
            "original_query": "第三次是3月20日。",
            "history_summary": (
                "用户：我租的房子漏水。\n用户：房东叫张某。\n"
                "用户：第一次催修是今年3月1日。\n用户：第二次是3月10日。"
            ),
            "legal_memory": {"current_case": {
                "civil_dispute_topic": "residential_lease_repair",
                "landlord_name": "张某",
                "rental_defect": "房屋漏水",
                "repair_notice_count": 3,
                "repair_notice_dates": {
                    "1": "2026-03-01", "2": "2026-03-10", "3": "2026-03-20",
                },
            }},
        }
        self.assertEqual(agent._lease_repair_intent(state), "lease_repair_notice_timeline")
        self.assertEqual(agent._loan_limitation_intent(state), "")
        query = agent._retrieval_query(state)
        self.assertIn("repair_notice_dates=", query)
        self.assertIn("2026-03-20", query)
        self.assertIn("催修通知 时间线", query)
        self.assertNotIn("劳动合同", query)
        prompt = get_prompt("lease_repair_notice_timeline_system")
        self.assertIn("绝对不得猜测为劳动合同", prompt)
        self.assertIn("不得声称每一次维修催告", prompt)

    def test_landlord_name_fragment_is_treated_as_case_fact_update(self) -> None:
        agent = object.__new__(LawQaAgent)
        state = {
            "original_query": "房东叫张某。",
            "history_summary": "用户：我租的房子漏水。",
            "legal_memory": {"current_case": {
                "civil_dispute_topic": "residential_lease_repair",
                "landlord_name": "张某",
                "rental_defect": "房屋漏水",
            }},
        }
        self.assertEqual(agent._lease_repair_intent(state), "lease_repair_fact_update")
        query = agent._retrieval_query(state)
        self.assertIn("landlord_name=张某", query)
        self.assertIn("案件事实补充", query)
        prompt = get_prompt("lease_repair_fact_update_system")
        self.assertIn("不得输出押金", prompt)

    def test_computer_repair_cost_inherits_known_leak_damage_cause(self) -> None:
        agent = object.__new__(LawQaAgent)
        case = {
            "civil_dispute_topic": "residential_lease_repair",
            "landlord_name": "张某",
            "landlord_repair_status": "经通知仍未维修",
            "repair_notice_count": 3,
            "property_damage_cause": "房屋漏水",
            "damaged_property": "电脑",
            "property_repair_cost_yuan": 3000,
            "property_loss_claim_text": "漏水导致电脑损坏，维修费3000元",
        }
        state = {
            "original_query": "电脑维修花了3000元。",
            "history_summary": "用户：漏水导致电脑损坏。",
            "legal_memory": {"current_case": case},
        }
        self.assertEqual(agent._lease_repair_intent(state), "lease_repair_damage_update")
        query = agent._retrieval_query(state)
        self.assertIn("property_damage_cause=房屋漏水", query)
        self.assertIn("property_repair_cost_yuan=3000", query)
        self.assertIn("漏水导致电脑损坏", query)
        prompt = get_prompt("lease_repair_damage_update_system")
        self.assertIn("不得再次询问电脑为何损坏", prompt)
        self.assertIn("不得分叉讨论维修店收费", prompt)

    def test_lease_settlement_prompt_uses_plain_text_formula_and_example(self) -> None:
        prompt = get_prompt("lease_repair_settlement_system")
        self.assertIn("应退剩余租金＝日租金×", prompt)
        self.assertIn("计算示例（仅作演示）", prompt)
        self.assertIn("3000÷30＝100元", prompt)
        self.assertIn("应退剩余租金＝100×15＝1500元", prompt)
        self.assertIn("不得使用 LaTeX", prompt)

    def test_renovation_loss_followup_cannot_activate_lease_prompt(self) -> None:
        agent = object.__new__(LawQaAgent)
        state = {
            "original_query": "我想解除合同，并要求返还多收的工程款、赔偿临时租房费和返工费。",
            "history_summary": (
                "用户：我与装修公司签了装修合同。\n"
                "用户：到6月15日还是没有完工，我临时租房花了6000元。\n"
                "用户：卫生间防水没做好，已经渗水到楼下。"
            ),
            "legal_memory": {"current_case": {
                "civil_dispute_topic": "renovation_contract",
                "renovation_company_name": "安居装饰有限公司",
                "renovation_contract_total_yuan": 120000,
                "renovation_paid_yuan": 80000,
                "renovation_progress_date": "2026-04-30",
                "renovation_progress_percent": 60,
                "renovation_still_incomplete_as_of": "2026-06-15",
                "temporary_rent_loss_yuan": 6000,
                "renovation_repair_estimate_yuan": 15000,
            }},
        }
        self.assertEqual(agent._lease_repair_intent(state), "")
        self.assertEqual(agent._renovation_contract_intent(state), "renovation_termination_settlement")
        query = agent._retrieval_query(state)
        self.assertIn("房屋装饰装修合同", query)
        self.assertIn("renovation_progress_date=2026-04-30", query)
        self.assertIn("renovation_still_incomplete_as_of=2026-06-15", query)
        self.assertNotIn("第七百一十二条", query)
        prompt = get_prompt("renovation_contract_followup_system")
        self.assertIn("本案不是房屋租赁合同纠纷", prompt)
        self.assertIn("只能标注为暂估", prompt)

    def test_labor_limitation_prompt_guards_topic_return_boundaries(self) -> None:
        prompt = get_prompt("labor_arbitration_limitation_system")
        for required in (
            "禁止使用“完全具备资格”",
            "第一日至最后一日",
            "剩余时间区间",
            "不得只写“剩余一个月左右”",
            "无法证明送达的口头催促",
            "不得把普通询问",
            "普通裁决与终局裁决",
            "以裁决书载明的救济方式和期限为准",
            "已恢复事实—时效判断—仍需确认—立即行动",
            "控制在1000个中文字符以内",
        ):
            self.assertIn(required, prompt)

    def test_pleading_template_typo_expands_pleading_terms(self) -> None:
        """“起讼状”错别字仍应进入正式起诉状模板检索。"""
        agent = object.__new__(LawQaAgent)
        query = agent._retrieval_query({"query": "请给我一份拖欠贷款的民事起讼状模板"})
        self.assertIn("民事起诉状", query)
        self.assertIn("民间借贷纠纷", query)
        self.assertIn("证据目录", query)

    def test_self_defense_question_expands_boundary_dimensions(self) -> None:
        """正当防卫问法应检索互殴、防卫过当和性质转化边界。"""
        agent = object.__new__(LawQaAgent)
        query = agent._retrieval_query({"query": "别人先打我，我还手把他打伤了，算正当防卫吗？"})
        for expected in (
            "正当防卫", "不法侵害", "正在进行", "防卫意图", "必要限度",
            "防卫过当", "互殴认定", "侵害结束后反击", "特殊防卫",
        ):
            self.assertIn(expected, query)

    def test_termination_question_expands_compensation_boundaries(self) -> None:
        """辞退赔偿问法应同时检索 N、N+1、2N 及通常不补偿的边界。"""
        agent = object.__new__(LawQaAgent)
        query = agent._retrieval_query({
            "query": "公司没有理由就把我辞退了，我工作3年，月工资10000元，可以要求多少赔偿？"
        })
        for expected in (
            "经济补偿", "N+1", "代通知金", "违法解除赔偿金", "2N",
            "协商一致解除", "无过失性辞退", "经济性裁员", "员工过错辞退",
            "第四十七条", "第八十七条", "继续履行劳动合同",
        ):
            self.assertIn(expected, query)

    def test_wage_arrears_question_expands_remedy_and_entitlement_terms(self) -> None:
        """欠薪“怎么办”应召回证据、维权路径、权益和时效，而非只查公司责任。"""
        agent = object.__new__(LawQaAgent)
        query = agent._retrieval_query({"query": "公司拖欠我三个月工资怎么办？"})
        for expected in (
            "固定证据", "银行流水", "欠薪沟通记录", "书面催告", "劳动监察投诉",
            "12333", "支付令", "劳动仲裁", "仲裁时效", "强制执行",
            "拖欠工资本金", "解除劳动合同经济补偿", "加付赔偿金50%至100%",
            "不要擅自旷工", "被迫解除通知", "工资已结清", "拒不支付劳动报酬罪",
        ):
            self.assertIn(expected, query)

        reordered_query = agent._retrieval_query({"query": "公司三个月工资一直没给，我该怎么维权？"})
        self.assertIn("劳动监察投诉", reordered_query)
        self.assertIn("拖欠工资本金", reordered_query)

    def test_wage_arrears_amount_and_recovery_followups_are_distinct(self) -> None:
        agent = object.__new__(LawQaAgent)
        case = {
            "labor_dispute_topic": "wage_arrears",
            "monthly_salary_yuan": 8000,
            "work_years": 4.0,
            "wage_arrears_months": 2,
            "employment_ended": True,
        }
        base = {
            "history_summary": "用户：公司无理由辞退我，我工作4年，月工资8000元，可以赔多少？",
            "legal_memory": {"current_case": case},
        }

        amount_state = {**base, "original_query": "公司还拖欠我两个月工资。"}
        self.assertEqual(agent._labor_intent(amount_state), "wage_arrears_amount")
        amount_query = agent._retrieval_query(amount_state)
        self.assertIn("monthly_salary_yuan=8000", amount_query)
        self.assertIn("wage_arrears_months=2", amount_query)
        self.assertIn("欠薪本金与经济补偿分别计算", amount_query)
        self.assertNotIn("最短维权路径", amount_query)

        recovery_state = {
            **base,
            "history_summary": base["history_summary"] + "\n用户：公司还拖欠我两个月工资。",
            "original_query": "我只想先追回工资，应该怎么处理？",
        }
        self.assertEqual(agent._labor_intent(recovery_state), "wage_arrears_recovery")
        recovery_query = agent._retrieval_query(recovery_state)
        self.assertIn("最短维权路径", recovery_query)
        self.assertIn("仲裁请求拖欠工资本金", recovery_query)
        self.assertNotIn("欠薪本金与经济补偿分别计算", recovery_query)

        amount_prompt = get_prompt("labor_wage_arrears_amount_system")
        recovery_prompt = get_prompt("labor_wage_arrears_recovery_system")
        self.assertIn("8000元/月×2个月＝16000元", amount_prompt)
        self.assertIn("只先追回工资", recovery_prompt)
        self.assertNotEqual(amount_prompt, recovery_prompt)

    def test_labor_followup_routes_to_arbitration_limitation_without_termination_table(self) -> None:
        """欠薪后的离职/仲裁追问应围绕时效，不能被历史经济补偿内容带回 N 表。"""
        agent = object.__new__(LawQaAgent)
        state = {
            "query": "请分析用户可主张的全部劳动权益，包括经济补偿",
            "original_query": "我已经离职了，还能申请仲裁吗？",
            "history_summary": "用户：公司拖欠我三个月工资怎么办？\n助手：可以固定证据后维权。",
            "legal_memory": {"current_case": {"labor_dispute_topic": "wage_arrears", "employment_ended": True}},
        }
        self.assertEqual(agent._labor_intent(state), "labor_arbitration_limitation")
        query = agent._retrieval_query(state)
        self.assertIn("劳动关系终止后一年内提出", query)
        self.assertIn("紧急立案", query)
        self.assertNotIn("N+1", query)
        self.assertNotIn("2N", query)

    def test_wage_topic_return_ignores_intervening_private_lending_question(self) -> None:
        """切到借款后再返回欠薪，应恢复劳动时效上下文且不残留借贷检索词。"""
        agent = object.__new__(LawQaAgent)
        state = {
            "original_query": "回到刚才工资的问题，我已经离职了。",
            "history_summary": (
                "用户：公司拖欠我三个月工资。\n"
                "用户：顺便问一下，借钱给朋友没有借条能起诉吗？"
            ),
            "legal_memory": {"current_case": {
                "labor_dispute_topic": "wage_arrears",
                "wage_arrears_months": 3,
                "employment_ended": True,
            }},
        }
        self.assertEqual(agent._labor_intent(state), "labor_arbitration_limitation")
        query = agent._retrieval_query(state)
        self.assertIn("劳动关系终止后一年内提出", query)
        self.assertNotIn("民间借贷", query)
        self.assertNotIn("借条", query)

    def test_departure_month_followup_inherits_wage_arbitration_context(self) -> None:
        """仅补充离职月份时仍应继承欠薪仲裁上下文和已记忆的离职时间。"""
        agent = object.__new__(LawQaAgent)
        state = {
            "query": "综合评估劳动争议",
            "original_query": "我是去年12月离职的。",
            "history_summary": "用户：公司拖欠我三个月工资怎么办？\n用户：我已经离职了，还能申请仲裁吗？",
            "legal_memory": {"current_case": {
                "labor_dispute_topic": "wage_arrears",
                "labor_arbitration_question": True,
                "employment_end_date_text": "2025年12月（具体日期待确认）",
            }},
        }
        self.assertEqual(agent._labor_intent(state), "labor_arbitration_limitation")
        query = agent._retrieval_query(state)
        self.assertIn("2025年12月", query)
        self.assertIn("劳动争议申请仲裁时效一年", query)

    def test_labor_limitation_empty_result_fallback_uses_exact_law_and_article(self) -> None:
        """仲裁时效空召回应改用法名和第二十七条精确补检，避免有法条却无引用。"""
        agent = object.__new__(LawQaAgent)
        query = agent._retrieval_query({"targeted_labor_fallback": True})
        self.assertIn("劳动争议调解仲裁法", query)
        self.assertIn("第二十七条", query)
        self.assertNotIn("社保转移", query)


class ToolAndCitationTests(unittest.IsolatedAsyncioTestCase):
    """覆盖工具注册表和引用校验。"""

    async def test_default_tools_registered(self) -> None:
        """阶段四内置五个工具应全部可被注册表发现。"""
        registry = ToolRegistry()
        names = {schema["function"]["name"] for schema in registry.schemas()}
        self.assertEqual(
            names,
            {"web_search", "article_tree", "ocr_extract", "contract_clause_parser", "contract_risk_rules"},
        )

    async def test_citation_validator_rejects_missing_number(self) -> None:
        """回答引用不存在的编号时应校验失败。"""
        result = await CitationValidator().validate(
            answer="可以这样处理。[2]",
            citations=[{"chunk_id": "1", "text": "x"}],
        )
        self.assertFalse(result["passed"])
        self.assertIn(2, result["failed_ids"])


if __name__ == "__main__":
    unittest.main()

