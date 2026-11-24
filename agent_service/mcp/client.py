"""本文件实现 MCP 客户端管理：连接外部 Streamable HTTP 必应搜索服务器并调用工具。

doc 20 方案：LawRAG 作为 MCP 客户端，仅接入 bing_search 单工具（外部服务器，
必应 Key 由服务器侧持有）。连接为懒连接 + 指数退避重连，调用用 asyncio.Lock 串行化
（底层 HTTP 传输非严格并发安全，本项目并发量低，串行足够）。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from backend.config import settings
from backend.utils.logger import get_logger

logger = get_logger(__name__)


class MCPClientManager:
    """连接管理 + list_tools + call_tool + 结果归一化（Streamable HTTP 传输）。"""

    def __init__(
        self,
        *,
        server_url: str,
        timeout: float | None = None,
        retry: int | None = None,
        allowed_tools: set[str] | None = None,
    ) -> None:
        """注入服务器地址、超时与重连次数；allowed_tools 为空表示不限制。"""
        self.server_url = server_url
        self.timeout = timeout if timeout is not None else settings.mcp_client_timeout
        self.retry = retry if retry is not None else settings.mcp_connect_retry
        self.allowed_tools = allowed_tools if allowed_tools is not None else set(settings.mcp_tool_allowlist)
        self._lock = asyncio.Lock()
        self._session: Any | None = None       # 当前 ClientSession
        self._session_ctx: Any | None = None   # 底层 streamable_http_client async context

    # ===== 连接生命周期 =====

    async def ensure_connected(self) -> bool:
        """懒连接：已连接返回 True；连接失败按 retry 指数退避重试。"""
        if self._session is not None:
            return True
        async with self._lock:
            if self._session is not None:
                return True
            for attempt in range(self.retry + 1):
                try:
                    await self._connect()
                    return True
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[MCP] 连接失败 (attempt=%d): %s", attempt + 1, exc.__class__.__name__)
                    await self._cleanup_partial()
                    if attempt < self.retry:
                        await asyncio.sleep(min(2**attempt, 4))
        return False

    async def _connect(self) -> None:
        """建立 mcp.ClientSession 并完成 initialize。"""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        ctx = streamable_http_client(self.server_url)
        read, write = await ctx.__aenter__()
        session = ClientSession(read, write)
        try:
            await session.__aenter__()
            await session.initialize()
        except Exception:  # noqa: BLE001
            await session.__aexit__(None, None, None)
            await ctx.__aexit__(None, None, None)
            raise
        self._session = session
        self._session_ctx = ctx
        logger.info("[MCP] 已连接 %s", self.server_url)

    async def close(self) -> None:
        """关闭会话与底层传输。"""
        session, ctx = self._session, self._session_ctx
        self._session = None
        self._session_ctx = None
        try:
            if session is not None:
                await session.__aexit__(None, None, None)
            if ctx is not None:
                await ctx.__aexit__(None, None, None)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[MCP] 关闭连接异常: %s", exc.__class__.__name__)

    async def _cleanup_partial(self) -> None:
        """连接中途失败时清理半开状态。"""
        await self.close()

    async def _reset(self) -> None:
        """调用异常时复位连接，下次调用自动重建。"""
        await self.close()

    # ===== 工具操作 =====

    async def list_tools(self) -> list[dict[str, Any]]:
        """返回服务器工具摘要（name/description/input_schema），用于日志与白名单核对。"""
        if not await self.ensure_connected():
            return []
        try:
            async with self._lock:
                result = await asyncio.wait_for(self._session.list_tools(), timeout=self.timeout)
            return [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                }
                for tool in result.tools
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("[MCP] list_tools 失败: %s", exc.__class__.__name__)
            await self._reset()
            return []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """调用 MCP 工具并归一化返回。

        Args:
            name: 工具名（如 bing_search）。
            arguments: 工具参数 dict。

        Returns:
            归一化后的 dict（优先 structuredContent，否则解析 TextContent JSON）。

        Raises:
            ValueError: 工具名不在白名单。
            ConnectionError: 无法建立连接。
            RuntimeError: 工具执行返回错误。
        """
        if self.allowed_tools and name not in self.allowed_tools:
            raise ValueError(f"MCP 工具 {name} 不在白名单 {sorted(self.allowed_tools)}")

        last_exc: Exception | None = None
        for attempt in range(self.retry + 1):
            if not await self.ensure_connected():
                last_exc = ConnectionError("MCP 客户端连接失败")
                break
            try:
                async with self._lock:
                    result = await asyncio.wait_for(
                        self._session.call_tool(name, arguments=arguments),
                        timeout=self.timeout,
                    )
                if getattr(result, "is_error", False):
                    raise RuntimeError(f"MCP 工具 {name} 执行返回错误")
                return self._normalize_result(result)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning("[MCP] call_tool %s 失败 (attempt=%d): %s", name, attempt + 1, exc.__class__.__name__)
                await self._reset()
                if attempt < self.retry:
                    await asyncio.sleep(min(2**attempt, 2))
        assert last_exc is not None
        raise last_exc

    @staticmethod
    def _normalize_result(result: Any) -> dict[str, Any]:
        """把 MCP CallToolResult 归一化为可 JSON 的 dict。

        优先 structuredContent；否则解析 TextContent 的 JSON 文本
        （bing_search 返回 {"query", "results": [...], "totalResults"}）。
        """
        structured = getattr(result, "structuredContent", None)
        if structured:
            return structured if isinstance(structured, dict) else {"results": structured}
        for block in result.content or []:
            text = getattr(block, "text", None)
            if not text:
                continue
            try:
                parsed = json.loads(text)
                return parsed if isinstance(parsed, dict) else {"results": parsed}
            except (json.JSONDecodeError, TypeError):
                continue
        return {"results": []}


# ===== 模块级持有者：backend/main.py lifespan 注入，WebSearchTool 读取 =====

_MCP_MANAGER: MCPClientManager | None = None


def set_mcp_manager(manager: MCPClientManager | None) -> None:
    """注入进程级 MCP 客户端实例（lifespan 启动时调用）。"""
    global _MCP_MANAGER
    _MCP_MANAGER = manager


def get_mcp_manager() -> MCPClientManager | None:
    """返回当前 MCP 客户端实例；未启用或未注入返回 None。"""
    return _MCP_MANAGER
