"""本文件实现 Markdown 法律文本到 LawTree 与法条 Chunk 的专用解析链路。"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Literal

from backend.utils.tokenizer import count_tokens

LAW_NUMERAL = r"[一二三四五六七八九十百千万零〇0-9]+"
HierarchyLevel = Literal["book", "chapter", "section"]


@dataclass(slots=True)
class LawNode:
    """表示法律树中的编、章、节节点。"""

    level: HierarchyLevel | Literal["root"]
    number: str
    title: str
    char_start: int = 0
    char_end: int = 0
    parent: LawNode | None = field(default=None, repr=False)
    children: list[LawNode] = field(default_factory=list)
    article_refs: list[LawArticle] = field(default_factory=list)

    def add_child(self, node: LawNode) -> None:
        """把子层级节点挂到当前节点下。"""
        node.parent = self
        self.children.append(node)


@dataclass(slots=True)
class LawArticle:
    """表示一条已经绑定层级上下文的法律条文。"""

    article_no: str
    text: str
    hierarchy: dict[str, str]
    char_start: int
    char_end: int


@dataclass(slots=True)
class LawBlock:
    """保存原文顺序中的 preamble 或 article 文本块。"""

    block_type: Literal["preamble", "article"]
    text: str
    char_start: int
    char_end: int
    article: LawArticle | None = None


@dataclass(slots=True)
class LawTree:
    """保存法律文档的树结构、条文列表和原文顺序块。"""

    title: str
    plain_text: str
    root: LawNode = field(default_factory=lambda: LawNode("root", "", ""))
    articles: list[LawArticle] = field(default_factory=list)
    blocks: list[LawBlock] = field(default_factory=list)

    def iter_nodes(self, level: HierarchyLevel | None = None) -> list[LawNode]:
        """按树上出现顺序返回指定层级的节点。"""
        nodes: list[LawNode] = []

        def walk(node: LawNode) -> None:
            if node.level != "root" and (level is None or node.level == level):
                nodes.append(node)
            for child in node.children:
                walk(child)

        walk(self.root)
        return nodes


def markdown_to_law_text(markdown: str) -> str:
    """将 Markdown 转为正则解析更稳定的纯法律文本。"""
    text = re.sub(r"<!--\s*page:\s*\d+\s*-->", "\n", markdown, flags=re.IGNORECASE)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    plain_lines: list[str] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        value = lines[index].strip()
        if value.startswith("|") and value.endswith("|"):
            table_rows: list[str] = []
            while index < len(lines):
                candidate = lines[index].strip()
                if not (candidate.startswith("|") and candidate.endswith("|")):
                    break
                if not _is_markdown_table_separator(candidate):
                    cells = [
                        cell.strip().replace("\\|", "|")
                        for cell in candidate.strip("|").split("|")
                    ]
                    table_rows.append("\t".join(cell for cell in cells if cell))
                index += 1
            if table_rows:
                plain_lines.append("表格：")
                plain_lines.extend(table_rows)
            continue
        value = re.sub(r"^#{1,6}\s*", "", value)
        value = re.sub(r"^>\s*", "", value)
        value = re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", value)
        value = value.replace("**", "").replace("__", "").replace("`", "")
        plain_lines.append(value)
        index += 1
    return "\n".join(plain_lines)


def clean_law_text(text: str) -> str:
    """清洗法律纯文本并保留段落空行。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    filtered = [
        line
        for line in lines
        if not re.fullmatch(r"(?:第?\s*\d+\s*页|[-—－]?\s*\d{1,4}\s*[-—－]?)", line)
    ]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(filtered)).strip()


class LawParser:
    """解析 Markdown 法律文本，输出带层级关系的 LawTree。"""

    _marker_pattern = re.compile(
        rf"(?m)^\s*(?P<hierarchy>第{LAW_NUMERAL}(?:编|章|节))[ \t]*(?P<title>[^\n]*)$"
        # 条文编号必须位于行首。正文中的“依照第一百八十八条规定”等引用不能被
        # 当作新条文，否则同一法条会产生多个残缺 Chunk。
        # 排除“第三十八条的规定”“第四十条第一款”等条号引用；这些引用即使
        # 恰好换行到行首，也不能成为新的 Article Chunk。
        rf"|^\s*(?P<article>第{LAW_NUMERAL}条)(?!的|第|规定|至|、|和|及)"
    )

    def parse(self, markdown: str) -> LawTree:
        """执行 Markdown -> 纯文本 -> LawTree 的法律解析流程。"""
        plain_text = clean_law_text(markdown_to_law_text(markdown))
        tree = LawTree(title=_first_non_empty_line(plain_text) or "", plain_text=plain_text)
        current: dict[HierarchyLevel, LawNode | None] = {
            "book": None,
            "chapter": None,
            "section": None,
        }
        matches = list(self._marker_pattern.finditer(plain_text))
        last_consumed = 0
        for index, match in enumerate(matches):
            if match.group("hierarchy"):
                self._append_preamble(tree, plain_text[last_consumed : match.start()], last_consumed)
                self._attach_heading(tree, current, match)
                last_consumed = match.end()
                continue

            article_end = matches[index + 1].start() if index + 1 < len(matches) else len(plain_text)
            self._append_preamble(tree, plain_text[last_consumed : match.start()], last_consumed)
            article_text = plain_text[match.start() : article_end].strip()
            if article_text:
                article = LawArticle(
                    article_no=str(match.group("article")),
                    text=article_text,
                    hierarchy=self._current_hierarchy(current),
                    char_start=match.start(),
                    char_end=article_end,
                )
                tree.articles.append(article)
                tree.blocks.append(
                    LawBlock("article", article_text, match.start(), article_end, article=article)
                )
                parent = current.get("section") or current.get("chapter") or current.get("book")
                if parent:
                    parent.article_refs.append(article)
            last_consumed = article_end
        self._append_preamble(tree, plain_text[last_consumed:], last_consumed)
        return tree

    def _attach_heading(
        self,
        tree: LawTree,
        current: dict[HierarchyLevel, LawNode | None],
        match: re.Match[str],
    ) -> None:
        """把编、章、节标题挂载到 LawTree 的正确父节点下。"""
        number = str(match.group("hierarchy"))
        title = (match.group("title") or "").strip()
        if number.endswith("编"):
            level: HierarchyLevel = "book"
            parent = tree.root
            current["chapter"] = None
            current["section"] = None
        elif number.endswith("章"):
            level = "chapter"
            parent = current.get("book") or tree.root
            current["section"] = None
        else:
            level = "section"
            parent = current.get("chapter") or current.get("book") or tree.root
        node = LawNode(level, number, title, match.start(), match.end())
        parent.add_child(node)
        current[level] = node

    def _current_hierarchy(self, current: dict[HierarchyLevel, LawNode | None]) -> dict[str, str]:
        """把当前树游标转换为 Article metadata 所需的层级字段。"""
        metadata: dict[str, str] = {}
        mapping = {
            "book": ("part_no", "part_title"),
            "chapter": ("chapter_no", "chapter_title"),
            "section": ("section_no", "section_title"),
        }
        for level, (number_key, title_key) in mapping.items():
            node = current.get(level)
            if node is None:
                continue
            metadata[number_key] = node.number
            if node.title:
                metadata[title_key] = node.title
        return metadata

    def _append_preamble(self, tree: LawTree, text: str, offset: int) -> None:
        """把非条文正文作为 preamble 保留，避免丢失施行说明等内容。"""
        value = text.strip()
        if not value:
            return
        start = offset + text.find(value)
        tree.blocks.append(LawBlock("preamble", value, start, start + len(value)))


class ChunkGenerator:
    """基于 LawTree 生成 Chunk，保证一条法条只生成一个 Article Chunk。"""

    def generate(self, tree: LawTree, chunk_size: int) -> list[dict[str, Any]]:
        """执行 LawTree -> Chunk 的切分流程。"""
        chunks: list[dict[str, Any]] = []
        for block in tree.blocks:
            if block.block_type == "article" and block.article is not None:
                chunks.append(self._article_chunk(block.article))
                continue
            for segment, start, end in self._split_preamble(block, chunk_size):
                chunks.append(
                    {
                        "chunk_type": "preamble",
                        "text": segment,
                        "token_count": count_tokens(segment),
                        "metadata": {
                            "chunk_level": "preamble",
                            "char_start": start,
                            "char_end": end,
                        },
                    }
                )
        return chunks

    def _article_chunk(self, article: LawArticle) -> dict[str, Any]:
        """构造单条法条 Chunk，并写入完整层级 metadata。"""
        metadata = {
            **article.hierarchy,
            "article": article.article_no,
            "article_no": article.article_no,
            "chunk_level": "article",
            "char_start": article.char_start,
            "char_end": article.char_end,
        }
        path_parts = [
            _title(metadata.get("part_no"), metadata.get("part_title")),
            _title(metadata.get("chapter_no"), metadata.get("chapter_title")),
            _title(metadata.get("section_no"), metadata.get("section_title")),
            article.article_no,
        ]
        metadata["hierarchy_path"] = " > ".join(part for part in path_parts if part)
        return {
            "chunk_type": "article",
            "text": article.text,
            "token_count": count_tokens(article.text),
            "metadata": metadata,
        }

    def _split_preamble(self, block: LawBlock, chunk_size: int) -> list[tuple[str, int, int]]:
        """仅对非法条 preamble 按大小兜底切分。"""
        max_chars = max(chunk_size * 2, 1)
        segments: list[tuple[str, int, int]] = []
        for index in range(0, len(block.text), max_chars):
            segment = block.text[index : index + max_chars].strip()
            if not segment:
                continue
            start = block.char_start + index + block.text[index : index + max_chars].find(segment)
            segments.append((segment, start, start + len(segment)))
        return segments


def _is_markdown_table_separator(value: str) -> bool:
    """识别 Markdown 表格分隔行。"""
    cells = [cell.strip() for cell in value.strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells)


def _first_non_empty_line(text: str) -> str | None:
    """返回第一个非空文本行。"""
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return None


def _title(number: Any, title: Any) -> str:
    """组合编号和标题用于层级路径。"""
    return " ".join(str(value).strip() for value in (number, title) if value).strip()
