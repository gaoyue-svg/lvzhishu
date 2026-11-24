"""本文件提供请求级工具执行上下文, 通过 contextvar 把 user_id 与 db 透传给单例工具。

ToolRegistry 在 main.py 中作为单例创建, 无法在请求级别注入 user_id;
WebSearchTool 等需要按当前用户读取 BYOK 配置的工具, 通过 get_tool_context()
从当前请求上下文获取 user_id 与 db, 再回查数据库, 避免修改 ToolRegistry 签名。
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolContext:
    """工具执行上下文, 承载当前请求的 user_id 与 db_session。"""

    user_id: int
    db: Any


tool_context_var: contextvars.ContextVar[ToolContext | None] = contextvars.ContextVar(
    "tool_context", default=None
)


def set_tool_context(ctx: ToolContext) -> contextvars.Token:
    """设置当前请求的工具执行上下文, 返回 token 用于结束时 reset。"""
    return tool_context_var.set(ctx)


def reset_tool_context(token: contextvars.Token) -> None:
    """根据 token 重置当前请求的工具执行上下文。"""
    tool_context_var.reset(token)


def get_tool_context() -> ToolContext | None:
    """获取当前请求的工具执行上下文, 未设置时返回 None。"""
    return tool_context_var.get()
