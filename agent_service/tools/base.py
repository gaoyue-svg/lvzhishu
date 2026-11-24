"""本文件定义 Agent 内部 Python 工具的统一抽象接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseTool(ABC):
    """工具抽象基类，预留与 MCP Tool Schema 对齐的描述字段。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """返回工具唯一名称。"""

    @property
    @abstractmethod
    def description(self) -> str:
        """返回工具用途描述。"""

    @property
    @abstractmethod
    def parameters_schema(self) -> dict[str, Any]:
        """返回 JSON Schema 风格参数定义。"""

    @abstractmethod
    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        """执行工具并返回可 JSON 序列化结果。"""

