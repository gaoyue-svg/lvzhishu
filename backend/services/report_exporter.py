"""本文件实现合同审查报告的 .docx 导出。

把分析最终报告（markdown）+ 关键要素表渲染为 Word 文档，供下载归档。
markdown→docx 采用轻量渲染器（标题/列表/表格/粗体），足够覆盖合同审查报告结构。
"""

from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Any, Iterable

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

_DISCLAIMER = (
    "本报告由 AI 生成，仅供合同审阅参考，不构成正式法律意见。\n"
    "涉及重大权益的合同签署前，建议咨询专业律师复核。"
)

_DRAFT_DISCLAIMER = "本文件由 AI 辅助生成，提交、签署或对外使用前请结合真实事实补充信息并由专业人士复核。"

_LEGAL_DOCUMENT_TITLES = (
    "房屋租赁合同",
    "劳动合同",
    "民事起诉状",
    "劳动仲裁申请书",
    "行政起诉状",
    "刑事自诉状",
    "民事答辩状",
    "上诉状",
    "申请书",
    "律师函",
    "催告函",
    "通知书",
    "协议书",
    "合同",
)

_NON_DOCUMENT_HEADINGS = (
    "直接结论", "核心条款的法律边界与适用条件", "法律边界与适用条件",
    "需要进一步确认的信息与条件式结论", "需要进一步确认的信息",
    "处理路径与证据建议", "法律依据", "风险提示", "常见误区",
)


def build_contract_report_docx(
    *,
    report_markdown: str,
    elements: dict[str, Any] | None,
    summary: str,
    filename: str,
) -> io.BytesIO:
    """把合同分析结果渲染为 .docx，返回 BytesIO（调用方负责转 StreamingResponse）。"""
    doc = Document()
    _set_base_style(doc)

    doc.add_heading("合同审查报告", level=0)
    meta = doc.add_paragraph()
    meta.add_run(f"合同文件：{filename}")
    meta.add_run(f"\n生成时间：{datetime.now():%Y-%m-%d %H:%M}")

    if summary:
        doc.add_heading("一、合同摘要", level=1)
        _append_markdown(doc, summary)

    elements_map = elements or {}
    flattened = list(_flatten_elements(elements_map))
    if flattened:
        doc.add_heading("二、关键要素", level=1)
        table = doc.add_table(rows=1, cols=2)
        table.style = "Table Grid"
        header = table.rows[0].cells
        header[0].text = "要素"
        header[1].text = "内容"
        for key, value in flattened:
            cells = table.add_row().cells
            cells[0].text = key
            cells[1].text = value

    if report_markdown and report_markdown.strip():
        doc.add_heading("三、风险审查", level=1)
        _append_markdown(doc, report_markdown)

    doc.add_heading("四、免责声明", level=1)
    _append_markdown(doc, _DISCLAIMER)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer


def build_legal_document_docx(
    *, content_markdown: str, title: str | None = None, request_text: str = ""
) -> io.BytesIO:
    """把 Agent 生成的法律文书或回答渲染为可下载的 Word 文档。"""
    document_title = (title or infer_legal_document_title(content_markdown, request_text=request_text)).strip() or "LawAgent 法律文书"
    document_body = _normalize_form_placeholders(
        extract_legal_document_body(content_markdown, title=document_title)
    )
    doc = Document()
    _set_legal_document_layout(doc)
    heading = doc.add_paragraph()
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = heading.add_run(document_title)
    run.bold = True
    run.font.size = Pt(20)
    run.font.name = "宋体"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    _append_markdown(doc, document_body)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer


def _normalize_form_placeholders(text: str) -> str:
    """把模型生成的说明型方括号占位符转换为可填写空白栏。"""
    # “【姓名/名称】”“【填写具体金额】”在 Word 中会被误认为已经填写的正文；
    # 导出兜底时统一改成横线，保留可打印、可手写/录入的表单语义。
    return re.sub(r"【[^】\r\n]{1,40}】", "__________", text)


def infer_legal_document_title(content_markdown: str, *, request_text: str = "") -> str:
    """从回答内容识别常见法律文书标题，用于 Word 标题和下载文件名。"""
    request_plain = _inline_plain(request_text)
    if "房屋租赁" in request_plain or "租房合同" in request_plain:
        return "房屋租赁合同"
    if "劳动合同" in request_plain:
        return "劳动合同"
    plain = _inline_plain(content_markdown)
    for candidate in _LEGAL_DOCUMENT_TITLES:
        if candidate in plain:
            return candidate
    for line in content_markdown.replace("\r\n", "\n").split("\n"):
        value = re.sub(r"^#{1,6}\s+", "", line.strip())
        value = _inline_plain(value).strip(" ：:，,。")
        if value and len(value) <= 30 and not re.match(r"^[一二三四五六七八九十]+[、.]", value):
            return value
    return "LawAgent 法律文书"


def extract_legal_document_body(content_markdown: str, *, title: str) -> str:
    """从历史问答式输出中只保留正式文书，避免分析内容进入下载文件。"""
    lines = content_markdown.replace("\r\n", "\n").split("\n")
    start = 0
    for index, line in enumerate(lines):
        plain = _inline_plain(re.sub(r"^#{1,6}\s+", "", line.strip())).strip(" ：:")
        if title in plain or (title == "房屋租赁合同" and "房屋租赁合同模板" in plain):
            start = index + 1
            break
    kept: list[str] = []
    for line in lines[start:]:
        plain = _inline_plain(re.sub(r"^#{1,6}\s+", "", line.strip())).strip(" ：:")
        if any(plain.startswith(heading) for heading in _NON_DOCUMENT_HEADINGS):
            break
        if plain.startswith(("为您提供", "以下为您", "基于您提供")) and not kept:
            continue
        cleaned = re.sub(r"\s*\[(?:\d+)(?:\]\[\d+)*\]", "", line)
        cleaned = re.sub(r"\[(\d+)\]", "", cleaned)
        if "该回答仅供参考" in cleaned or "本文件由 AI 辅助生成" in cleaned:
            continue
        kept.append(cleaned)
    body = "\n".join(kept).strip()
    return body or content_markdown.strip()


def _set_legal_document_layout(doc: Document) -> None:
    """按可打印、可签署的中文合同设置页面与正文格式。"""
    _set_base_style(doc)
    section = doc.sections[0]
    section.top_margin = Cm(2.5)
    section.bottom_margin = Cm(2.5)
    section.left_margin = Cm(2.8)
    section.right_margin = Cm(2.6)
    style = doc.styles["Normal"]
    style.font.size = Pt(12)
    style.paragraph_format.line_spacing = 1.5
    style.paragraph_format.space_after = Pt(3)
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run("第 ")
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)
    footer.add_run(" 页")


def _set_base_style(doc: Document) -> None:
    """统一正文字体，中文字体优先宋体。"""
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)
    try:
        style.element.rPr.rFonts.set(__import__("docx").oxml.ns.qn("w:eastAsia"), "宋体")
    except Exception:  # noqa: BLE001
        pass


def _flatten_elements(elements: dict[str, Any]) -> Iterable[tuple[str, str]]:
    """把要素字典拍平为 (中文标签, 文本) 列表，兼容嵌套 dict/list。"""
    label_map = {
        "contract_name": "合同名称",
        "contract_type": "合同类型",
        "party_a": "甲方",
        "party_b": "乙方",
        "amount": "合同金额",
        "currency": "币种",
        "payment_terms": "付款方式",
        "payment_deadline": "付款期限",
        "contract_term": "合同期限",
        "effective_date": "生效日期",
        "governing_law": "适用法律",
        "jurisdiction": "争议解决",
        "breach_liability": "违约责任",
        "signing_requirements": "签署生效条件",
        "key_obligations": "核心义务",
        "important_clauses": "重要条款",
    }
    for key, value in elements.items():
        if value in (None, "", [], {}):
            continue
        label = label_map.get(key, key)
        if isinstance(value, dict):
            # 当事人等嵌套对象：a=b 拼接
            parts = [f"{k}：{v}" for k, v in value.items() if v]
            text = "；".join(parts)
        elif isinstance(value, list):
            text = "\n".join(str(item) for item in value if item)
        else:
            text = str(value)
        if text.strip():
            yield label, text.strip()


def _append_markdown(doc: Document, markdown: str) -> None:
    """把轻量 markdown 追加到 docx：标题/列表/表格/粗体。"""
    lines = markdown.replace("\r\n", "\n").split("\n")
    table_buffer: list[str] = []
    for line in lines:
        stripped = line.strip()
        # 收集 markdown 表格行
        if stripped.startswith("|") and stripped.endswith("|"):
            if _is_table_separator(stripped):
                continue
            table_buffer.append(stripped)
            continue
        if table_buffer:
            _append_table(doc, table_buffer)
            table_buffer = []
        if not stripped:
            continue
        # 标题
        heading = re.fullmatch(r"(#{1,6})\s+(.+)", stripped)
        if heading:
            level = min(len(heading.group(1)), 4)
            doc.add_heading(_inline_plain(heading.group(2)), level=level)
            continue
        # 无序列表
        if re.fullmatch(r"[-*]\s+(.+)", stripped):
            paragraph = doc.add_paragraph(style="List Bullet")
            _add_inline_runs(paragraph, re.fullmatch(r"[-*]\s+(.+)", stripped).group(1))
            continue
        # 有序列表
        ordered = re.fullmatch(r"\d+[.、)]\s*(.+)", stripped)
        if ordered:
            paragraph = doc.add_paragraph(style="List Number")
            _add_inline_runs(paragraph, ordered.group(1))
            continue
        paragraph = doc.add_paragraph()
        paragraph.paragraph_format.first_line_indent = Cm(0.74)
        _add_inline_runs(paragraph, stripped)
    if table_buffer:
        _append_table(doc, table_buffer)


def _append_table(doc: Document, rows: list[str]) -> None:
    """把 markdown 表格行渲染为 docx 表格。"""
    parsed = []
    for line in rows:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if cells:
            parsed.append(cells)
    if not parsed:
        return
    table = doc.add_table(rows=len(parsed), cols=max(len(row) for row in parsed))
    table.style = "Table Grid"
    for row_index, row in enumerate(parsed):
        for col_index, cell in enumerate(row):
            table.rows[row_index].cells[col_index].text = _inline_plain(cell)


def _add_inline_runs(paragraph, text: str) -> None:
    """把含 **粗体** 的文本按段拆分写入 docx 段落。"""
    segments = re.split(r"(\*\*.+?\*\*)", text)
    for segment in segments:
        if not segment:
            continue
        if segment.startswith("**") and segment.endswith("**"):
            run = paragraph.add_run(segment[2:-2])
            run.bold = True
        else:
            paragraph.add_run(segment)


def _inline_plain(text: str) -> str:
    """去掉行内 markdown 标记，返回纯文本。"""
    return text.replace("**", "")


def _is_table_separator(line: str) -> bool:
    """识别 markdown 表格分隔行 | --- | --- |。"""
    cells = [cell.strip() for cell in line.strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)
