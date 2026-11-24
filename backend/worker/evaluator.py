"""本文件实现独立离线评估 Worker，消费 Redis Stream 对抽样 run 做 LLM-as-Judge 打分。

流程：
1. 消费 lawrag:stream:evaluation 任务 {trace_id, user_id}
2. 读 agent_run_trace 该 run 的 final_answer / final_citations
3. 按用户 BYOK 配置构建 LLM（不回退全局 key，控制离线成本）
4. judge_offline 打 grounded_score / hallucination，写 evaluation_result(mode='offline')

容错策略与 parser worker 一致：per-message try/finally ACK，坏消息不阻塞队列；
BYOK 缺失或评审失败仅跳过，不影响任何在线链路。
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket
from typing import Any

from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import select

from agent_service.evaluator.judge import judge_offline
from agent_service.evaluator.recorder import record_offline
from agent_service.llm.registry import get_or_create
from backend.database import AsyncSessionLocal, close_connections, init_redis
from backend.models.harness import AgentRunTrace
from backend.services.llm_config import get_active_config
from backend.utils.logger import get_logger
from backend.worker.task_queue import EVALUATION_STREAM, TaskQueue

logger = get_logger(__name__)
GROUP = "evaluator"
TRANSIENT_REDIS_ERRORS = (RedisConnectionError, TimeoutError)


async def main(
    stop_event: asyncio.Event | None = None,
    register_signals: bool = True,
    close_on_exit: bool = True,
) -> None:
    """运行离线评估 Worker，直到收到 SIGINT/SIGTERM 或外部 stop_event。"""
    if stop_event is None:
        stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    if register_signals:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:
                signal.signal(sig, lambda *_: stop_event.set())

    redis = await init_redis()
    if redis is None:
        raise RuntimeError("Redis 未初始化")
    queue = TaskQueue(redis)
    consumer = f"{socket.gethostname()}-{os.getpid()}"
    logger.info("离线评估 Worker 以 %s 身份启动", consumer)

    try:
        while not stop_event.is_set():
            try:
                tasks = await queue.reclaim_stale(
                    EVALUATION_STREAM, GROUP, consumer, min_idle_ms=60000
                )
                if not tasks:
                    tasks = await queue.consume(EVALUATION_STREAM, GROUP, consumer, block_ms=5000)
            except TRANSIENT_REDIS_ERRORS:
                logger.warning("离线评估 Worker 读取任务瞬时故障，跳过本轮重试")
                continue
            for msg_id, task in tasks:
                try:
                    await _handle_task(task)
                except asyncio.CancelledError:
                    logger.warning("离线评估 Worker 被取消，消息 %s 未 ACK", msg_id)
                    raise
                except Exception:
                    logger.exception("处理消息 %s 时发生未预期错误", msg_id)
                await queue.ack(EVALUATION_STREAM, GROUP, msg_id)
                if stop_event.is_set():
                    break
    finally:
        if close_on_exit:
            await close_connections()
        logger.info("离线评估 Worker 已停止")


async def _handle_task(task: dict[str, Any]) -> None:
    """执行单个离线评审任务。"""
    trace_id = str(task.get("trace_id") or "")
    user_id = int(task.get("user_id") or 0)
    if not trace_id:
        return
    logger.info("开始离线评审 trace_id=%s", trace_id)

    async with AsyncSessionLocal() as db:
        trace = await db.scalar(select(AgentRunTrace).where(AgentRunTrace.trace_id == trace_id))
        if trace is None:
            logger.warning("离线评审：run 不存在 trace_id=%s", trace_id)
            return

        # BYOK：仅用用户已保存配置，未配置则跳过（不回退全局 key）
        if user_id <= 0:
            logger.warning("离线评审：无 user_id，跳过 trace_id=%s", trace_id)
            return
        config = await get_active_config(db, user_id)
        if config is None:
            logger.warning("离线评审：用户未配置 LLM，跳过 user_id=%s", user_id)
            return
        llm = await get_or_create(config)

        scores = await judge_offline(trace.final_answer or "", list(trace.final_citations or []), llm)
        await record_offline(trace_id, user_id, scores)
        logger.info("离线评审完成 trace_id=%s grounded=%s", trace_id, scores.get("grounded_score"))


if __name__ == "__main__":
    asyncio.run(main())
