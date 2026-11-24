"""Input Guard 检查项（doc 21 §4.1）：纯函数 + 少量异步 DB 查询，便于单测。

语义：拦截统一抛 GuardError；内部异常由 dependencies.run_input_guard 按
"非安全类 fail-open / 越权 fail-close" 处理。
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, time as datetime_time
from typing import Any

from sqlalchemy import select

from backend.config import settings
from backend.utils.logger import get_logger
from backend.utils.tokenizer import count_tokens

from .errors import GuardError

logger = get_logger(__name__)

# 提示注入规则（保守，避免误伤正常法律问题）：覆盖"忽略指令/系统提示词泄露/角色欺骗"等。
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"忽略.{0,15}(上述|之前|以上|上面).{0,10}(指令|指示|要求|提示)", re.IGNORECASE),
    re.compile(r"ignore\s+(all\s+)?(previous|above|prior).{0,15}instructions", re.IGNORECASE),
    re.compile(r"系统提示词|system\s*prompt", re.IGNORECASE),
    re.compile(r"请(假装|扮演).{0,8}(你|系统|模型)", re.IGNORECASE),
    re.compile(r"don'?t\s+follow\s+your", re.IGNORECASE),
]


def check_query(query: str) -> None:
    """输入合法性：长度上限 + 非法控制字符。"""
    if len(query) > settings.guard_max_query_chars:
        raise GuardError(400, f"query 超长（上限 {settings.guard_max_query_chars} 字符）", "query")
    if any(ord(ch) < 32 and ch not in "\t\n\r" for ch in query):
        raise GuardError(400, "query 含非法控制字符", "query")


def check_prompt_injection(query: str) -> None:
    """提示注入规则检测：命中即拦截。"""
    if any(pattern.search(query) for pattern in _INJECTION_PATTERNS):
        raise GuardError(400, "检测到提示注入指令，已拦截", "injection")


def check_sensitive(query: str) -> None:
    """敏感词检测：guard_blocked_keywords 逗号分隔，命中即拦截。"""
    blocked = [keyword.strip() for keyword in (settings.guard_blocked_keywords or "").split(",") if keyword.strip()]
    if blocked and any(keyword in query for keyword in blocked):
        raise GuardError(400, "query 命中敏感词，已拦截", "sensitive")


async def check_kb_ownership(db: Any, user_id: int, kb_ids: list[str]) -> None:
    """越权校验：请求的 kb_ids 必须全部属于当前用户（数字 id 按 id 匹配，否则按名称匹配）。"""
    if not kb_ids:
        return
    from backend.models.knowledge import KnowledgeBase

    for item in kb_ids:
        kb_ref = str(item)
        statement = (
            select(KnowledgeBase.id)
            .where(KnowledgeBase.user_id == user_id)
            .where(KnowledgeBase.id == int(kb_ref) if kb_ref.isdigit() else KnowledgeBase.name == kb_ref)
        )
        exists = await db.scalar(statement.limit(1))
        if not exists:
            raise GuardError(403, f"无权访问知识库 {kb_ref}", "kb")


async def check_budget(db: Any, user_id: int, query: str) -> None:
    """预算检查：单请求估算 token 上限 + 单用户当日 llm_usage 配额（0=不限）。"""
    if settings.guard_request_token_cap > 0:
        estimate = count_tokens(query)
        if estimate > settings.guard_request_token_cap:
            raise GuardError(429, f"单请求 token 估算 {estimate} 超过上限 {settings.guard_request_token_cap}", "budget")

    if settings.guard_user_daily_token_quota > 0:
        from backend.models.harness import LlmUsage

        day_start = datetime.combine(datetime.now().date(), datetime_time.min)
        total = await db.scalar(
            select(LlmUsage.total_tokens)
            .where(LlmUsage.user_id == user_id, LlmUsage.created_at >= day_start)
        )
        used = int(total or 0)
        if used >= settings.guard_user_daily_token_quota:
            raise GuardError(429, f"当日 token 配额已用完（{used}）", "budget")


# ===== 并发控制（进程内，单机有效；多 Worker 部署时按实例计数）=====
_active_requests: dict[int, int] = {}
_concurrency_lock = asyncio.Lock()


async def acquire_concurrency(user_id: int) -> None:
    """为单用户占用一个并发槽位；超限抛 429。"""
    limit = settings.guard_max_concurrency
    if limit <= 0:
        return
    async with _concurrency_lock:
        count = _active_requests.get(user_id, 0)
        if count >= limit:
            raise GuardError(429, "并发请求过多，请稍后再试", "concurrency")
        _active_requests[user_id] = count + 1


async def release_concurrency(user_id: int) -> None:
    """释放单用户一个并发槽位（成对调用，安全幂等）。"""
    limit = settings.guard_max_concurrency
    if limit <= 0:
        return
    async with _concurrency_lock:
        count = _active_requests.get(user_id, 0)
        if count <= 1:
            _active_requests.pop(user_id, None)
        else:
            _active_requests[user_id] = count - 1
