"""本文件实现基于 Redis 的会话记忆读取，供 Router 注入多轮法律上下文。"""

from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from agent_service.router.models import LegalMemory
from backend.config import settings
from backend.utils.logger import get_logger

logger = get_logger(__name__)


class RedisMemory:
    """读取和维护活跃会话的短期法律记忆。"""

    def __init__(self, redis: Redis | None, ttl: int | None = None) -> None:
        """保存 Redis 客户端和默认 TTL。"""
        self.redis = redis
        self.ttl = ttl or settings.agent_memory_ttl

    async def load(self, conversation_id: str) -> LegalMemory | None:
        """读取结构化法律记忆；Redis 不可用时静默降级为空。"""
        payload = await self._load_payload(conversation_id)
        if not payload:
            return None
        memory_payload = payload.get("legal_memory") if "legal_memory" in payload else payload
        if not isinstance(memory_payload, dict):
            return None
        return LegalMemory.model_validate(memory_payload)

    async def load_summary(self, conversation_id: str) -> str | None:
        """读取“长期模型摘要 + 近期原文窗口”，供整条编排链识别省略追问。"""
        payload = await self._load_payload(conversation_id)
        if not payload:
            return None
        summary = payload.get("history_summary") or payload.get("summary")
        return str(summary) if summary else None

    async def load_files(self, conversation_id: str) -> list[dict[str, Any]]:
        """读取当前会话已上传文件列表，合同审查路由依赖该上下文。"""
        payload = await self._load_payload(conversation_id)
        if not payload:
            return []
        files = payload.get("uploaded_files") or payload.get("files") or []
        return list(files) if isinstance(files, list) else []

    async def update(self, conversation_id: str, legal_memory: LegalMemory | dict[str, Any]) -> None:
        """更新法律记忆；业务 Agent 结束后可复用该方法写回 Redis。"""
        if self.redis is None or not conversation_id:
            return
        payload = await self._load_payload(conversation_id) or {}
        if isinstance(legal_memory, LegalMemory):
            payload["legal_memory"] = legal_memory.model_dump(mode="json")
        else:
            payload["legal_memory"] = legal_memory
        try:
            await self.redis.set(self._key(conversation_id), json.dumps(payload, ensure_ascii=False), ex=self.ttl)
        except RedisError as exc:
            logger.warning("法律记忆写入 Redis 失败: %s", exc.__class__.__name__)

    async def update_summary(self, conversation_id: str, history_summary: str) -> None:
        """保存双层压缩记忆；与结构化记忆共用 Key 和 TTL。"""
        if self.redis is None or not conversation_id:
            return
        payload = await self._load_payload(conversation_id) or {}
        payload["history_summary"] = history_summary
        try:
            await self.redis.set(self._key(conversation_id), json.dumps(payload, ensure_ascii=False), ex=self.ttl)
        except RedisError as exc:
            logger.warning("会话摘要写入 Redis 失败: %s", exc.__class__.__name__)

    async def save_files(self, conversation_id: str, files: list[dict[str, Any]]) -> None:
        """持久化会话已上传文件引用，供后续轮次 load_files 自动复用。"""
        if self.redis is None or not conversation_id:
            return
        payload = await self._load_payload(conversation_id) or {}
        payload["uploaded_files"] = files
        try:
            await self.redis.set(self._key(conversation_id), json.dumps(payload, ensure_ascii=False), ex=self.ttl)
        except RedisError as exc:
            logger.warning("会话文件引用写入 Redis 失败: %s", exc.__class__.__name__)

    async def _load_payload(self, conversation_id: str) -> dict[str, Any]:
        """读取并解析 Redis 中的会话记忆 JSON。"""
        if self.redis is None or not conversation_id:
            return {}
        try:
            raw = await self.redis.get(self._key(conversation_id))
        except RedisError as exc:
            logger.warning("法律记忆读取 Redis 失败: %s", exc.__class__.__name__)
            return {}
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("法律记忆 JSON 解析失败: conversation_id=%s", conversation_id)
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _key(conversation_id: str) -> str:
        """生成短期记忆 Redis Key。"""
        return f"lawrag:memory:{conversation_id}"
