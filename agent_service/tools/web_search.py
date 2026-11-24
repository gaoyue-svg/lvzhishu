"""本文件实现 Tavily 联网搜索工具，供案例分析 Agent 获取类案线索。"""

from __future__ import annotations

from typing import Any

import httpx
from bs4 import BeautifulSoup

from backend.config import settings
from backend.services import llm_config as llm_config_svc
from backend.utils.logger import get_logger
from backend.utils.tool_context import get_tool_context

from agent_service.mcp import get_mcp_manager

from .base import BaseTool

logger = get_logger(__name__)


def _count_web_fallback(reason: str) -> None:
    """统计 WebSearch 降级次数（Prometheus 埋点，best-effort）。"""
    try:
        from agent_service.metrics.registry import WEB_SEARCH_FALLBACK

        WEB_SEARCH_FALLBACK.labels(reason=reason).inc()
    except Exception:  # noqa: BLE001
        pass


def _html_to_text(html: str) -> str:
    """把 Tavily raw_content（HTML/markdown 混合）清洗为可读纯文本。

    去掉脚本/样式噪音，合并空行；非 HTML 的纯文本原样返回。
    """
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)


def _normalize_search_result(raw: dict[str, Any], max_results: int) -> dict[str, Any]:
    """把 bing_search 返回归一化为 WebSearchTool 契约。

    bing_search 返回 {"query", "results": [{uuid,title,url,snippet,displayUrl}], "totalResults"}，
    这里映射为 citations（web 引用，text=摘要前 300 字）并透传 results。
    """
    results = list(raw.get("results") or [])[:max_results]
    citations = [
        {
            "source_type": "web",
            "title": item.get("title"),
            "url": item.get("url"),
            "text": str(item.get("snippet") or "")[:300],
            "full_text": str(item.get("snippet") or ""),
        }
        for item in results
        if item.get("url") or item.get("title")
    ]
    if not results:
        return {"available": True, "results": [], "citations": [], "message": "未检索到结果"}
    return {"available": True, "results": results, "citations": citations}


class WebSearchTool(BaseTool):
    """联网搜索工具：按 settings.web_search_provider 分发到不同搜索引擎实现。

    当前实现 tavily；必应中文搜索 MCP（provider=bing_mcp）为预留占位，
    未接入时返回 available=False 的降级结果，不阻塞 Agent。
    返回契约 {available, results, citations, message} 保持稳定，替换搜索引擎时 Agent 侧零改动。
    """

    @property
    def name(self) -> str:
        """返回工具唯一名称。"""
        return "web_search"

    @property
    def description(self) -> str:
        """返回工具用途描述。"""
        return "搜索互联网公开资料，返回案例分析可参考的网络来源。"

    @property
    def parameters_schema(self) -> dict[str, Any]:
        """返回搜索参数定义。"""
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["query"],
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        """按配置的 provider 执行搜索；未配置或失败时返回可降级结果。"""
        query = str(kwargs.get("query") or "").strip()
        max_results = int(kwargs.get("max_results") or settings.tavily_max_results)
        if not query:
            return {"available": False, "results": [], "citations": [], "message": "搜索关键词为空"}

        provider = (settings.web_search_provider or "tavily").strip().lower()
        if provider == "bing_mcp":
            return await self._execute_bing_mcp(query, max_results)
        return await self._execute_tavily(query, max_results)

    async def _execute_tavily(self, query: str, max_results: int) -> dict[str, Any]:
        """通过 Tavily Search API 执行搜索。

        仅使用当前请求用户已保存并启用的 Tavily 配置 (config_type='tavily');
        用户未配置时不调用 Tavily, 直接返回 available=False 的降级结果,
        不回退到全局 .env 配置。
        """
        api_key = await _resolve_tavily_api_key()
        if not api_key:
            _count_web_fallback("not_configured")
            return {"available": False, "results": [], "citations": [], "message": "Tavily 未配置"}

        body: dict[str, Any] = {
            "api_key": api_key,
            "query": query,
            "max_results": max(1, min(max_results, 10)),
            "search_depth": settings.tavily_search_depth,
        }
        if settings.tavily_include_raw_content:
            # raw_content 提供网页正文，供前端弹窗展示完整内容；成本约 2-3 倍
            body["include_raw_content"] = True
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    f"{settings.tavily_api_base.rstrip('/')}/search",
                    json=body,
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            _count_web_fallback("error")
            return {
                "available": False,
                "results": [],
                "citations": [],
                "message": f"联网搜索不可用: {exc.__class__.__name__}",
            }

        # results 会进入 LLM 提示词（tool_calls），必须剔除体积巨大的 raw_content；
        # 网页正文单独抽到 full_texts 映射，由 tool_exec_node 抽离到 state，供前端弹窗展示。
        results = list(payload.get("results") or [])
        full_texts: dict[str, str] = {}
        clean_results: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []
        for item in results[:max_results]:
            url = item.get("url")
            content = str(item.get("content") or "")
            raw = str(item.get("raw_content") or "")
            full = _html_to_text(raw) or content
            if url and full:
                full_texts[url] = full[: settings.tavily_full_text_limit]
            clean_results.append({k: v for k, v in item.items() if k != "raw_content"})
            citations.append({
                "source_type": "web",
                "title": item.get("title"),
                "url": url,
                "text": content[:300],
                "score": item.get("score"),
            })
        return {
            "available": True,
            "results": clean_results[:max_results],
            "citations": citations,
            "full_texts": full_texts,
        }

    async def _execute_bing_mcp(self, query: str, max_results: int) -> dict[str, Any]:
        """通过必应中文搜索 MCP 客户端执行搜索（doc 20）。

        MCP 服务器暴露 bing_search(query, count, offset)，返回
        {"query", "results": [{uuid,title,url,snippet,displayUrl}], "totalResults"}；
        归一化为项目契约 {available, results, citations, message}，Agent 侧零改动。
        MCP 未初始化或调用失败时返回 available=False 降级结果，不阻塞 Agent。
        """
        mcp = get_mcp_manager()
        if mcp is None:
            _count_web_fallback("mcp_unavailable")
            return {
                "available": False,
                "results": [],
                "citations": [],
                "message": "必应中文搜索 MCP 未初始化",
            }
        try:
            raw = await mcp.call_tool(
                settings.bing_mcp_tool_name,
                {"query": query, "count": max(1, min(max_results, 10))},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("必应搜索 MCP 调用失败: %s", exc.__class__.__name__)
            _count_web_fallback("error")
            return {
                "available": False,
                "results": [],
                "citations": [],
                "message": f"必应搜索 MCP 不可用: {exc.__class__.__name__}",
            }
        return _normalize_search_result(raw, max_results)


async def _resolve_tavily_api_key() -> str:
    """解析当前请求应使用的 Tavily API Key。

    从请求级 ToolContext 读取当前用户已保存并启用的 Tavily 配置 (config_type='tavily');
    未设置或读取失败时返回空串, 由上层按 "Tavily 未配置" 处理,
    不调用 Tavily, 也不回退到全局 .env 配置。
    """
    ctx = get_tool_context()
    if ctx is None:
        return ""
    try:
        return await llm_config_svc.get_active_tavily_api_key(ctx.db, ctx.user_id)
    except Exception:
        # 配置读取失败不阻塞 Agent, 视为未配置, 由上层返回降级结果。
        return ""

