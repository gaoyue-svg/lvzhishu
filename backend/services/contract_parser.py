"""本文件实现合同 Markdown 文本的结构化解析，产出可入库的条款列表。

设计要点：
1. 复用 ContractClauseParserTool 的条款边界正则，但增强为三段式（编号+标题+正文）。
2. 保留章节层级（第X章作为父 chunk），条款作为叶子。
3. clause_type 用关键词规则分类（第一阶段，确定性、快）。
4. 实体抽取（payment_days/amount/penalty_rate/term_days）用正则，供规则引擎使用。
5. 输出结构与 knowledge_chunk 对齐，便于 Worker 直接入库。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from backend.utils.tokenizer import count_tokens

# 条款编号正则：第X条 / 第X章 / 一、 / 1. 等
CLAUSE_PATTERN = re.compile(
    r"(?=(?:第[一二三四五六七八九十百千万零〇0-9]+[条章节]|[一二三四五六七八九十]+、|\d+[.、]))"
)
# 章节标题正则（第X章）
CHAPTER_PATTERN = re.compile(r"第[一二三四五六七八九十百千万零〇0-9]+章")
# 条款编号正则（第X条）
ARTICLE_PATTERN = re.compile(r"(第[一二三四五六七八九十百千万零〇0-9]+条)")

# clause_type 关键词映射表，按优先级从上到下匹配
# liability 放在 payment 前面：违约条款常含"支付违约金"，应优先归 liability
CLAUSE_TYPE_KEYWORDS: list[tuple[str, list[str]]] = [
    ("liability", ["违约", "赔偿", "滞纳金", "违约金", "罚金", "承担责任"]),
    ("termination", ["解除", "终止", "单方", "解除合同", "合同终止"]),
    ("payment", ["付款", "支付", "价款", "金额", "结款", "结算", "报酬"]),
    ("delivery", ["交付", "验收", "提交", "移交", "交货"]),
    ("confidentiality", ["保密", "机密", "商业秘密"]),
    ("jurisdiction", ["管辖", "仲裁", "争议解决", "诉讼"]),
    ("term", ["期限", "有效期", "起止", "合同期限", "履行期限"]),
    ("ip", ["知识产权", "专利", "著作权", "商标", "版权"]),
    ("warranty", ["保证", "担保", "承诺", "陈述与保证"]),
    ("force_majeure", ["不可抗力"]),
]


@dataclass(slots=True)
class ContractClause:
    """单条合同条款的结构化表示，映射到 knowledge_chunk。"""

    article_no: str               # 条款编号，如"第五条"
    title: str                    # 条款标题，如"付款方式"
    content: str                  # 条款正文
    clause_type: str              # 条款类型，如 payment
    chunk_level: str = "section"  # section=叶子条款，chapter=章节
    parent_no: str = ""           # 所属章节编号，无章节时为空
    entities: dict[str, Any] = field(default_factory=dict)
    token_count: int = 0
    char_start: int = 0
    char_end: int = 0

    def to_chunk_dict(self, index: int, document_id: int = 0) -> dict[str, Any]:
        """转换为 knowledge_chunk 入库字典，与 parser 的 chunk 结构对齐。

        document_id 用于生成稳定的 parent_chunk_id，便于章节-条款父子关联。
        """
        # 章节作为父级，条款的 parent_chunk_id 指向所属章节的稳定 ID
        parent_chunk_id = ""
        if self.chunk_level == "chapter":
            parent_chunk_id = ""
        elif self.parent_no:
            parent_chunk_id = f"contract:{document_id}:{self.parent_no}"

        return {
            "chunk_index": index,
            "chunk_type": "contract_clause",
            "chunk_level": self.chunk_level,
            "chunk_subtype": "contract_chapter" if self.chunk_level == "chapter" else "contract_clause",
            "text": self.content,
            "token_count": self.token_count or count_tokens(self.content),
            "parent_chunk_id": parent_chunk_id,
            "metadata": {
                "article_no": self.article_no,
                "title": self.title,
                "clause_type": self.clause_type,
                "chunk_level": self.chunk_level,
                "parent_no": self.parent_no,
                "entities": self.entities,
                "chunk_index": index,
            },
        }


@dataclass(slots=True)
class ContractDocument:
    """整份合同的结构化解析结果。"""

    contract_name: str
    parties: list[dict[str, str]] = field(default_factory=list)
    clauses: list[ContractClause] = field(default_factory=list)

    def to_chunks(self, document_id: int = 0) -> list[dict[str, Any]]:
        """把所有条款转换为 knowledge_chunk 入库字典列表。"""
        return [clause.to_chunk_dict(index, document_id) for index, clause in enumerate(self.clauses)]


class ContractParser:
    """把合同 Markdown 解析为 ContractDocument，产出结构化条款列表。"""

    def parse(self, markdown: str, filename: str = "") -> ContractDocument:
        """解析合同 Markdown，返回结构化文档。"""
        clean_text = self._strip_markdown_noise(markdown)
        contract_name = self._extract_contract_name(clean_text, filename)
        parties = self._extract_parties(clean_text)
        clauses = self._split_clauses(clean_text)
        return ContractDocument(
            contract_name=contract_name,
            parties=parties,
            clauses=clauses,
        )

    def _strip_markdown_noise(self, markdown: str) -> str:
        """去掉页码注释和多余标记，保留可读文本。"""
        text = re.sub(r"<!--\s*page:\d+\s*-->", "", markdown)
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        return text.strip()

    def _extract_contract_name(self, text: str, filename: str) -> str:
        """从首行提取合同名称，无法识别时回退到文件名。"""
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if "合同" in line or "协议" in line:
                return line[:200]
            return line[:200]
        return filename or "未命名合同"

    def _extract_parties(self, text: str) -> list[dict[str, str]]:
        """提取甲乙双方信息，兼容'甲方（出租方）：xxx'与'甲方：xxx'两种格式。

        常见合同书写为"甲方（出租方）：公司名"，括号内的角色（出租方/承租方/买方/卖方）
        位于冒号之前，故正则允许括号角色可选出现后再匹配冒号后的主体名称。
        """
        parties: list[dict[str, str]] = []
        for role in ("甲方", "乙方", "丙方"):
            match = re.search(rf"{role}(?:（[^）]*）)?[:：]\s*([^\n，,。；;]+)", text)
            if match:
                parties.append({"role": role, "name": match.group(1).strip()[:200]})
        return parties

    def _split_clauses(self, text: str) -> list[ContractClause]:
        """按条款编号切分合同文本，识别章节层级和条款类型。"""
        if not text.strip():
            return []
        # 按条款边界正则切分
        parts = [part.strip() for part in CLAUSE_PATTERN.split(text) if part and part.strip()]
        if len(parts) <= 1:
            # 没有明确条款编号，按段落切分兜底
            parts = [item.strip() for item in re.split(r"\n{2,}", text) if item.strip()] or [text]

        clauses: list[ContractClause] = []
        current_chapter = ""
        char_offset = 0
        for part in parts[:500]:  # 限制最多 500 条，防止异常输入
            article_no = self._extract_article_no(part)
            # 跳过无编号的抬头/标题段（合同名、甲乙方等），条款必须有编号
            if not article_no:
                char_offset += len(part) + 1
                continue
            title = self._extract_title(part)

            # 章节节点：记录当前章节，不作为叶子条款
            if CHAPTER_PATTERN.search(part) and not ARTICLE_PATTERN.search(part):
                current_chapter = article_no
                clauses.append(ContractClause(
                    article_no=article_no,
                    title=title,
                    content=part[:2000],
                    clause_type="chapter",
                    chunk_level="chapter",
                    parent_no="",
                    token_count=count_tokens(part),
                    char_start=char_offset,
                    char_end=char_offset + len(part),
                ))
                char_offset += len(part) + 1
                continue

            clause_type = self._classify_clause_type(part)
            entities = self._extract_entities(part, clause_type)
            content = part[:2000]
            clauses.append(ContractClause(
                article_no=article_no,
                title=title,
                content=content,
                clause_type=clause_type,
                chunk_level="section",
                parent_no=current_chapter,
                entities=entities,
                token_count=count_tokens(content),
                char_start=char_offset,
                char_end=char_offset + len(content),
            ))
            char_offset += len(part) + 1
        return clauses

    @staticmethod
    def _extract_article_no(text: str) -> str:
        """从条款首行提取编号，如'第五条'。"""
        match = re.match(r"(第[一二三四五六七八九十百千万零〇0-9]+[条章节])", text)
        if match:
            return match.group(1)
        match = re.match(r"([一二三四五六七八九十]+、)", text)
        if match:
            return match.group(1).rstrip("、")
        match = re.match(r"(\d+[.、])", text)
        if match:
            return match.group(1).rstrip(".、")
        return ""

    @staticmethod
    def _extract_title(text: str) -> str:
        """从条款首行提取标题，取编号后的文本或首行。"""
        first_line = text.splitlines()[0].strip() if text.splitlines() else text
        # 去掉编号前缀，取标题部分
        title = re.sub(
            r"^(第[一二三四五六七八九十百千万零〇0-9]+[条章节]|[一二三四五六七八九十]+、|\d+[.、])\s*",
            "",
            first_line,
        ).strip()
        return title[:60] if title else first_line[:60]

    @staticmethod
    def _classify_clause_type(text: str) -> str:
        """用关键词规则识别条款类型，未命中返回 other。"""
        for clause_type, keywords in CLAUSE_TYPE_KEYWORDS:
            if any(keyword in text for keyword in keywords):
                return clause_type
        return "other"

    @staticmethod
    def _extract_entities(text: str, clause_type: str) -> dict[str, Any]:
        """从条款文本抽取关键数值实体，供规则引擎判断风险。"""
        entities: dict[str, Any] = {}

        # 付款天数：N日内付款 / N个工作日
        days_match = re.search(r"(\d+)\s*(?:个)?(?:工作)?日(?:内|后)?(?:付款|支付|结款|结算)", text)
        if days_match:
            entities["payment_days"] = int(days_match.group(1))

        # 金额：N元 / N万元
        amount_match = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*万?元", text)
        if amount_match:
            entities["amount"] = amount_match.group(0)

        # 违约金比例：N% 的违约金
        penalty_match = re.search(r"(\d+(?:\.\d+)?)\s*%.*?(?:违约金|滞纳金|罚金)", text)
        if penalty_match:
            entities["penalty_rate"] = float(penalty_match.group(1))

        # 期限天数：N天/N日/N个月
        term_match = re.search(r"(\d+)\s*(?:个)?(?:天|日|个月|月)", text)
        if term_match:
            entities["term_value"] = int(term_match.group(1))
            entities["term_unit"] = re.search(r"(天|日|个月|月)", text).group(1) if re.search(r"(天|日|个月|月)", text) else ""

        # 风险关键词
        risk_keywords = [kw for kw in ("单方解除", "随时解除", "自动续期", "无限责任", "不可撤销") if kw in text]
        if risk_keywords:
            entities["risk_keywords"] = risk_keywords

        return entities


def parse_contract(markdown: str, filename: str = "") -> ContractDocument:
    """便捷入口：解析合同 Markdown 为结构化文档。"""
    return ContractParser().parse(markdown, filename)
