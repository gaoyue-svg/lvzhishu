"""本文件实现法条定位辅助工具，用于整理检索结果的条款树信息。"""

from __future__ import annotations

from typing import Any

from .base import BaseTool


class ArticleTreeTool(BaseTool):
    """把检索到的法条 Chunk 整理为简易条款树。"""

    @property
    def name(self) -> str:
        """返回工具唯一名称。"""
        return "article_tree"

    @property
    def description(self) -> str:
        """返回工具用途描述。"""
        return "根据 hierarchy_path、law_name、article_no 整理法条层级。"

    @property
    def parameters_schema(self) -> dict[str, Any]:
        """返回工具参数定义。"""
        return {"type": "object", "properties": {"chunks": {"type": "array"}}, "required": ["chunks"]}

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        """从 Chunk metadata 中抽取法律名称、条号和层级路径。"""
        tree = []
        for index, chunk in enumerate(kwargs.get("chunks") or [], start=1):
            metadata = dict(chunk.get("metadata") or {})
            tree.append(
                {
                    "index": index,
                    "law_name": metadata.get("law_name"),
                    "article_no": metadata.get("article_no") or metadata.get("article"),
                    "hierarchy_path": metadata.get("hierarchy_path"),
                    "chunk_level": metadata.get("chunk_level") or chunk.get("chunk_level"),
                }
            )
        return {"tree": tree}

