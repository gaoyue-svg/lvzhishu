"""本文件实现基于 Redis 与内容哈希的 Embedding 去重缓存。"""

import hashlib
import json
from enum import Enum

from redis.asyncio import Redis
from redis.exceptions import RedisError

from backend.utils.logger import get_logger

logger = get_logger(__name__)


class CacheScope(str, Enum):
    """定义缓存按租户隔离或跨租户共享。"""

    TENANT = "tenant"
    GLOBAL = "global"


class EmbeddingCache:
    """以 provider、模型、维度和增强文本共同计算 SHA256 缓存键。"""

    def __init__(self, redis: Redis, scope: CacheScope = CacheScope.TENANT, ttl: int = 2592000):
        """保存 Redis 连接、隔离范围和默认过期时间。"""
        self.redis = redis
        self.scope = scope
        self.ttl = ttl
        self.prefix = "lawrag:embed_cache:"

    def compute_hash(
        self, enhanced_text: str, tenant_id: str, provider: str, model: str, dimension: int
    ) -> str:
        """计算不会跨模型或错误跨租户复用的稳定内容哈希。"""
        scoped_tenant = "_global_" if self.scope == CacheScope.GLOBAL else tenant_id
        key = f"{scoped_tenant}:{provider}:{model}:{dimension}:{enhanced_text}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def _redis_key(self, content_hash: str) -> str:
        """构造 Redis 完整键名。"""
        return f"{self.prefix}{content_hash}"

    async def get(self, content_hash: str) -> list[float] | None:
        """读取单个缓存向量，Redis 不可用时安全降级为未命中。"""
        try:
            value = await self.redis.get(self._redis_key(content_hash))
            return [float(item) for item in json.loads(value)] if value else None
        except (RedisError, ValueError, TypeError, json.JSONDecodeError) as exc:
            logger.warning("Embedding缓存读取失败: %s", exc.__class__.__name__)
            return None

    async def set(self, content_hash: str, vector: list[float], ttl: int | None = None) -> None:
        """写入单个缓存向量，缓存异常不阻断主链路。"""
        try:
            await self.redis.set(
                self._redis_key(content_hash), json.dumps(vector), ex=ttl or self.ttl
            )
        except RedisError as exc:
            logger.warning("Embedding缓存写入失败: %s", exc.__class__.__name__)

    async def batch_get(self, hashes: list[str]) -> dict[str, list[float] | None]:
        """通过 Redis mget 批量读取向量并保留全部请求键。"""
        if not hashes:
            return {}
        try:
            values = await self.redis.mget([self._redis_key(item) for item in hashes])
            result: dict[str, list[float] | None] = {}
            for content_hash, value in zip(hashes, values, strict=True):
                try:
                    result[content_hash] = [float(item) for item in json.loads(value)] if value else None
                except (ValueError, TypeError, json.JSONDecodeError):
                    result[content_hash] = None
            return result
        except RedisError as exc:
            logger.warning("Embedding缓存批量读取失败: %s", exc.__class__.__name__)
            return {item: None for item in hashes}

    async def batch_set(self, hash_vector_map: dict[str, list[float]]) -> None:
        """使用 pipeline 批量写入向量，缓存异常不阻断向量入库。"""
        if not hash_vector_map:
            return
        try:
            async with self.redis.pipeline(transaction=False) as pipe:
                for content_hash, vector in hash_vector_map.items():
                    pipe.set(self._redis_key(content_hash), json.dumps(vector), ex=self.ttl)
                await pipe.execute()
        except RedisError as exc:
            logger.warning("Embedding缓存批量写入失败: %s", exc.__class__.__name__)
