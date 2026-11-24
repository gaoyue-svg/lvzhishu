"""Input Guard 编排入口（doc 21 §4.1）：串起各检查项，对外暴露 run_input_guard。

语义：
- 非安全类（长度/注入/敏感词/预算）内部异常 → fail-open（仅 warning 放行）；
- 越权（安全类）内部异常 → fail-close（宁可拒绝）；
- 并发槽位作为最后一步占用，由调用方在请求 finally 里 release_concurrency 释放。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from backend.config import settings
from backend.utils.logger import get_logger

from .checks import (
    acquire_concurrency,
    check_budget,
    check_kb_ownership,
    check_prompt_injection,
    check_query,
    check_sensitive,
    release_concurrency,
)
from .errors import GuardError

logger = get_logger(__name__)


def _block(check: str) -> None:
    """记录拦截指标（best-effort）。"""
    try:
        from agent_service.metrics.registry import GUARD_BLOCKED

        GUARD_BLOCKED.labels(check=check).inc()
    except Exception:  # noqa: BLE001
        pass


async def run_input_guard(
    *,
    query: str,
    kb_ids: list[str],
    user_id: int,
    db: Any,
    with_concurrency: bool = True,
) -> None:
    """执行 Input Guard 检查；未通过抛 HTTPException，不通过时由调用方终止请求。"""
    if not settings.guard_enabled:
        return

    # 1) 非安全类检查：fail-open（检查自身异常只放行）
    checks: list[tuple[Any, str]] = [(check_query, "query")]
    if settings.guard_prompt_injection_enabled:
        checks.append((check_prompt_injection, "injection"))
    checks.append((check_sensitive, "sensitive"))
    for check_fn, check_name in checks:
        try:
            check_fn(query)
        except GuardError as exc:
            _block(exc.check)
            raise HTTPException(status_code=exc.status_code, detail=exc.message)
        except Exception:  # noqa: BLE001
            logger.warning("[Guard] 检查 %s 异常，fail-open 放行", check_name, exc_info=True)

    # 2) 越权检查：安全类，fail-close（内部异常也拒绝）
    try:
        await check_kb_ownership(db, user_id, kb_ids)
    except GuardError as exc:
        _block(exc.check)
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    except Exception:  # noqa: BLE001
        _block("kb")
        logger.warning("[Guard] 知识库归属校验异常，fail-close 拒绝", exc_info=True)
        raise HTTPException(status_code=403, detail="知识库归属校验不可用，已拒绝")

    # 3) 预算检查：fail-open
    try:
        await check_budget(db, user_id, query)
    except GuardError as exc:
        _block(exc.check)
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    except Exception:  # noqa: BLE001
        logger.warning("[Guard] 预算检查异常，fail-open 放行", exc_info=True)

    # 4) 并发槽位：最后占用，调用方 finally 释放
    if with_concurrency:
        try:
            await acquire_concurrency(user_id)
        except GuardError as exc:
            _block(exc.check)
            raise HTTPException(status_code=exc.status_code, detail=exc.message)
