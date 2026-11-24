"""本文件实现独立合同审查 Worker，消费 Redis Stream 异步执行合同审查任务。

流程：
1. 消费 lawrag:stream:contract_review 任务
2. 加载合同文档与结构化条款 chunks
3. 对每条条款跑规则检测，命中风险写入 contract_risk 表（source=rule）
4. 汇总风险评分写入 task_log.output_result
5. LLM 深度报告由前端调 /api/agent/contract/review SSE 接口生成，可读取已落库规则风险

容错策略与 parser worker 一致：per-message try/finally ACK，坏消息不阻塞队列。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import os
import signal
import socket
from typing import Any

from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import select

from agent_service.tools.contract import ContractRiskRuleTool
from backend.database import AsyncSessionLocal, close_connections, init_redis
from backend.models.contract import ContractRisk
from backend.models.knowledge import KnowledgeChunk, KnowledgeDocument
from backend.models.task import TaskLog
from backend.services.contract_parser import parse_contract
from backend.utils.logger import get_logger
from backend.worker.task_queue import CONTRACT_REVIEW_STREAM, TaskQueue

logger = get_logger(__name__)
GROUP = "contract-review"
TRANSIENT_REDIS_ERRORS = (RedisConnectionError, TimeoutError)


@dataclass(slots=True)
class ClauseInfo:
    """统一的条款信息结构，兼容知识库 chunk 与直接上传解析两种来源。"""

    text: str
    article_no: str
    clause_type: str
    chunk_level: str
    # 知识库模式对应 knowledge_chunk.id；直接上传模式为 None
    chunk_id: int | None


async def main(
    stop_event: asyncio.Event | None = None,
    register_signals: bool = True,
    close_on_exit: bool = True,
) -> None:
    """运行合同审查 Worker，直到收到 SIGINT/SIGTERM 或外部 stop_event。"""
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
    logger.info("合同审查 Worker 以 %s 身份启动", consumer)

    try:
        while not stop_event.is_set():
            try:
                tasks = await queue.reclaim_stale(
                    CONTRACT_REVIEW_STREAM, GROUP, consumer, min_idle_ms=60000
                )
                if not tasks:
                    tasks = await queue.consume(CONTRACT_REVIEW_STREAM, GROUP, consumer, block_ms=5000)
            except TRANSIENT_REDIS_ERRORS:
                logger.warning("合同审查 Worker 读取任务瞬时故障，跳过本轮重试")
                continue
            for msg_id, task in tasks:
                try:
                    await _handle_task(task, queue)
                except asyncio.CancelledError:
                    logger.warning("合同审查 Worker 被取消，消息 %s 未 ACK", msg_id)
                    raise
                except Exception:
                    logger.exception("处理消息 %s 时发生未预期错误", msg_id)
                await queue.ack(CONTRACT_REVIEW_STREAM, GROUP, msg_id)
                if stop_event.is_set():
                    break
    finally:
        if close_on_exit:
            await close_connections()
        logger.info("合同审查 Worker 已停止")


async def _handle_task(task: dict[str, Any], queue: TaskQueue) -> None:
    """执行单个合同审查任务：加载条款 → 规则检测 → 汇总风险评分。

    支持两种来源：
    - source=upload：直接上传模式，从 task_log.input_params.contract_markdown 读取并用 contract_parser 切分
    - 其他：知识库模式，从 knowledge_chunk 读取已入库条款
    """
    task_id = int(task["task_id"])
    document_id = int(task.get("document_id", 0))
    contract_type = task.get("contract_type", "other")
    review_dimensions = task.get("review_dimensions") or ["legality", "fairness", "completeness"]
    user_id = int(task.get("user_id", 0))
    source = task.get("source", "")
    trace = f"task_id={task_id} document_id={document_id} source={source or 'kb'}"
    logger.info("开始合同审查 %s", trace)

    async with AsyncSessionLocal() as db:
        task_log = await db.get(TaskLog, task_id)
        if task_log is None:
            logger.warning("任务日志不存在: %s", trace)
            return

        # 按来源加载条款，统一构造 ClauseInfo 列表
        if source == "upload":
            clauses, contract_name, parties = await _load_clauses_from_upload(task_log)
        else:
            clauses, contract_name, parties = await _load_clauses_from_kb(db, document_id, task_log)

        if clauses is None:
            # 加载失败，提交失败状态（错误信息已由加载函数写入 task_log）
            await db.commit()
            return

        task_log.status = "analyzing"
        task_log.started_at = datetime.now()
        await db.commit()

        try:
            # 规则检测，命中风险写入 contract_risk
            rule_risks = await _run_rule_detection(db, clauses, task_id, document_id)
            await db.commit()
            logger.info("规则检测完成 %s rule_risks=%s", trace, len(rule_risks))

            # 汇总风险评分写入 task_log
            high_count = sum(1 for r in rule_risks if r.risk_level == "high")
            medium_count = sum(1 for r in rule_risks if r.risk_level == "medium")
            low_count = sum(1 for r in rule_risks if r.risk_level == "low")
            risk_score = max(0, 100 - high_count * 20 - medium_count * 10 - low_count * 5)
            task_log.status = "done"
            # 重试成功后清空历史失败信息，避免前端展示过期错误
            task_log.error_message = None
            task_log.output_result = {
                "risk_score": risk_score,
                "risk_count": len(rule_risks),
                "high_count": high_count,
                "medium_count": medium_count,
                "low_count": low_count,
                "contract_type": contract_type,
                "review_dimensions": review_dimensions,
                "contract_name": contract_name,
                "parties": parties,
                "note": "规则检测完成，可调 /api/agent/contract/review 生成 LLM 深度报告",
            }
            task_log.finished_at = datetime.now()
            await db.commit()
            logger.info("合同审查完成 %s score=%s risks=%s", trace, risk_score, len(rule_risks))

        except Exception as exc:
            await db.rollback()
            async with AsyncSessionLocal() as error_db:
                failed_log = await error_db.get(TaskLog, task_id)
                if failed_log:
                    await _fail_task(error_db, failed_log, str(exc)[:2000])
            logger.exception("合同审查失败 %s", trace)


async def _load_clauses_from_upload(
    task_log: TaskLog,
) -> tuple[list[ClauseInfo] | None, str, list[dict[str, str]]]:
    """直接上传模式：从 task_log.input_params 读合同 markdown，用 contract_parser 切分条款。"""
    params = task_log.input_params or {}
    markdown = params.get("contract_markdown", "")
    filename = params.get("filename", "")
    if not markdown.strip():
        await _fail_task_by_log(task_log, "合同原文为空")
        return None, "", []

    try:
        contract_doc = parse_contract(markdown, filename)
    except Exception as exc:  # noqa: BLE001
        await _fail_task_by_log(task_log, f"合同解析失败: {exc.__class__.__name__}")
        return None, "", []

    clauses = [
        ClauseInfo(
            text=c.content,
            article_no=c.article_no,
            clause_type=c.clause_type,
            chunk_level=c.chunk_level,
            chunk_id=None,
        )
        for c in contract_doc.clauses
    ]
    if not clauses:
        await _fail_task_by_log(task_log, "合同未解析出条款，请检查文件内容")
        return None, "", []

    return clauses, contract_doc.contract_name, contract_doc.parties


async def _load_clauses_from_kb(
    db, document_id: int, task_log: TaskLog
) -> tuple[list[ClauseInfo] | None, str, list[dict[str, str]]]:
    """知识库模式：从 knowledge_chunk 读取已入库的合同条款。"""
    doc = await db.get(KnowledgeDocument, document_id)
    if doc is None:
        await _fail_task_by_log(task_log, "合同文档不存在")
        return None, "", []

    result = await db.execute(
        select(KnowledgeChunk)
        .where(KnowledgeChunk.document_id == document_id)
        .order_by(KnowledgeChunk.chunk_index)
    )
    chunks = list(result.scalars().all())
    if not chunks:
        await _fail_task_by_log(task_log, "合同未解析出条款，请先完成文档解析")
        return None, "", []

    clauses = [
        ClauseInfo(
            text=chunk.text or "",
            article_no=(chunk.metadata_ or {}).get("article_no", ""),
            clause_type=(chunk.metadata_ or {}).get("clause_type", "other"),
            chunk_level=chunk.chunk_level or "section",
            chunk_id=chunk.id,
        )
        for chunk in chunks
    ]
    return clauses, doc.filename or "", []


async def _fail_task_by_log(task_log: TaskLog, message: str) -> None:
    """仅更新内存中的 task_log 字段，由调用方决定何时 commit。"""
    task_log.status = "failed"
    task_log.error_message = message[:2000]
    task_log.finished_at = datetime.now()


async def _run_rule_detection(
    db, clauses: list[ClauseInfo], task_id: int, document_id: int
) -> list[ContractRisk]:
    """对每条条款跑规则引擎，命中风险写入 contract_risk 表。"""
    tool = ContractRiskRuleTool()
    risks: list[ContractRisk] = []
    for clause in clauses:
        if clause.chunk_level == "chapter":
            continue
        try:
            result = await tool.execute(text=clause.text, dimensions=[])
        except Exception:  # noqa: BLE001
            logger.warning("条款规则检测失败 chunk_id=%s", clause.chunk_id)
            continue
        for risk_item in result.get("risks", []):
            risk = ContractRisk(
                task_id=task_id,
                document_id=document_id,
                clause_id=clause.chunk_id,
                article_no=clause.article_no,
                risk_level=risk_item.get("level", "low"),
                risk_type=risk_item.get("code", clause.clause_type),
                title=risk_item.get("message", "")[:200],
                description=risk_item.get("message", ""),
                excerpt=risk_item.get("excerpt", ""),
                suggestion="",
                law_references=[],
                source="rule",
            )
            db.add(risk)
            risks.append(risk)
    return risks


async def _fail_task(db, task_log: TaskLog, message: str) -> None:
    """标记任务失败并记录错误信息。"""
    task_log.status = "failed"
    task_log.error_message = message[:2000]
    task_log.finished_at = datetime.now()
    await db.commit()


if __name__ == "__main__":
    asyncio.run(main())
