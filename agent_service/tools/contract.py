"""本文件实现合同审查相关的文本抽取、条款切分和规则风险工具。"""

from __future__ import annotations

import re
from typing import Any

from .base import BaseTool


class OcrExtractTool(BaseTool):
    """OCR 抽取预留工具；当前优先依赖入库解析文本，不静默返回空内容。"""

    @property
    def name(self) -> str:
        """返回工具唯一名称。"""
        return "ocr_extract"

    @property
    def description(self) -> str:
        """返回工具用途描述。"""
        return "从扫描合同中抽取文本；当前未配置 OCR 时明确返回不可用。"

    @property
    def parameters_schema(self) -> dict[str, Any]:
        """返回 OCR 参数定义。"""
        return {"type": "object", "properties": {"file_path": {"type": "string"}}}

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        """返回 OCR 未启用提示，避免合同审查拿空文本继续生成。"""
        _ = kwargs
        return {"available": False, "text": "", "message": "OCR 未启用，请先完成文档解析或上传可复制文本"}


class ContractClauseParserTool(BaseTool):
    """把合同正文切分为可定位的条款块。"""

    @property
    def name(self) -> str:
        """返回工具唯一名称。"""
        return "contract_clause_parser"

    @property
    def description(self) -> str:
        """返回工具用途描述。"""
        return "按条、款、章节标题切分合同文本。"

    @property
    def parameters_schema(self) -> dict[str, Any]:
        """返回条款切分参数定义。"""
        return {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        """用稳定规则切分合同条款，保留条款编号和原文片段。"""
        text = str(kwargs.get("text") or "").strip()
        if not text:
            return {"clauses": []}
        pattern = re.compile(r"(?=(?:第[一二三四五六七八九十百千万\d]+[条章节]|[一二三四五六七八九十]+、|\d+[.、]))")
        parts = [part.strip() for part in pattern.split(text) if part and part.strip()]
        if len(parts) <= 1:
            paragraphs = [item.strip() for item in re.split(r"\n{2,}", text) if item.strip()]
            parts = paragraphs or [text]
        clauses = [
            {"index": index, "title": self._title(part, index), "text": part[:2000]}
            for index, part in enumerate(parts[:200], start=1)
        ]
        return {"clauses": clauses, "count": len(clauses)}

    @staticmethod
    def _title(text: str, index: int) -> str:
        """从条款首行提取标题，缺失时生成稳定标题。"""
        first_line = text.splitlines()[0].strip()
        return first_line[:60] if first_line else f"条款{index}"


class ContractRiskRuleTool(BaseTool):
    """用轻量规则识别常见合同风险，作为 LLM 审查前的确定性提示。"""

    @property
    def name(self) -> str:
        """返回工具唯一名称。"""
        return "contract_risk_rules"

    @property
    def description(self) -> str:
        """返回工具用途描述。"""
        return "识别单方解除、空白条款、违约责任、管辖约定等常见风险。"

    @property
    def parameters_schema(self) -> dict[str, Any]:
        """返回规则审查参数定义。"""
        return {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "dimensions": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["text"],
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        """执行确定性规则扫描，输出风险清单供报告引用。"""
        text = str(kwargs.get("text") or "")
        risks: list[dict[str, Any]] = []
        checks = [
            ("blank_field", r"_{3,}|【\s*】|（\s*）", "存在空白或待填写字段，签署前需补齐。", "medium"),
            ("unilateral_termination", r"单方解除|随时解除|无需.*通知", "可能存在单方解除权约定，需要核对是否对等。", "medium"),
            ("liquidated_damages", r"违约金|滞纳金|赔偿金", "涉及违约金或赔偿责任，应核对计算方式和上限。", "medium"),
            ("jurisdiction", r"管辖|仲裁|争议解决", "争议解决条款会影响维权成本，应确认地点和机构。", "low"),
            ("auto_renewal", r"自动续期|期满.*续", "自动续期条款可能产生持续义务，应设置提醒或退出机制。", "low"),
        ]
        for code, pattern, message, level in checks:
            match = re.search(pattern, text)
            if match:
                start = max(match.start() - 60, 0)
                end = min(match.end() + 120, len(text))
                risks.append(
                    {
                        "code": code,
                        "level": level,
                        "message": message,
                        "excerpt": text[start:end],
                    }
                )
        return {"risks": risks, "risk_count": len(risks)}

