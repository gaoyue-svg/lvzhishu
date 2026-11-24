"""合同分析（会话上传模式）功能单元测试。"""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from agent_service.agents.contract.elements_agent import ContractElementsAgent
from agent_service.agents.contract.legal_rag_agent import LegalRAGAgent
from agent_service.orchestrator.pipeline import extract_contract_payload
from agent_service.orchestrator.workflow import build_preset_plan, match_preset_workflow


class TestLegalRagDeterministicReason(unittest.IsolatedAsyncioTestCase):
    """contract_rag 中间摘要不应再触发 LLM，也不得编造引用。"""

    async def test_reason_uses_only_real_citation_indexes(self):
        agent = object.__new__(LegalRAGAgent)
        result = await agent.reason_node(
            {
                "citations": [
                    {"index": 4, "law_name": "中华人民共和国民法典", "article_no": "五百八十五"},
                ]
            }
        )
        self.assertIn("[4]", result["answer"])
        self.assertNotIn("[1]", result["answer"])

    async def test_reason_without_citations_has_no_numeric_reference(self):
        agent = object.__new__(LegalRAGAgent)
        result = await agent.reason_node({"citations": []})
        self.assertNotRegex(result["answer"], r"\[\d+\]")


class TestUploadWorkflowMatch(unittest.TestCase):
    """上传模式预置工作流匹配与建图。"""

    def test_match_upload_mode(self):
        """会话上传了合同（uploaded_contracts 非空）时命中上传专用工作流。"""
        self.assertEqual(
            match_preset_workflow({"category": "contract"}, {"uploaded_contracts": [{"upload_id": "1"}]}),
            "contract_review_upload",
        )

    def test_match_entry_hint_upload(self):
        """entry_hint=contract_review_upload 同样命中。"""
        self.assertEqual(
            match_preset_workflow({}, {"entry_hint": "contract_review_upload"}),
            "contract_review_upload",
        )

    def test_match_legacy_kb_mode_unaffected(self):
        """知识库 document_id 模式仍走原 contract_review 工作流。"""
        self.assertEqual(
            match_preset_workflow({"entry_hint": "contract_review"}, {"document_id": "42"}),
            "contract_review",
        )

    def test_upload_preset_steps_order(self):
        """上传模式步骤顺序：clause → rule/elements/rag(并行) → risk_report → synthesize。"""
        plan = build_preset_plan("contract_review_upload", query="审查合同")
        self.assertIsNotNone(plan)
        self.assertEqual(
            [s.agent for s in plan.steps],
            [
                "contract_clause",
                "contract_rule",
                "contract_elements",
                "contract_rag",
                "contract_risk_report",
                "synthesize",
            ],
        )
        by_id = {s.step_id: s for s in plan.steps}
        self.assertEqual(by_id["w5"].deps, ["w2", "w3", "w4"])
        self.assertEqual(by_id["w2"].deps, ["w1"])
        self.assertEqual(by_id["w3"].deps, ["w1"])
        self.assertEqual(by_id["w4"].deps, ["w1"])


class TestExtractContractPayload(unittest.TestCase):
    """从 run slots 提取结构化摘要/要素/风险。"""

    def test_parses_elements_and_risks(self):
        slots = {
            "clauses": [{"text": "x"}],
            "elements": json.dumps(
                {"summary": "摘要", "elements": {"amount": "10万", "party_a": {"name": "甲", "role": "买方"}}}
            ),
            "report": json.dumps(
                [{"clause": "第五条", "level": "high", "title": "违约金过高", "description": "d", "suggestion": "s"}],
                ensure_ascii=False,
            ),
        }
        payload = extract_contract_payload(slots)
        self.assertEqual(payload["summary"], "摘要")
        self.assertEqual(payload["elements"]["amount"], "10万")
        self.assertEqual(payload["risks"][0]["title"], "违约金过高")

    def test_falls_back_to_rule_risks(self):
        """风险报告缺失时回退到规则工具结果。"""
        slots = {"rule_risks": [{"result": {"risks": [{"title": "rule"}]}}], "elements": "{}"}
        payload = extract_contract_payload(slots)
        self.assertEqual(payload["risks"][0]["title"], "rule")

    def test_empty_slots(self):
        self.assertEqual(extract_contract_payload({}), {"summary": "", "elements": {}, "risks": []})


class TestContractElementsAgent(unittest.TestCase):
    """要素提取 Agent 的 JSON 解析。"""

    def test_parse_elements_json(self):
        parsed = ContractElementsAgent.parse_elements_json(
            '```json\n{"summary": "摘要", "elements": {"amount": "100万"}}\n```'
        )
        self.assertEqual(parsed["summary"], "摘要")
        self.assertEqual(parsed["elements"]["amount"], "100万")

    def test_parse_elements_json_invalid(self):
        self.assertEqual(ContractElementsAgent.parse_elements_json(""), {})

    def test_reason_messages_shape(self):
        # 纯方法测试：绕过 BaseAgent 构造（构造需要完整依赖注入）。
        agent = object.__new__(ContractElementsAgent)
        messages = agent._build_reason_messages(
            {"retrieved_chunks": [{"article_no": "第一条", "title": "付款", "text": "每月付款", "chunk_level": "section"}]}
        )
        self.assertIn("JSON", messages[1]["content"])
        self.assertIn("summary", messages[1]["content"])


class TestReportExporter(unittest.TestCase):
    """审查报告 .docx 导出。"""

    def test_builds_valid_docx(self):
        from docx import Document

        from backend.services.report_exporter import build_contract_report_docx

        buffer = build_contract_report_docx(
            report_markdown="## 风险\n- 违约金过高\n| 要素 | 值 |\n| --- | --- |\n| 金额 | 10万 |",
            elements={"amount": "10万", "party_a": {"name": "甲", "role": "买方"}},
            summary="合同摘要",
            filename="租赁合同.docx",
        )
        buffer.seek(0)
        document = Document(buffer)
        texts = [p.text for p in document.paragraphs]
        self.assertTrue(any("合同审查报告" in t for t in texts))
        self.assertTrue(any("合同摘要" in t for t in texts))
        self.assertGreaterEqual(len(document.tables), 1)

    def test_legal_document_export_uses_request_title_and_removes_analysis(self):
        from docx import Document

        from backend.services.report_exporter import build_legal_document_docx

        markdown = """## 直接结论
这里是分析。

## 房屋租赁合同模板
出租人（甲方）：________

第一条 租赁房屋
房屋地址：________。

## 核心条款的法律边界与适用条件
这里不应进入合同。
"""
        buffer = build_legal_document_docx(
            content_markdown=markdown,
            request_text="请给我一份房屋租赁合同模板",
        )
        document = Document(buffer)
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        self.assertIn("房屋租赁合同", text)
        self.assertIn("出租人（甲方）", text)
        self.assertNotIn("直接结论", text)
        self.assertNotIn("法律边界", text)
        self.assertNotIn("AI 辅助生成", text)

    def test_legal_document_export_converts_instruction_placeholders_to_blanks(self):
        from docx import Document

        from backend.services.report_exporter import build_legal_document_docx

        buffer = build_legal_document_docx(
            content_markdown="""民事起诉状

原告：【姓名/名称】
借款本金：人民币【填写具体金额】元
日期：【年】【月】【日】
""",
            request_text="请给我一份借贷纠纷民事起诉状模板",
        )
        document = Document(buffer)
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        self.assertNotIn("填写具体金额", text)
        self.assertNotIn("姓名/名称", text)
        self.assertIn("__________", text)


class TestKnowledgeTemplateSelection(unittest.IsolatedAsyncioTestCase):
    """正式文书导出应优先选择用户知识库中的同案由原始模板。"""

    async def test_debt_complaint_selects_lending_template(self):
        from agent_service.routers.agent import _find_matching_knowledge_template

        generic = SimpleNamespace(filename="民事起诉状.docx")
        lending = SimpleNamespace(filename="民事起讼状(借贷纠纷).docx")
        scalar_result = MagicMock()
        scalar_result.scalars.return_value.all.return_value = [generic, lending]
        db = MagicMock()
        db.execute = AsyncMock(return_value=scalar_result)

        selected = await _find_matching_knowledge_template(
            db,
            user_id=1,
            request_text="请给我一份拖欠贷款的民事起讼状模板",
        )

        self.assertIs(selected, lending)

    async def test_selects_each_supported_civil_complaint_original(self):
        from agent_service.routers.agent import _find_matching_knowledge_template

        lending = SimpleNamespace(filename="民事起讼状(借贷纠纷).docx")
        labor = SimpleNamespace(filename="民事起讼状(劳动争议纠纷).docx")
        divorce = SimpleNamespace(filename="民事起讼状(离婚纠纷).docx")
        scalar_result = MagicMock()
        scalar_result.scalars.return_value.all.return_value = [divorce, labor, lending]
        db = MagicMock()
        db.execute = AsyncMock(return_value=scalar_result)

        cases = (
            ("请给我一份拖欠贷款的民事起讼状模板", lending),
            ("请生成一份欠薪劳动争议民事起诉状", labor),
            ("我需要一份离婚纠纷民事起诉状模板", divorce),
        )
        for request_text, expected in cases:
            with self.subTest(request_text=request_text):
                selected = await _find_matching_knowledge_template(
                    db,
                    user_id=1,
                    request_text=request_text,
                )
                self.assertIs(selected, expected)

    async def test_generic_complaint_does_not_guess_dispute_type(self):
        from agent_service.routers.agent import _find_matching_knowledge_template

        db = MagicMock()
        db.execute = AsyncMock()
        selected = await _find_matching_knowledge_template(
            db,
            user_id=1,
            request_text="请给我一份民事起诉状模板",
        )
        self.assertIsNone(selected)
        db.execute.assert_not_awaited()


class TestOcrAliyunFallback(unittest.TestCase):
    """阿里云 OCR 未配置密钥时安全降级为空串。"""

    def test_disabled_returns_empty(self):
        from backend.config import settings
        from backend.services.ocr_aliyun import ocr_image_aliyun, ocr_pdf_aliyun

        if settings.aliyun_ocr_enabled:
            self.skipTest("aliyun_ocr_enabled=true，跳过降级断言")
        self.assertEqual(ocr_image_aliyun("not_exists.png"), "")
        self.assertEqual(ocr_pdf_aliyun("not_exists.pdf"), "")


if __name__ == "__main__":
    unittest.main()
