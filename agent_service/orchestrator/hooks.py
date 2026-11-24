"""边界级 Hook 总线（doc 21 §4.4）：在编排层各边界提供统一 hook 注册与触发点。

设计约束：
- 进程内单例（get_hook_bus），对齐 get_registry() 惯例；
- handler 顺序执行，同事件可注册多个；
- handler 异常只 warning，绝不阻断主流程；
- handler 之间不传递数据（ctx 只读）。
"""

from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
from typing import Any, Awaitable, Callable

from backend.utils.logger import get_logger

logger = get_logger(__name__)

# 事件名常量（Phase 1 边界级事件）
BEFORE_PIPELINE = "before_pipeline"
AFTER_PIPELINE = "after_pipeline"
BEFORE_PLAN = "before_plan"
AFTER_PLAN = "after_plan"
BEFORE_STEP = "before_step"
AFTER_STEP = "after_step"
BEFORE_REVIEW = "before_review"
AFTER_REVIEW = "after_review"
BEFORE_SYNTHESIZE = "before_synthesize"
AFTER_SYNTHESIZE = "after_synthesize"

# 同步或异步 handler 均可
Handler = Callable[[str, dict[str, Any]], None | Awaitable[None]]


class HookBus:
    """事件注册与触发的进程内总线。"""

    def __init__(self) -> None:
        """初始化事件处理器表。"""
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def register(self, event: str, handler: Handler) -> None:
        """为事件注册一个处理器（可重复注册，按注册顺序触发）。"""
        if handler not in self._handlers[event]:
            self._handlers[event].append(handler)

    def unregister(self, event: str, handler: Handler) -> None:
        """移除指定事件的处理器。"""
        if handler in self._handlers[event]:
            self._handlers[event].remove(handler)

    def count(self, event: str) -> int:
        """返回某事件已注册的处理器数量（便于测试与排查）。"""
        return len(self._handlers.get(event, []))

    async def emit(self, event: str, ctx: dict[str, Any] | None = None) -> None:
        """触发事件：顺序执行所有 handler；任一异常只 warning，不抛出。"""
        handlers = list(self._handlers.get(event, []))
        if not handlers:
            return
        payload: dict[str, Any] = ctx or {}
        for handler in handlers:
            try:
                result = handler(event, payload)
                if result is not None:
                    await result
            except Exception:  # noqa: BLE001
                logger.warning("Hook 处理器异常 event=%s handler=%s", event, getattr(handler, "__name__", handler), exc_info=True)


@lru_cache
def get_hook_bus() -> HookBus:
    """返回进程级 HookBus 单例。"""
    return HookBus()
