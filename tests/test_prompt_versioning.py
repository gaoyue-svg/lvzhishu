"""Prompt 版本管理与 A/B 覆盖测试（doc 21 Phase 3）。"""

import unittest
from unittest.mock import patch

from backend.config import settings

from agent_service.prompts import (
    format_prompt,
    get_active_prompt_versions,
    get_prompt,
    list_prompt_versions,
    reset_prompt_versions,
    set_prompt_versions,
)


class TestPromptVersioning(unittest.TestCase):
    """loader 版本解析。"""

    def test_synthesizer_has_two_versions(self):
        self.assertEqual(set(list_prompt_versions("synthesizer_system")), {"v1", "v2"})

    def test_default_is_v1(self):
        self.assertEqual(get_prompt("synthesizer_system"), get_prompt("synthesizer_system", version="v1"))

    def test_v2_distinct(self):
        self.assertNotEqual(get_prompt("synthesizer_system", version="v2"), get_prompt("synthesizer_system"))

    def test_unknown_version_raises(self):
        with self.assertRaises(KeyError):
            get_prompt("synthesizer_system", version="v9")

    def test_unknown_prompt_raises(self):
        with self.assertRaises(KeyError):
            get_prompt("no_such_prompt")

    def test_single_version_prompt_backward_compat(self):
        """未声明 versions 的 prompt 仍按原 API 工作。"""
        self.assertIsInstance(get_prompt("router_system"), str)

    def test_format_prompt_version(self):
        """user 模板按版本取（无多版本模板时走默认）。"""
        self.assertIsInstance(
            format_prompt(
                "base_reason_user",
                query="q",
                history_summary="",
                memory="m",
                context_text="c",
                risk_level="low",
                tool_calls=[],
                retry_hint="",
            ),
            str,
        )


class TestABOverride(unittest.TestCase):
    """请求级 A/B 版本覆盖。"""

    def test_set_override_changes_resolution(self):
        v1 = get_prompt("synthesizer_system")
        token = set_prompt_versions({"synthesizer_system": "v2"})
        try:
            self.assertEqual(get_prompt("synthesizer_system"), get_prompt("synthesizer_system", version="v2"))
            self.assertNotEqual(get_prompt("synthesizer_system"), v1)
            self.assertEqual(get_active_prompt_versions(), {"synthesizer_system": "v2"})
        finally:
            reset_prompt_versions(token)
        self.assertEqual(get_prompt("synthesizer_system"), v1)
        self.assertEqual(get_active_prompt_versions(), {})

    @patch.object(settings, "prompt_version_overrides", {"synthesizer_system": "v2"})
    def test_settings_override_used(self):
        self.assertEqual(get_prompt("synthesizer_system"), get_prompt("synthesizer_system", version="v2"))


if __name__ == "__main__":
    unittest.main()
