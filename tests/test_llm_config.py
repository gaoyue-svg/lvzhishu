"""本文件测试 BYOK（用户自带 LLM 配置）核心逻辑：加密、脱敏、实例池缓存、Service CRUD。"""

import asyncio
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from backend.schemas.llm_config import SaveLlmConfigRequest
from backend.services import llm_config as svc
from backend.utils import crypto
from agent_service.llm.registry import clear, get_or_create, invalidate, _cache


class CryptoTests(unittest.TestCase):
    """加密、解密、脱敏测试。"""

    def test_encrypt_decrypt_roundtrip(self):
        """加密后解密应还原明文。"""
        plaintext = "sk-test-placeholder-0000000000000000"
        encrypted = crypto.encrypt(plaintext)
        self.assertNotEqual(plaintext, encrypted)
        self.assertEqual(crypto.decrypt(encrypted), plaintext)

    def test_encrypt_not_deterministic(self):
        """同一明文两次加密应产生不同密文（Fernet 带 IV）。"""
        plaintext = "sk-test-key"
        self.assertNotEqual(crypto.encrypt(plaintext), crypto.encrypt(plaintext))

    def test_mask_long_key(self):
        """长 Key 脱敏应保留首尾（前 8 位 + 后 4 位）。"""
        key = "sk-test-placeholder-0000000000000000"
        self.assertEqual(crypto.mask(key), "sk-test-...0000")

    def test_mask_short_key(self):
        """短 Key 脱敏应返回 ***。"""
        self.assertEqual(crypto.mask("short"), "***")
        self.assertEqual(crypto.mask("exactly12ch"), "***")


class LlmRegistryTests(unittest.TestCase):
    """LLM 实例池缓存测试。"""

    def setUp(self):
        clear()

    def tearDown(self):
        clear()

    def test_get_or_create_caches_instance(self):
        """同一 config 应复用缓存实例，不重复创建。"""
        config = MagicMock()
        config.id = 100
        config.provider = "deepseek"
        config.model_name = "deepseek-chat"
        config.api_base = ""
        config.api_key_encrypted = crypto.encrypt("sk-test")
        config.temperature = None
        config.max_tokens = None
        config.timeout = None
        config.retry = None

        with patch("agent_service.llm.registry.decrypt", return_value="sk-test"), \
             patch("agent_service.llm.registry.LLMFactory") as factory_cls:
            mock_llm = MagicMock()
            factory_cls.create.return_value = mock_llm

            llm1 = asyncio.run(get_or_create(config))
            llm2 = asyncio.run(get_or_create(config))

            self.assertIs(llm1, llm2)
            self.assertEqual(factory_cls.create.call_count, 1)
            self.assertEqual(_cache[100], mock_llm)

    def test_invalidate_clears_cache(self):
        """invalidate 应清除对应 config 的缓存，下次重建。"""
        config = MagicMock()
        config.id = 200
        config.provider = "deepseek"
        config.model_name = "deepseek-chat"
        config.api_base = ""
        config.api_key_encrypted = crypto.encrypt("sk-test")
        config.temperature = config.max_tokens = config.timeout = config.retry = None

        with patch("agent_service.llm.registry.decrypt", return_value="sk-test"), \
             patch("agent_service.llm.registry.LLMFactory") as factory_cls:
            factory_cls.create.return_value = MagicMock()
            asyncio.run(get_or_create(config))
            self.assertIn(200, _cache)

            invalidate(200)
            self.assertNotIn(200, _cache)


class LlmConfigServiceTests(unittest.TestCase):
    """Service 层 CRUD 逻辑测试（用 AsyncMock 模拟数据库）。"""

    def _make_config(self, user_id=1):
        """构造一个已存在的配置 ORM 对象。"""
        config = MagicMock()
        config.id = 1
        config.user_id = user_id
        config.provider = "deepseek"
        config.model_name = "deepseek-chat"
        config.api_base = ""
        config.api_key_encrypted = crypto.encrypt("sk-service-test")
        config.is_active = 1
        config.temperature = None
        config.max_tokens = None
        config.timeout = None
        config.retry = None
        config.created_at = datetime.now()
        config.updated_at = datetime.now()
        return config

    def test_get_config_not_found(self):
        """未配置时应返回 None。"""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        config = asyncio.run(svc.get_config(db, user_id=999))
        self.assertIsNone(config)

    def test_save_config_new_record(self):
        """新配置应调用 db.add 并 commit。"""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        with patch("backend.services.llm_config.invalidate") as inv:
            data = SaveLlmConfigRequest(
                provider="deepseek",
                model_name="deepseek-chat",
                api_base="",
                api_key="sk-new",
            )
            config = asyncio.run(svc.save_config(db, user_id=1, data=data))

            db.add.assert_called_once()
            db.commit.assert_awaited_once()
            db.refresh.assert_awaited_once()
            inv.assert_called_once()
            self.assertEqual(config.provider, "deepseek")

    def test_save_config_update_existing(self):
        """已存在配置应就地更新，不调用 db.add。"""
        existing = self._make_config()
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = existing
        db.execute = AsyncMock(return_value=result_mock)

        with patch("backend.services.llm_config.invalidate") as inv:
            data = SaveLlmConfigRequest(
                provider="openai",
                model_name="gpt-4o",
                api_base="https://api.openai.com/v1",
                api_key="sk-updated",
            )
            config = asyncio.run(svc.save_config(db, user_id=1, data=data))

            db.add.assert_not_called()
            db.commit.assert_awaited_once()
            inv.assert_called_once()
            self.assertEqual(config.provider, "openai")
            self.assertEqual(config.model_name, "gpt-4o")

    def test_delete_config_not_found_raises(self):
        """删除不存在的配置应抛 404。"""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(svc.delete_config(db, user_id=999))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_delete_config_success(self):
        """删除已存在配置应调用 db.delete 并 commit。"""
        existing = self._make_config()
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = existing
        db.execute = AsyncMock(return_value=result_mock)

        with patch("backend.services.llm_config.invalidate") as inv:
            asyncio.run(svc.delete_config(db, user_id=1))

            db.delete.assert_awaited_once_with(existing)
            db.commit.assert_awaited_once()
            inv.assert_called_once_with(1)

    def test_test_config_no_saved_and_no_params_raises(self):
        """既无已保存配置又未传完整参数应抛 400。"""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(svc.test_config(db, 1, None, None, None, None))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_test_config_with_explicit_params(self):
        """传入完整参数应直接测临时配置，不查数据库。"""
        db = AsyncMock()

        with patch("backend.services.llm_config.LLMFactory") as factory_cls:
            mock_llm = AsyncMock()
            mock_llm.chat = AsyncMock(return_value="pong")
            factory_cls.create.return_value = mock_llm

            result = asyncio.run(svc.test_config(
                db, 1, "deepseek", "deepseek-chat", "", "sk-test-explicit"
            ))

            db.execute.assert_not_called()
            self.assertTrue(result["success"])
            self.assertEqual(result["message"], "连接成功")
            self.assertGreaterEqual(result["latency_ms"], 0)

    def test_test_config_uses_saved_config(self):
        """不传参数时应查已保存配置并解密 Key 测试。"""
        existing = self._make_config()
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = existing
        db.execute = AsyncMock(return_value=result_mock)

        with patch("backend.services.llm_config.LLMFactory") as factory_cls, \
             patch("backend.services.llm_config.crypto.decrypt", return_value="sk-service-test"):
            mock_llm = AsyncMock()
            mock_llm.chat = AsyncMock(return_value="ok")
            factory_cls.create.return_value = mock_llm

            result = asyncio.run(svc.test_config(db, 1, None, None, None, None))

            self.assertTrue(result["success"])
            factory_cls.create.assert_called_once_with(
                provider="deepseek",
                model_name="deepseek-chat",
                api_base=None,
                api_key="sk-service-test",
            )

    def test_test_config_llm_failure_returns_not_success(self):
        """LLM 调用失败时 success=False，不抛异常。"""
        db = AsyncMock()

        with patch("backend.services.llm_config.LLMFactory") as factory_cls:
            mock_llm = AsyncMock()
            mock_llm.chat = AsyncMock(side_effect=RuntimeError("network error"))
            factory_cls.create.return_value = mock_llm

            result = asyncio.run(svc.test_config(
                db, 1, "deepseek", "deepseek-chat", "", "sk-bad"
            ))

            self.assertFalse(result["success"])
            self.assertIn("network error", result["message"])

    def test_builtin_providers_complete(self):
        """内置 provider 列表应包含 deepseek/openai/qwen 三个。"""
        names = [p["name"] for p in svc.BUILTIN_PROVIDERS]
        self.assertIn("deepseek", names)
        self.assertIn("openai", names)
        self.assertIn("qwen", names)
        for p in svc.BUILTIN_PROVIDERS:
            self.assertTrue(p["label"])
            self.assertIsInstance(p["popular_models"], list)


if __name__ == "__main__":
    unittest.main()
