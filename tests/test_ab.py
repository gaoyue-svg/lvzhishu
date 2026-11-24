"""A/B 分流框架测试（doc 21 Phase 3）。"""

import unittest
from unittest.mock import patch

from backend.config import settings

from agent_service.experiment.ab import SYNTHESIZER_AB, apply_experiment, assign_variant
from agent_service.prompts import get_active_prompt_versions, get_prompt, reset_prompt_versions


class TestAssignVariant(unittest.TestCase):
    """哈希分流确定性。"""

    def test_deterministic_per_user(self):
        self.assertEqual(assign_variant(1), assign_variant(1))
        self.assertEqual(assign_variant(999), assign_variant(999))

    def test_both_variants_occur(self):
        variants = {assign_variant(user_id) for user_id in range(1, 21)}
        self.assertTrue(variants.issubset({"A", "B"}))
        self.assertEqual(len(variants), 2)  # 20 个用户应覆盖 A/B 两组


class TestApplyExperiment(unittest.TestCase):
    """应用实验：设置版本覆盖 + 返回变体标签。"""

    @patch.object(settings, "experiment_enabled", True)
    def test_apply_sets_override_and_label(self):
        variant_label, token = apply_experiment(7)
        try:
            self.assertTrue(variant_label.startswith(f"{SYNTHESIZER_AB}:"))
            self.assertIn(variant_label.split(":")[-1], {"A", "B"})
            # 覆盖已生效：当前生效版本是变体对应版本
            self.assertEqual(get_active_prompt_versions(), {"synthesizer_system": variant_label.split(":")[-1].lower().replace("a", "v1").replace("b", "v2")})
        finally:
            if token is not None:
                reset_prompt_versions(token)

    @patch.object(settings, "experiment_enabled", True)
    def test_prompt_resolves_to_variant_version(self):
        variant_label, token = apply_experiment(7)
        try:
            variant = variant_label.split(":")[-1]
            expected = "v1" if variant == "A" else "v2"
            self.assertEqual(get_prompt("synthesizer_system"), get_prompt("synthesizer_system", version=expected))
        finally:
            if token is not None:
                reset_prompt_versions(token)

    @patch.object(settings, "experiment_enabled", False)
    def test_disabled_returns_none(self):
        variant_label, token = apply_experiment(7)
        self.assertEqual(variant_label, "none")
        self.assertIsNone(token)


if __name__ == "__main__":
    unittest.main()
