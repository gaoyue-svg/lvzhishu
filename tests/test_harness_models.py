"""Harness 数据表 ORM 模型测试（doc 21 §5）。"""

import unittest

from backend.models import AgentRunTrace, EvaluationResult, LlmUsage
from backend.models.harness import AgentRunTrace as HarnessAgentRunTrace


class TestHarnessModels(unittest.TestCase):
    """校验三张新表的表名与关键列。"""

    def test_agent_run_trace_columns(self):
        """agent_run_trace 表结构。"""
        self.assertEqual(AgentRunTrace.__tablename__, "agent_run_trace")
        self.assertIn("trace_id", AgentRunTrace.__table__.columns)
        self.assertIn("step_traces", AgentRunTrace.__table__.columns)
        self.assertIn("agent_results_summary", AgentRunTrace.__table__.columns)
        self.assertIn("status", AgentRunTrace.__table__.columns)
        # trace_id 在 ORM 层声明为唯一
        self.assertTrue(AgentRunTrace.__table__.columns["trace_id"].unique)

    def test_llm_usage_columns(self):
        """llm_usage 表结构。"""
        self.assertEqual(LlmUsage.__tablename__, "llm_usage")
        for column in ("trace_id", "provider", "model", "prompt_tokens", "completion_tokens", "total_tokens", "purpose"):
            self.assertIn(column, LlmUsage.__table__.columns)

    def test_evaluation_result_columns(self):
        """evaluation_result 表结构。"""
        self.assertEqual(EvaluationResult.__tablename__, "evaluation_result")
        for column in ("trace_id", "mode", "citation_score", "coverage", "grounded_score", "hallucination"):
            self.assertIn(column, EvaluationResult.__table__.columns)

    def test_models_exported_from_package(self):
        """三个模型已从 backend.models 顶层导出。"""
        self.assertIs(AgentRunTrace, HarnessAgentRunTrace)


if __name__ == "__main__":
    unittest.main()
