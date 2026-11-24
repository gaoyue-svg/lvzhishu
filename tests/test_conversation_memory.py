"""短期会话记忆的事实提取、覆盖和滚动窗口测试。"""

from __future__ import annotations

import unittest
from datetime import date

from agent_service.memory.conversation import (
    append_history,
    compress_history_with_llm,
    enrich_legal_memory,
    split_memory_context,
)


class ConversationMemoryTests(unittest.TestCase):
    def test_extracts_strong_memory_case(self) -> None:
        memory = enrich_legal_memory(
            None,
            history_summary="用户：我叫测试甲，对方叫测试乙，事故发生在测试路口，我负主要责任。",
            current_query="对方叫什么？事故发生在哪里？我承担什么责任？",
        )
        case = memory["current_case"]
        self.assertEqual(case["user_name"], "测试甲")
        self.assertEqual(case["counterparty_name"], "测试乙")
        self.assertEqual(case["location"], "测试路口")
        self.assertEqual(case["liability"], "主要")

    def test_current_correction_overrides_old_fact(self) -> None:
        memory = enrich_legal_memory(
            {"current_case": {"liability": "主要"}},
            history_summary="用户：交警最初认定我负主要责任。",
            current_query="交警刚刚改成认定我负全部责任。",
        )
        self.assertEqual(memory["current_case"]["liability"], "全部")

    def test_negative_flags_win_over_keyword_substrings(self) -> None:
        memory = enrich_legal_memory(
            None,
            history_summary="",
            current_query="没有逃逸，也没有酒驾。",
        )
        self.assertFalse(memory["current_case"]["escaped"])
        self.assertFalse(memory["current_case"]["drunk_driving"])

    def test_extracts_traffic_vehicle_injury_and_conjoined_negative_facts(self) -> None:
        memory = enrich_legal_memory(
            None,
            history_summary="用户：我开车撞到了一个骑电动车的人。\n用户：交警认定我负主要责任。",
            current_query="对方只是轻伤，也没有逃逸和酒驾，我会坐牢吗？",
        )
        case = memory["current_case"]
        self.assertEqual(case["event_type"], "交通事故")
        self.assertEqual(case["user_vehicle_type"], "机动车")
        self.assertEqual(case["counterparty_vehicle_type"], "电动车")
        self.assertEqual(case["counterparty_injury_description"], "轻伤")
        self.assertEqual(case["liability"], "主要")
        self.assertFalse(case["escaped"])
        self.assertFalse(case["drunk_driving"])

    def test_assistant_conditional_escape_is_not_case_fact(self) -> None:
        memory = enrich_legal_memory(
            None,
            history_summary=(
                "用户：我叫测试甲，对方叫测试乙，事故发生在测试路口，我负主要责任。\n"
                "助手：若存在肇事逃逸情节，将面临更严重处罚。"
            ),
            current_query="对方叫什么？事故发生在哪里？我承担什么责任？",
        )
        case = memory["current_case"]
        self.assertNotIn("escaped", case)
        self.assertEqual(case["counterparty_name"], "测试乙")
        self.assertEqual(case["location"], "测试路口")
        self.assertEqual(case["liability"], "主要")

    def test_stale_polluted_escape_flag_is_removed_without_user_support(self) -> None:
        memory = enrich_legal_memory(
            {"current_case": {"escaped": True, "liability": "主要"}},
            history_summary="用户：我负主要责任。\n助手：如果逃逸，处罚会加重。",
            current_query="我承担什么责任？",
        )
        self.assertNotIn("escaped", memory["current_case"])

    def test_explicit_user_escape_fact_is_preserved(self) -> None:
        memory = enrich_legal_memory(
            None,
            history_summary="用户：事故后我肇事逃逸了。",
            current_query="我会承担什么责任？",
        )
        self.assertTrue(memory["current_case"]["escaped"])

    def test_append_history_keeps_latest_content_with_budget(self) -> None:
        summary = append_history(
            "旧内容" * 2000,
            query="最新问题",
            answer="最新回答",
            max_tokens=100,
        )
        self.assertLessEqual(len(summary), 800)
        self.assertIn("用户：最新问题", summary)
        self.assertIn("助手：最新回答", summary)

    def test_labor_followups_preserve_wage_departure_and_arbitration_facts(self) -> None:
        memory = enrich_legal_memory(
            None,
            history_summary=(
                "用户：公司拖欠我三个月工资怎么办？\n"
                "助手：建议固定证据。\n"
                "用户：我已经离职了，还能申请仲裁吗？"
            ),
            current_query="我是去年12月离职的。",
        )
        case = memory["current_case"]
        self.assertEqual(case["labor_dispute_topic"], "wage_arrears")
        self.assertTrue(case["employment_ended"])
        self.assertTrue(case["labor_arbitration_question"])
        self.assertEqual(case["employment_end_year"], 2025)
        self.assertEqual(case["employment_end_month"], 12)
        self.assertIn("具体日期待确认", case["employment_end_date_text"])

    def test_lending_followups_preserve_amount_due_date_and_acknowledgment(self) -> None:
        memory = enrich_legal_memory(
            None,
            history_summary=(
                "用户：我借给朋友10万元，他一直不还，我什么时候必须起诉？\n"
                "用户：借条写的是2024年6月30日前还款。\n"
                "用户：去年他通过微信承认欠钱，还说年底一定还。"
            ),
            current_query="那现在诉讼时效应该从什么时候重新算？",
        )
        case = memory["current_case"]
        self.assertEqual(case["civil_dispute_topic"], "private_lending")
        self.assertEqual(case["loan_amount_text"], "10万元")
        self.assertEqual(case["loan_amount_yuan"], 100000)
        self.assertEqual(case["loan_due_date_iso"], "2024-06-30")
        self.assertEqual(case["loan_due_date_text"], "2024年6月30日前还款")
        self.assertTrue(case["debtor_acknowledged_debt"])
        self.assertEqual(case["debt_acknowledgment_channel"], "微信")
        self.assertEqual(case["debt_acknowledgment_date_text"], "2025年（具体日期待确认）")
        self.assertTrue(case["debtor_promised_repayment"])
        self.assertEqual(case["repayment_promise_deadline_text"], "2025年年底（具体日期待确认）")

    def test_lease_repair_followup_preserves_defect_notices_and_wechat_evidence(self) -> None:
        memory = enrich_legal_memory(
            None,
            history_summary="用户：我租的房子一直漏水，房东不维修怎么办？",
            current_query="我已经催过三次，还有微信聊天记录。",
        )
        case = memory["current_case"]
        self.assertEqual(case["civil_dispute_topic"], "residential_lease_repair")
        self.assertEqual(case["lease_user_role"], "tenant")
        self.assertEqual(case["rental_defect"], "房屋漏水")
        self.assertEqual(case["landlord_repair_status"], "经通知仍未维修")
        self.assertEqual(case["repair_notice_count"], 3)
        self.assertEqual(case["repair_notice_evidence"], "微信聊天记录")

    def test_labor_memory_preserves_salary_tenure_and_arrears_months(self) -> None:
        memory = enrich_legal_memory(
            None,
            history_summary="用户：公司无理由辞退我，我工作4年，月工资8000元，可以赔多少？",
            current_query="公司还拖欠我两个月工资。",
        )
        case = memory["current_case"]
        self.assertEqual(case["monthly_salary_yuan"], 8000)
        self.assertEqual(case["work_years"], 4.0)
        self.assertEqual(case["wage_arrears_months"], 2)
        self.assertTrue(case["employment_ended"])
        self.assertTrue(case["employment_termination_event"])
        self.assertEqual(case["labor_dispute_topic"], "wage_arrears")

    def test_lease_repair_memory_preserves_habitability_termination_and_settlement(self) -> None:
        memory = enrich_legal_memory(
            None,
            history_summary=(
                "用户：我租的房子一直漏水，房东不维修怎么办？\n"
                "用户：我已经催过三次，还有微信聊天记录。\n"
                "用户：漏水已经导致卧室无法居住，我能解除合同吗？"
            ),
            current_query="押金和剩余租金怎么办？",
        )
        case = memory["current_case"]
        self.assertEqual(case["rental_habitability_impact"], "租赁房屋部分或全部无法居住")
        self.assertTrue(case["tenant_seeks_termination"])
        self.assertTrue(case["lease_settlement_question"])

    def test_lease_repair_memory_preserves_ordinal_notice_timeline(self) -> None:
        memory = enrich_legal_memory(
            None,
            history_summary=(
                "用户：我租的房子漏水。\n"
                "用户：房东叫张某。\n"
                "用户：我第一次催修是今年3月1日。\n"
                "用户：第二次是3月10日。"
            ),
            current_query="第三次是3月20日。",
        )
        case = memory["current_case"]
        current_year = date.today().year
        self.assertEqual(case["civil_dispute_topic"], "residential_lease_repair")
        self.assertEqual(case["landlord_name"], "张某")
        self.assertEqual(case["repair_notice_count"], 3)
        self.assertEqual(case["repair_notice_dates"], {
            "1": f"{current_year}-03-01",
            "2": f"{current_year}-03-10",
            "3": f"{current_year}-03-20",
        })

    def test_long_lease_dialogue_preserves_damage_cost_and_evidence_chain(self) -> None:
        memory = enrich_legal_memory(
            None,
            history_summary=(
                "用户：我租的房子漏水。\n用户：房东叫张某。\n"
                "用户：我第一次催修是今年3月1日。\n用户：第二次是3月10日。\n"
                "用户：第三次是3月20日。\n用户：房东一直没有维修。\n"
                "用户：漏水导致电脑损坏。\n用户：电脑维修花了3000元。\n"
                "用户：我有维修发票。\n用户：我也有三次催修记录。"
            ),
            current_query="我现在想解除合同。",
        )
        case = memory["current_case"]
        self.assertEqual(case["landlord_name"], "张某")
        self.assertEqual(case["landlord_repair_status"], "经通知仍未维修")
        self.assertEqual(case["repair_notice_count"], 3)
        self.assertEqual(case["property_damage_cause"], "房屋漏水")
        self.assertEqual(case["damaged_property"], "电脑")
        self.assertEqual(case["property_repair_cost_yuan"], 3000)
        self.assertTrue(case["property_repair_invoice"])
        self.assertEqual(case["property_loss_claim_text"], "漏水导致电脑损坏，维修费3000元")
        self.assertTrue(case["tenant_seeks_termination"])

        recalled = enrich_legal_memory(
            memory,
            history_summary=(
                "用户：我租的房子漏水。\n用户：房东叫张某。\n"
                "用户：漏水导致电脑损坏。\n用户：电脑维修花了3000元。"
            ),
            current_query="我之前说的房东叫什么？电脑损失是多少？",
        )
        self.assertEqual(recalled["current_case"]["landlord_name"], "张某")
        self.assertEqual(recalled["current_case"]["property_repair_cost_yuan"], 3000)

    def test_renovation_dialogue_does_not_drift_to_residential_lease(self) -> None:
        memory = enrich_legal_memory(
            None,
            history_summary=(
                "用户：我找安居装饰有限公司装修新房，合同总价12万元，今年1月5日签约。\n"
                "用户：我已经分三次支付了8万元，合同约定今年4月30日前完工。\n"
                "用户：到4月30日只完成了大约60%。\n"
                "用户：我在5月10日通过微信和EMS催告，公司承诺5月31日前完工。\n"
                "用户：到6月15日还是没有完工，我临时租房花了6000元。\n"
                "用户：我还发现卫生间防水没做好，已经渗水到楼下。\n"
                "用户：第三方检测报告说返工修复大约需要15000元。"
            ),
            current_query="我想解除合同，并要求返还多收的工程款、赔偿临时租房费和返工费。",
        )
        case = memory["current_case"]
        self.assertEqual(case["civil_dispute_topic"], "renovation_contract")
        self.assertEqual(case["renovation_company_name"], "安居装饰有限公司")
        self.assertEqual(case["renovation_contract_total_yuan"], 120000)
        self.assertEqual(case["renovation_paid_yuan"], 80000)
        self.assertEqual(case["renovation_progress_percent"], 60)
        self.assertEqual(case["renovation_progress_date"], f"{date.today().year}-04-30")
        self.assertEqual(case["renovation_still_incomplete_as_of"], f"{date.today().year}-06-15")
        self.assertEqual(case["temporary_rent_loss_yuan"], 6000)
        self.assertEqual(case["renovation_repair_estimate_yuan"], 15000)
        self.assertTrue(case["renovation_downstairs_damage"])
        self.assertTrue(case["renovation_third_party_report"])
        self.assertNotEqual(case["civil_dispute_topic"], "residential_lease_repair")


if __name__ == "__main__":
    unittest.main()


class _SummaryLLM:
    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages, **kwargs):
        self.calls += 1
        return "- 争议类型：欠薪\n- 用户已离职\n- 当前诉求：确认仲裁时效"


class CompressedMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_short_history_keeps_recent_text_without_model_call(self) -> None:
        llm = _SummaryLLM()
        value = await compress_history_with_llm(
            "",
            query="公司拖欠工资怎么办？",
            answer="请先固定证据。",
            llm=llm,
            max_tokens=4000,
            timeout=5,
        )
        summary, recent = split_memory_context(value)
        self.assertEqual(summary, "无")
        self.assertIn("公司拖欠工资", recent)
        self.assertEqual(llm.calls, 0)

    async def test_over_budget_history_is_model_summarized_and_recent_turn_survives(self) -> None:
        llm = _SummaryLLM()
        previous = "\n".join(f"用户：第{i}轮事实" + "很长内容" * 80 for i in range(20))
        value = await compress_history_with_llm(
            previous,
            query="我是去年12月离职的。",
            answer="需要按具体离职日判断。",
            llm=llm,
            max_tokens=900,
            timeout=5,
        )
        summary, recent = split_memory_context(value)
        self.assertEqual(llm.calls, 1)
        self.assertIn("争议类型：欠薪", summary)
        self.assertIn("去年12月离职", recent)
