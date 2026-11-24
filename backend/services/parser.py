"""文档解析与切分逻辑:先将文档转换为 Markdown,再执行法律文本切分与元数据提取。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from backend.config import settings
from backend.services.law_parser import (
    ChunkGenerator,
    LAW_NUMERAL,
    LawParser,
    clean_law_text,
    markdown_to_law_text,
)

logger = logging.getLogger(__name__)
_MINERU_MISSING_LOGGED = False


@dataclass(slots=True)
class ParsedDocument:
    """保存文档 Markdown 与解析过程中的非致命降级提示。"""

    markdown: str
    warnings: list[str] = field(default_factory=list)


async def parse_document(file_path: str, file_type: str) -> str:
    """解析文档并返回 Markdown 文本。"""
    parsed = await parse_document_with_metadata(file_path, file_type)
    return parsed.markdown


async def parse_document_with_metadata(file_path: str, file_type: str) -> ParsedDocument:
    """解析文档并返回 Markdown 文本与降级提示。"""
    return await asyncio.to_thread(_parse_document_sync_with_metadata, file_path, file_type)


async def chunk_document(
    text: str,
    kb_type: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
    filename: str = "",
) -> list[dict[str, Any]]:
    """将文本切分为具备法律语义感知的 Chunk。"""
    clean_text = _clean_text(_markdown_to_law_text(text))
    base_metadata = await extract_metadata(clean_text, kb_type, filename)
    chunks: list[dict[str, Any]] = []
    if kb_type in {"law", "judicial"}:
        # 法律类文档显式走 Markdown -> LawParser -> LawTree -> ChunkGenerator。
        law_tree = LawParser().parse(text)
        chunks = ChunkGenerator().generate(law_tree, chunk_size)
    if not chunks:
        chunks = _chunk_by_paragraph(clean_text, chunk_size, chunk_overlap)

    total = len(chunks)
    for index, chunk in enumerate(chunks):
        chunk["chunk_index"] = index
        chunk["metadata"] = {
            **base_metadata,
            **chunk.get("metadata", {}),
            "source_file": filename,
            "chunk_index": index,
            "total_chunks": total,
        }
    return chunks


async def extract_metadata(text: str, kb_type: str, filename: str) -> dict[str, Any]:
    """从文档文本中提取轻量级法律元数据。"""
    title = _first_non_empty_line(text) or Path(filename).stem
    metadata: dict[str, Any] = {
        "title": title[:200],
        "keywords": _extract_keywords(text),
        "source_format": "markdown",
    }
    if kb_type == "law":
        law_name = _extract_law_name(text, filename)
        metadata.update(
            {
                # PDF 可能从跨页残句或右栏开始，不能把第一个非空行
                # 当作文档标题传递到每个法条。
                "title": law_name,
                "law_name": law_name,
                "effective_date": _match_first(text, r"自([0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日)起施行"),
            }
        )
    elif kb_type == "case":
        metadata.update(
            {
                "case_name": title[:200],
                "case_no": _match_first(text, r"（?\(?[0-9]{4}[）)]?[\u4e00-\u9fa5]{1,20}[0-9]+号"),
                "court": _match_first(text, r"([\u4e00-\u9fa5]{2,40}(?:人民法院|仲裁委员会))"),
                "cause_of_action": _match_first(text, r"案由[:：]\s*([^\n]+)"),
                "judgment_date": _match_first(text, r"([0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日)"),
                "plaintiff": _match_first(text, r"原告[:：]?\s*([^\n，,。]+)"),
                "defendant": _match_first(text, r"被告[:：]?\s*([^\n，,。]+)"),
            }
        )
    elif kb_type == "contract":
        metadata.update(
            {
                "contract_name": title[:200],
                "clause_title": _match_first(text, r"([一二三四五六七八九十]+、[^\n]+)"),
                "clause_type": _match_first(text, r"(付款|违约|保密|解除|争议解决|交付|验收)"),
                "party": _match_first(text, r"(?:甲方|乙方)[:：]\s*([^\n]+)"),
            }
        )
    else:
        metadata.update({"source_page": None})
    return {key: value for key, value in metadata.items() if value not in (None, "")}


def _parse_document_sync(file_path: str, file_type: str) -> str:
    """同步解析文档为 Markdown,根据文件类型选择对应解析器。"""
    return _parse_document_sync_with_metadata(file_path, file_type).markdown


def _parse_document_sync_with_metadata(file_path: str, file_type: str) -> ParsedDocument:
    """同步解析文档为 Markdown,并记录 MinerU 等解析器降级原因。

    PDF 链路：MinerU → 扫描件检测 → PaddleOCR → pdfplumber 兜底。
    图片链路：PaddleOCR 直接识别。
    """
    path = Path(file_path)
    warnings: list[str] = []
    if file_type == "pdf":
        mineru_markdown, mineru_warnings = _parse_with_mineru(path)
        warnings.extend(mineru_warnings)
        if mineru_markdown and not _is_likely_scanned(mineru_markdown, path):
            return ParsedDocument(markdown=mineru_markdown, warnings=warnings)
        # MinerU 产出稀疏或失败：检测扫描件，扫描件走 OCR
        if _is_scanned_pdf(path):
            warnings.append("PDF 判定为扫描件，已使用 RapidOCR 识别")
            ocr_markdown = _ocr_pdf(path)
            if ocr_markdown:
                return ParsedDocument(markdown=ocr_markdown, warnings=warnings)
            warnings.append("OCR 未产出文本，降级为 pdfplumber")
        warnings.append("PDF 已使用版面感知的 pdfplumber 兜底转换为 Markdown")
        markdown = _parse_pdf_to_markdown(path, warnings)
        warnings.extend(_validate_extracted_legal_text(markdown))
        return ParsedDocument(markdown=markdown, warnings=list(dict.fromkeys(warnings)))
    if file_type == "docx":
        # 一些网站提供的“DOCX”实际是 Word 97-2003 OLE 二进制文档，只是后缀被
        # 错误改成了 .docx。python-docx 只能处理 ZIP/OOXML，需先通过本机 Word 转换。
        if _is_legacy_word_document(path):
            warnings.append("检测到旧版 Word 97-2003 文档，已自动转换为 DOCX 后解析")
            return ParsedDocument(markdown=_parse_legacy_word_to_markdown(path), warnings=warnings)
        # mineru_enabled 时优先用 MinerU 解析 DOCX（版面还原更好），失败降级 python-docx
        if settings.mineru_enabled:
            mineru_markdown, mineru_warnings = _parse_with_mineru(path)
            warnings.extend(mineru_warnings)
            if mineru_markdown:
                return ParsedDocument(markdown=mineru_markdown, warnings=warnings)
            warnings.append("DOCX MinerU 解析失败，已降级为 python-docx")
        return ParsedDocument(markdown=_parse_docx_to_markdown(path), warnings=warnings)
    if file_type == "txt":
        return ParsedDocument(
            markdown=_clean_markdown(path.read_text(encoding="utf-8", errors="ignore")),
            warnings=warnings,
        )
    if file_type == "html":
        return ParsedDocument(markdown=_parse_html_to_markdown(path), warnings=warnings)
    if file_type == "image":
        # 图片走 OCR：优先阿里云 OCR，失败降级本地 RapidOCR；OCR 不可用时返回空 Markdown 由上层报 409
        warnings.append("图片已使用 OCR 识别")
        from backend.services.ocr import ocr_image
        from backend.services.ocr_aliyun import ocr_image_aliyun

        markdown = ocr_image_aliyun(str(path))
        if not markdown:
            markdown = ocr_image(str(path))
        if not markdown:
            warnings.append("OCR 未产出文本，请上传更清晰的图片或启用 OCR")
        return ParsedDocument(markdown=markdown, warnings=warnings)
    raise ValueError(f"不支持的解析器文件类型: {file_type}")


def _is_likely_scanned(markdown: str, path: Path) -> bool:
    """MinerU 产出的 Markdown 字符密度过低时怀疑是扫描件，需进一步检测。"""
    if not markdown.strip():
        return True
    page_count = _estimate_pdf_page_count(path)
    if page_count <= 0:
        return False
    chars_per_page = len(markdown) / page_count
    return chars_per_page < settings.ocr_min_chars_per_page


def _is_scanned_pdf(path: Path) -> bool:
    """用 pdfplumber 提取文本，每页平均字符数低于阈值则判定为扫描件。"""
    try:
        import pdfplumber
    except ImportError:
        return False
    try:
        with pdfplumber.open(path) as pdf:
            page_count = len(pdf.pages)
            if page_count == 0:
                return False
            total_chars = sum(len(page.extract_text() or "") for page in pdf.pages)
            return (total_chars / page_count) < settings.ocr_min_chars_per_page
    except Exception:  # noqa: BLE001
        return False


def _estimate_pdf_page_count(path: Path) -> int:
    """快速估算 PDF 页数，失败返回 0。"""
    try:
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            return len(pdf.pages)
    except Exception:  # noqa: BLE001
        return 0


def _ocr_pdf(path: Path) -> str:
    """调用 OCR 服务把扫描版 PDF 转为 Markdown；优先阿里云 OCR，失败降级本地 RapidOCR。"""
    from backend.services.ocr import ocr_pdf_to_markdown
    from backend.services.ocr_aliyun import ocr_pdf_aliyun

    aliyun_markdown = ocr_pdf_aliyun(str(path))
    if aliyun_markdown.strip():
        return aliyun_markdown
    return ocr_pdf_to_markdown(str(path))


def _parse_with_mineru(path: Path) -> tuple[str | None, list[str]]:
    """优先调用本地 MinerU CLI 将 PDF 转为 Markdown,不可用时返回 warning 交给 fallback。"""
    global _MINERU_MISSING_LOGGED
    if not settings.mineru_enabled:
        return None, []
    executable = shutil.which("mineru") or shutil.which("magic-pdf")
    if executable is None:
        message = "MinerU CLI 未安装或不在 PATH,已降级为 pdfplumber"
        if not _MINERU_MISSING_LOGGED:
            logger.info(message)
            _MINERU_MISSING_LOGGED = True
        return None, [message]

    with tempfile.TemporaryDirectory(prefix="lawrag-mineru-") as output_dir:
        command = [
            executable,
            "-p",
            str(path),
            "-o",
            output_dir,
            "-m",
            settings.mineru_method,
        ]
        if settings.mineru_backend:
            command.extend(["-b", settings.mineru_backend])
        if settings.mineru_lang:
            command.extend(["-l", settings.mineru_lang])
        if settings.mineru_api_url:
            command.extend(["--api-url", settings.mineru_api_url])

        warnings: list[str] = []
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                check=False,
                encoding="utf-8",
                errors="ignore",
                text=True,
                timeout=settings.mineru_timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            message = f"MinerU 解析超过 {settings.mineru_timeout_seconds}s,已降级为 pdfplumber"
            logger.warning(message)
            return None, [message]
        except (OSError, subprocess.SubprocessError) as exc:
            message = f"MinerU 调用失败,已降级为 pdfplumber: {exc}"
            logger.warning(message)
            return None, [message]
        if result.returncode != 0:
            message = f"MinerU 解析失败,已降级为 pdfplumber: {result.stderr[:1000]}"
            logger.warning(message)
            return None, [message]

        markdown_files = [
            file
            for file in Path(output_dir).rglob("*.md")
            if file.is_file() and file.stat().st_size > 0
        ]
        if not markdown_files:
            message = "MinerU 未产出 Markdown,已降级为 pdfplumber"
            logger.warning(message)
            return None, [message]
        markdown_file = max(markdown_files, key=lambda file: file.stat().st_size)
        return _clean_markdown(markdown_file.read_text(encoding="utf-8", errors="ignore")), warnings


def _parse_pdf_to_markdown(path: Path, warnings: list[str] | None = None) -> str:
    """使用版面感知的 pdfplumber 兜底把 PDF 整理为 Markdown。

    页面先裁掉常见页眉页脚；检测到双栏时严格按左栏、右栏顺序提取，避免
    同一水平线上的两栏文字交错。全部页面提取完成后再移除重复页眉与页脚。
    """
    import pdfplumber

    page_blocks: list[tuple[int, str, list[str]]] = []
    two_column_pages = 0
    with pdfplumber.open(path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            blocks: list[str] = []
            text, is_two_column = _extract_pdf_page_text(page)
            two_column_pages += int(is_two_column)
            if text.strip():
                blocks.append(_text_block_to_markdown(text))
            for table in page.extract_tables() or []:
                markdown_table = _markdown_table(table)
                if markdown_table:
                    blocks.append(markdown_table)
            if blocks:
                page_blocks.append((page_number, "\n\n".join(blocks), []))
    cleaned_pages = _remove_repeated_page_boundaries(page_blocks)
    if warnings is not None and two_column_pages:
        warnings.append(f"检测并按左右栏顺序解析 {two_column_pages} 个双栏页面")
    pages = [f"<!-- page:{page_number} -->\n\n{text}" for page_number, text in cleaned_pages if text]
    return _clean_markdown("\n\n".join(pages))


def _extract_pdf_page_text(page) -> tuple[str, bool]:
    """裁剪页眉页脚并根据行内中央留白判断是否为双栏页面。"""
    width = float(page.width)
    height = float(page.height)
    top = height * 0.045
    bottom = height * 0.955
    body = page.crop((0, top, width, bottom))
    words = body.extract_words(use_text_flow=False, keep_blank_chars=False) or []
    if not words:
        return "", False

    lines = _group_pdf_words_by_line(words)
    midpoint = width / 2
    wide_gutter_lines = 0
    split_lines = 0
    for line in lines:
        left = [word for word in line if float(word["x1"]) <= midpoint]
        right = [word for word in line if float(word["x0"]) >= midpoint]
        if not left or not right:
            continue
        split_lines += 1
        gutter = min(float(word["x0"]) for word in right) - max(float(word["x1"]) for word in left)
        if gutter >= width * 0.055:
            wide_gutter_lines += 1

    # 双栏页在大量正文行的中心都有稳定宽留白；单栏行只存在普通字词间距。
    is_two_column = (
        len(lines) >= 12
        and split_lines >= 8
        and wide_gutter_lines >= max(5, int(split_lines * 0.38))
    )
    if not is_two_column:
        return body.extract_text(x_tolerance=2, y_tolerance=3) or "", False

    gutter = width * 0.025
    left_page = page.crop((0, top, midpoint - gutter, bottom))
    right_page = page.crop((midpoint + gutter, top, width, bottom))
    left_text = left_page.extract_text(x_tolerance=2, y_tolerance=3) or ""
    right_text = right_page.extract_text(x_tolerance=2, y_tolerance=3) or ""
    return "\n".join(part for part in (left_text.strip(), right_text.strip()) if part), True


def _group_pdf_words_by_line(words: list[dict[str, Any]], tolerance: float = 3.0) -> list[list[dict[str, Any]]]:
    """按纵坐标把 pdfplumber word 分组，供双栏版式检测使用。"""
    lines: list[list[dict[str, Any]]] = []
    tops: list[float] = []
    for word in sorted(words, key=lambda item: (float(item["top"]), float(item["x0"]))):
        word_top = float(word["top"])
        target = next((index for index, value in enumerate(tops) if abs(value - word_top) <= tolerance), None)
        if target is None:
            tops.append(word_top)
            lines.append([word])
        else:
            lines[target].append(word)
    for line in lines:
        line.sort(key=lambda item: float(item["x0"]))
    return lines


def _remove_repeated_page_boundaries(
    pages: list[tuple[int, str, list[str]]],
) -> list[tuple[int, str]]:
    """移除重复页眉/页脚和孤立页码，不触碰正文内部的数字。"""
    boundary_counts: dict[str, int] = {}
    split_pages: list[tuple[int, list[str]]] = []
    for page_number, text, _ in pages:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        split_pages.append((page_number, lines))
        # 短页面的头尾取样可能重叠；同一页的同一行只计一次，
        # 否则会把仅出现一页的正文误判为“重复页眉”。
        for line in dict.fromkeys(lines[:3] + lines[-3:]):
            normalized = re.sub(r"\s+", "", line)
            if normalized:
                boundary_counts[normalized] = boundary_counts.get(normalized, 0) + 1

    repeat_threshold = max(2, int(len(split_pages) * 0.35))
    cleaned: list[tuple[int, str]] = []
    page_number_pattern = re.compile(r"^(?:[-—－]\s*)?\d{1,4}(?:\s*[-—－])?$")
    for page_number, lines in split_pages:
        output: list[str] = []
        for index, line in enumerate(lines):
            normalized = re.sub(r"\s+", "", line)
            is_boundary = index < 3 or index >= max(0, len(lines) - 3)
            is_repeated_boundary = is_boundary and boundary_counts.get(normalized, 0) >= repeat_threshold
            if page_number_pattern.fullmatch(line) or is_repeated_boundary:
                continue
            output.append(line)
        cleaned.append((page_number, "\n".join(output)))
    return cleaned


def _validate_extracted_legal_text(markdown: str) -> list[str]:
    """对解析文本执行轻量结构质检，异常只告警，不阻断入库。"""
    warnings: list[str] = []
    plain = markdown_to_law_text(markdown)
    if re.search(r"(?m)^\s*(?:[-—－]\s*)?\d{1,4}(?:\s*[-—－])?\s*$", plain):
        warnings.append("解析文本仍可能包含孤立页码，请检查原文版式")
    article_numbers = re.findall(rf"(?m)^\s*(第{LAW_NUMERAL}条)", plain)
    duplicates = {number for number in article_numbers if article_numbers.count(number) > 1}
    if duplicates:
        warnings.append(f"检测到重复条号 {len(duplicates)} 个，可能是汇编引用或版面顺序异常")
    return warnings


def _parse_docx_to_markdown(path: Path) -> str:
    """将 Word 段落、标题和表格按原始顺序转换为 Markdown。"""
    from docx import Document
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = Document(path)
    blocks: list[str] = []
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            paragraph = Paragraph(child, document)
            markdown = _docx_paragraph_to_markdown(paragraph)
            if markdown:
                blocks.append(markdown)
        elif isinstance(child, CT_Tbl):
            table = Table(child, document)
            rows = [[cell.text for cell in row.cells] for row in table.rows]
            markdown_table = _markdown_table(rows)
            if markdown_table:
                blocks.append(markdown_table)
    return _clean_markdown("\n\n".join(blocks))


def _is_legacy_word_document(path: Path) -> bool:
    """识别 Word 97-2003 OLE 复合文档，即使文件被错误命名为 .docx。"""
    with path.open("rb") as source:
        return source.read(8) == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _parse_legacy_word_to_markdown(path: Path) -> str:
    """使用 Windows 上已安装的 Microsoft Word 将旧版 .doc 转为临时 .docx。"""
    with tempfile.TemporaryDirectory(prefix="lawagent-word-") as tmp_dir:
        workspace = Path(tmp_dir)
        legacy_path = workspace / "source.doc"
        converted_path = workspace / "converted.docx"
        shutil.copyfile(path, legacy_path)
        _convert_legacy_word_to_docx(legacy_path, converted_path)
        if not converted_path.exists() or converted_path.stat().st_size == 0:
            raise RuntimeError("旧版 Word 文档转换失败：未生成有效 DOCX 文件")
        return _parse_docx_to_markdown(converted_path)


def _convert_legacy_word_to_docx(source: Path, target: Path) -> None:
    """通过 Word COM 在独立线程中完成格式转换；调用方已位于 asyncio.to_thread。"""
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        raise RuntimeError(
            "检测到旧版 Word .doc 文件；请安装 Microsoft Word 与 pywin32，或另存为真正的 .docx 后重新上传"
        ) from exc

    pythoncom.CoInitialize()
    word = None
    document = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        document = word.Documents.Open(
            str(source.resolve()),
            ConfirmConversions=False,
            ReadOnly=True,
            AddToRecentFiles=False,
        )
        # 16 = wdFormatDocumentDefault（Office Open XML .docx）
        document.SaveAs2(str(target.resolve()), FileFormat=16, AddToRecentFiles=False)
    except Exception as exc:
        raise RuntimeError(f"旧版 Word 文档自动转换失败：{exc}") from exc
    finally:
        if document is not None:
            try:
                document.Close(SaveChanges=False)
            except Exception:  # noqa: BLE001
                pass
        if word is not None:
            try:
                word.Quit(SaveChanges=False)
            except Exception:  # noqa: BLE001
                pass
        pythoncom.CoUninitialize()


def _parse_html_to_markdown(path: Path) -> str:
    """将 HTML 常见结构转换为 Markdown,用于与 PDF/Word 解析结果保持一致。"""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="ignore"), "lxml")
    blocks: list[str] = []
    for element in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table"]):
        name = element.name or ""
        text = element.get_text(" ", strip=True)
        if not text:
            continue
        if re.fullmatch(r"h[1-6]", name):
            blocks.append(f"{'#' * int(name[1])} {text}")
        elif name == "li":
            blocks.append(f"- {text}")
        elif name == "table":
            rows = [
                [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
                for row in element.find_all("tr")
            ]
            markdown_table = _markdown_table(rows)
            if markdown_table:
                blocks.append(markdown_table)
        else:
            blocks.append(text)
    return _clean_markdown("\n\n".join(blocks) or soup.get_text("\n"))


def _docx_paragraph_to_markdown(paragraph) -> str:
    """将单个 Word 段落转换为 Markdown 段落或标题。"""
    text = paragraph.text.strip()
    if not text:
        return ""
    style_name = paragraph.style.name if paragraph.style else ""
    heading = re.search(r"(?:Heading|标题)\s*([1-6])", style_name, flags=re.IGNORECASE)
    if heading:
        return f"{'#' * int(heading.group(1))} {text}"
    if "List Bullet" in style_name or "项目符号" in style_name:
        return f"- {text}"
    if "List Number" in style_name or "编号" in style_name:
        return f"1. {text}"
    return text


def _text_block_to_markdown(text: str) -> str:
    """将版面解析出的文本块规范为 Markdown 段落,保留法律标题与法条边界。"""
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _markdown_table(rows: list[list[Any]]) -> str:
    """把二维表格转换为 GitHub Markdown 表格。"""
    normalized = [
        [_escape_table_cell(str(cell or "").strip()) for cell in row]
        for row in rows
        if any(str(cell or "").strip() for cell in row)
    ]
    if not normalized:
        return ""
    width = max(len(row) for row in normalized)
    padded = [row + [""] * (width - len(row)) for row in normalized]
    header = padded[0]
    body = padded[1:]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)


def _escape_table_cell(text: str) -> str:
    """转义 Markdown 表格单元格中的竖线与换行。"""
    return text.replace("|", "\\|").replace("\r\n", " ").replace("\n", " ").strip()


def _clean_markdown(text: str) -> str:
    """清洗 Markdown:统一换行、压缩横向空白并保留段落空行。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).rstrip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _markdown_to_law_text(markdown: str) -> str:
    """将 Markdown 转为正则 LawParser 更稳定处理的纯法律文本。"""
    return markdown_to_law_text(markdown)


def _is_markdown_table_separator(value: str) -> bool:
    """识别 Markdown 表格分隔行,避免把 | --- | --- | 当作正文。"""
    cells = [cell.strip() for cell in value.strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells)


def _clean_text(text: str) -> str:
    """清洗文本:统一换行、压缩空白、剔除页码、合并多余空行。"""
    return clean_law_text(text)


def _chunk_by_paragraph(text: str, chunk_size: int, chunk_overlap: int) -> list[dict[str, Any]]:
    """按段落聚合切分文本,必要时叠加 overlap。"""
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if _estimate_tokens(current + "\n\n" + paragraph) <= chunk_size:
            current = f"{current}\n\n{paragraph}".strip()
            continue
        if current:
            chunks.append(current)
        if _estimate_tokens(paragraph) > chunk_size:
            chunks.extend(_split_by_size(paragraph, chunk_size))
            current = ""
        else:
            current = paragraph
    if current:
        chunks.append(current)

    if chunk_overlap <= 0 or len(chunks) < 2:
        return [_build_paragraph_chunk(chunk) for chunk in chunks]

    overlap_chars = chunk_overlap * 2
    overlapped = [chunks[0]]
    for index in range(1, len(chunks)):
        previous = chunks[index - 1]
        prefix = previous[-overlap_chars:] if len(previous) > overlap_chars else ""
        overlapped.append(f"{prefix}\n{chunks[index]}".strip())
    return [_build_paragraph_chunk(chunk) for chunk in overlapped]


def _split_by_size(text: str, chunk_size: int) -> list[str]:
    """按固定字符上限将文本切分为多段。"""
    max_chars = max(chunk_size * 2, 1)
    return [text[index : index + max_chars].strip() for index in range(0, len(text), max_chars)]


def _build_paragraph_chunk(text: str) -> dict[str, Any]:
    """构造段落类型 Chunk 的字典结构。"""
    return {
        "chunk_type": "paragraph",
        "text": text,
        "token_count": _estimate_tokens(text),
        "metadata": {},
    }


def _estimate_tokens(text: str) -> int:
    """按字符数粗略估算 token 数。"""
    return max(0, len(text) // 2)


def _first_non_empty_line(text: str) -> str | None:
    """返回文本中第一个非空行。"""
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return None


def _extract_law_name(text: str, filename: str) -> str:
    """推断法律名称，优先使用用户上传时的原始文件名。

    PDF 文本的第一行可能是页眉、跨页残句或双栏右侧内容；
    例如“……依法追究刑事责任”中含有“法”字，但它不是法律名称。
    """
    filename_title = Path(filename).stem.strip()
    if filename_title:
        return filename_title[:200]
    first_line = _first_non_empty_line(text)
    if first_line and ("法" in first_line or "条例" in first_line or "规定" in first_line):
        return first_line[:200]
    return Path(filename).stem


def _extract_keywords(text: str) -> list[str]:
    """从预设候选词中筛选出文本中出现的法律关键词。"""
    candidates = ["合同", "侵权", "民事", "刑事", "行政", "劳动", "婚姻", "公司", "知识产权", "诉讼"]
    return [word for word in candidates if word in text][:8]


def _match_first(text: str, pattern: str) -> str | None:
    """返回正则首个匹配的捕获组,无捕获组则返回整体匹配。"""
    match = re.search(pattern, text)
    if not match:
        return None
    return next((group for group in match.groups() if group), match.group(0)).strip()
