"""本文件封装文档解析与向量化任务使用的 Redis Stream 队列。"""

import json
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import ResponseError

DOCUMENT_PARSE_STREAM = "lawrag:stream:document_parse"
CHUNK_EMBEDDING_STREAM = "lawrag:stream:chunk_embedding"
CONTRACT_REVIEW_STREAM = "lawrag:stream:contract_review"
EVALUATION_STREAM = "lawrag:stream:evaluation"


class TaskQueue:
    """基于 Redis Stream 消费组的轻量级任务队列。"""

    def __init__(self, redis: Redis):
        """基于 Redis 连接创建队列包装器。"""
        self.redis = redis

    """Stream 的常用命令概览
    作为开发者，操作 Stream 的指令通常以 X 开头：
    XADD：向 Stream 中追加一条消息。
    XREAD：独立消费（不使用消费者组），以阻塞或非阻塞方式读取消息。
    XGROUP：创建、销毁或管理消费者组。
    XREADGROUP：通过消费者组读取消息（最常用的生产级别消费方式）。
    XACK：向消费者组确认消息已成功处理。
    XPENDING：查询消费者组中已读取但尚未 ACK 的消息（用于处理死信或超时重试）。"""

    async def enqueue(self, stream: str, task: dict[str, Any]) -> str:
        """将任务入队并返回其 Redis 消息 id。"""
        return await self.redis.xadd(stream, {"payload": json.dumps(task, ensure_ascii=False)})

    #核心方法
    async def consume(
            self, stream: str, group: str, consumer: str, block_ms: int = 5000
    ) -> list[tuple[str, dict[str, Any]]]:
        """
        从消费组消费最多五条任务。

        该方法采用“先处理待确认消息，再拉取新消息”的策略，确保消费者重启后能优先处理未确认的任务，
        避免消息长时间处于 pending 状态。每条消息的 payload 会被安全地反序列化为字典。

        Args:
            stream: Redis Stream 的键名
            group: 消费组名称
            consumer: 当前消费者标识（通常为实例 ID）
            block_ms: 当没有新消息时，阻塞等待的最大毫秒数（默认 5000ms）

        Returns:
            一个列表，每个元素为 (消息ID, 任务字典) 的元组。
            若 payload 解析失败，则任务字典为 {"_invalid_payload": True}。
        """
        # 确保消费组存在，若 Stream 不存在则自动创建
        await self._ensure_group(stream, group)

        # 第一步：尝试读取当前消费者已收到但尚未确认（pending）的消息。
        # 使用起始 ID "0" 表示从 pending 列表的头部开始，只读取 1 条（但内部 _read 固定取 5 条）。
        # block=1 表示几乎不阻塞，快速返回结果。
        messages = await self._read(stream, group, consumer, "0", 1)

        # 注意：xreadgroup 在无 pending 时返回 [['stream', []]]（外层非空但内层消息列表为空），
        # 不能直接用 `if not messages` 判断，否则会跳过第二步读新消息，导致 Worker 永远读不到新任务。
        # 这里检查内层实际消息数，只有当所有 stream 的消息列表都为空时才进入第二步。
        if not messages or not any(msgs for _, msgs in messages):
            # 如果没有 pending 消息，则第二步：读取新消息（ID 为 ">" 表示只消费从未投递过的消息）。
            # 此时使用传入的 block_ms 阻塞等待新消息到来。
            messages = await self._read(stream, group, consumer, ">", block_ms)

        # 遍历返回的消息（格式为 [(stream_name, [(msg_id, fields), ...]), ...]）
        items: list[tuple[str, dict[str, Any]]] = []
        for _, stream_messages in messages:  # _ 为 stream 名称，通常不关注
            for msg_id, fields in stream_messages:  # fields 是 dict，包含 payload 字段
                payload = fields.get("payload", "{}")  # 获取消息体，默认为空 JSON 对象
                items.append((msg_id, self._decode_payload(payload)))  # 安全反序列化并加入结果列表

        return items

    async def ack(self, stream: str, group: str, msg_id: str) -> None:
        """确认已完成处理的任务。"""
        await self.redis.xack(stream, group, msg_id)

    async def reclaim_stale(
        self, stream: str, group: str, consumer: str, min_idle_ms: int = 60000
    ) -> list[tuple[str, dict[str, Any]]]:
        """认领崩溃消费者遗留的空闲 pending 消息。"""
        await self._ensure_group(stream, group)
        try:
            result = await self.redis.xautoclaim(
                stream,
                group,
                consumer,
                min_idle_time=min_idle_ms,
                start_id="0",
                count=5,
            )
        except ResponseError:
            return []

        items: list[tuple[str, dict[str, Any]]] = []
        messages = result[1] if isinstance(result, tuple) and len(result) >= 2 else []
        for msg_id, fields in messages:
            payload = fields.get("payload", "{}")
            items.append((msg_id, self._decode_payload(payload)))
        return items

    async def _ensure_group(self, stream: str, group: str) -> None:
        """确保消费组存在，组已存在时静默忽略。"""
        try:
            await self.redis.xgroup_create(stream, group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def _read(
        self, stream: str, group: str, consumer: str, message_id: str, block_ms: int
    ) -> list[Any]:
        """从消费组读取消息，支持阻塞等待。"""
        return await self.redis.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={stream: message_id},
            count=5,
            block=block_ms,
        )

    @staticmethod
    def _decode_payload(payload: str) -> dict[str, Any]:
        """将坏消息转换为可由 Worker 单条失败处理的标记对象，避免消费循环崩溃。"""
        try:
            value = json.loads(payload)
            return value if isinstance(value, dict) else {"_invalid_payload": True}
        except (json.JSONDecodeError, TypeError):
            return {"_invalid_payload": True}
