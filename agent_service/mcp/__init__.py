"""本子包实现 MCP 客户端（doc 20 必应中文搜索 MCP 接入）。

LawRAG 作为 MCP 客户端连接外部 Streamable HTTP 必应搜索服务器，
仅接入 bing_search 单工具；必应 Key 由 MCP 服务器侧持有。
"""

from .client import MCPClientManager, get_mcp_manager, set_mcp_manager

__all__ = ["MCPClientManager", "get_mcp_manager", "set_mcp_manager"]
