"""本文件实现 Agent 内部工具注册表，避免在 Agent 中硬编码工具分支。"""

from __future__ import annotations

from typing import Any

from .article import ArticleTreeTool
from .base import BaseTool
from .contract import ContractClauseParserTool, ContractRiskRuleTool, OcrExtractTool
from .web_search import WebSearchTool


class ToolRegistry:
    """内部工具注册表，新增工具只需 register。"""

    def __init__(self, tools: list[BaseTool] | None = None) -> None:
        """初始化并注册默认工具。"""
        self._tools: dict[str, BaseTool] = {}
        for tool in tools or self.default_tools():
            self.register(tool)

    def register(self, tool: BaseTool) -> None:
        """注册一个工具实例。"""
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        """按名称获取工具，不存在时给出可读错误。"""
        tool = self._tools.get(name)
        if tool is None:
            raise ValueError(f"未知工具: {name}")
        return tool

    async def execute(self, name: str, **kwargs: Any) -> dict[str, Any]:
        """执行指定工具并返回标准字典。"""
        return await self.get(name).execute(**kwargs)

    def schemas(self) -> list[dict[str, Any]]:
        """导出 OpenAI/MCP 风格工具 Schema，便于后续 function calling。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters_schema,
                },
            }
            for tool in self._tools.values()
        ]

    @staticmethod
    def default_tools() -> list[BaseTool]:
        """返回阶段四内置的五个工具。"""
        return [
            WebSearchTool(),
            ArticleTreeTool(),
            OcrExtractTool(),
            ContractClauseParserTool(),
            ContractRiskRuleTool(),
        ]

