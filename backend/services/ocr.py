"""本文件实现 OCR 识别能力，基于 RapidOCR(onnxruntime) 把扫描件和图片转为可检索文本。

设计要点：
1. RapidOCR 引擎懒加载，首次调用时初始化，避免拖慢应用启动。
2. RapidOCR 未安装或初始化失败时返回空结果与原因，交由上层 parser 决定降级策略。
3. PDF 逐页渲染为图片后 OCR，保留 <!-- page:N --> 标记，与现有 parser 输出风格一致。
4. 单页 OCR 超时跳过，不阻塞整份文档解析。

注：原基于 PaddleOCR 的实现因 paddlepaddle 未提供 Python 3.14 wheel 而改用 RapidOCR，
RapidOCR 同样基于 PaddleOCR 模型，识别质量一致但无需 paddlepaddle 重依赖。
"""

from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path
from typing import Any

from backend.config import settings

logger = logging.getLogger(__name__)

# RapidOCR 引擎单例，懒加载；初始化失败后置为 False 避免重复尝试
_engine_instance: Any = None
_engine_init_failed: bool = False

# 支持的图片扩展名
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}


def _get_engine() -> Any:
    """懒加载 RapidOCR 引擎；未安装或初始化失败时返回 None 并标记失败。"""
    global _engine_instance, _engine_init_failed
    if _engine_init_failed:
        return None
    if _engine_instance is not None:
        return _engine_instance

    try:
        # 延迟 import，避免 rapidocr 未安装时影响整个进程
        from rapidocr_onnxruntime import RapidOCR  # type: ignore[import-not-found]

        # RapidOCR 默认加载中英文检测+识别+分类模型，无需额外参数
        _engine_instance = RapidOCR()
        logger.info("RapidOCR 初始化成功")
        return _engine_instance
    except Exception as exc:  # noqa: BLE001
        _engine_init_failed = True
        logger.warning("RapidOCR 初始化失败，OCR 功能不可用: %s: %s", exc.__class__.__name__, exc)
        return None


def is_ocr_available() -> bool:
    """检查 OCR 是否可用（provider 已启用且 RapidOCR 可加载）。"""
    if settings.ocr_provider != "rapidocr":
        return False
    return _get_engine() is not None


def ocr_image(image_path: str) -> str:
    """对单张图片执行 OCR，返回清洗后的纯文本。

    失败时返回空字符串，交由上层判断是否报错或降级。
    """
    engine = _get_engine()
    if engine is None:
        logger.warning("OCR 不可用，跳过图片识别: %s", image_path)
        return ""

    try:
        # RapidOCR 返回 (result, elapse)；result 为 [[box, text, score], ...] 或 None
        result, _elapse = engine(str(image_path))
    except Exception as exc:  # noqa: BLE001
        logger.warning("图片 OCR 失败 path=%s error=%s: %s", image_path, exc.__class__.__name__, exc)
        return ""

    return _extract_text_from_result(result)


def ocr_pdf_to_markdown(pdf_path: str) -> str:
    """把扫描版 PDF 逐页转为图片后 OCR，拼成带页码标记的 Markdown。

    流程：pdf2image 渲染每页 → ocr_image → 拼接 <!-- page:N -->。
    pdf2image 依赖系统级 poppler；不可用时降级为 pdfplumber 直接提取（文字版兜底）。
    """
    engine = _get_engine()
    if engine is None:
        logger.warning("OCR 不可用，跳过 PDF 识别: %s", pdf_path)
        return ""

    # 优先用 pdf2image 把 PDF 页面渲染为图片
    page_images = _render_pdf_to_images(pdf_path)
    if not page_images:
        # pdf2image 不可用时，尝试用 pdfplumber 提取文本（扫描件会返回空）
        logger.warning("PDF 转图片失败，尝试 pdfplumber 兜底提取文本: %s", pdf_path)
        return _fallback_pdf_text(pdf_path)

    pages: list[str] = []
    for index, image_path in enumerate(page_images, start=1):
        try:
            text = ocr_image(image_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("PDF 第 %d 页 OCR 失败，跳过: %s", index, exc.__class__.__name__)
            text = ""
        if text.strip():
            pages.append(f"<!-- page:{index} -->\n\n{text}")

    # 清理临时图片
    for image_path in page_images:
        try:
            Path(image_path).unlink(missing_ok=True)
        except OSError:
            pass

    return _clean_md("\n\n".join(pages))


def _render_pdf_to_images(pdf_path: str) -> list[str]:
    """用 pdf2image 把 PDF 每页渲染为 PNG 临时文件；失败返回空列表。"""
    try:
        from pdf2image import convert_from_path  # type: ignore[import-not-found]
    except ImportError:
        logger.warning("pdf2image 未安装，无法把 PDF 转图片；请安装 poppler + pdf2image")
        return []

    try:
        with tempfile.TemporaryDirectory(prefix="lawrag-ocr-") as tmp_dir:
            pages = convert_from_path(
                pdf_path,
                dpi=200,
                output_folder=tmp_dir,
                fmt="png",
                paths_only=True,
            )
            # paths_only=True 时返回路径字符串列表，但临时目录会被清理
            # 需要把图片复制到独立临时文件，避免目录释放后丢失
            result: list[str] = []
            for index, page in enumerate(pages, start=1):
                src = Path(str(page))
                dst = Path(tempfile.gettempdir()) / f"lawrag-ocr-page-{index}-{src.name}"
                src.replace(dst)
                result.append(str(dst))
            return result
    except Exception as exc:  # noqa: BLE001
        logger.warning("PDF 转图片失败 path=%s error=%s: %s", pdf_path, exc.__class__.__name__, exc)
        return []


def _fallback_pdf_text(pdf_path: str) -> str:
    """pdf2image 不可用时用 pdfplumber 兜底提取文字版 PDF 文本。"""
    try:
        import pdfplumber
    except ImportError:
        return ""

    pages: list[str] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for index, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                if text.strip():
                    pages.append(f"<!-- page:{index} -->\n\n{text}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("pdfplumber 兜底提取失败 path=%s error=%s", pdf_path, exc.__class__.__name__)
        return ""
    return _clean_md("\n\n".join(pages))


def _extract_text_from_result(result: Any) -> str:
    """从 RapidOCR 返回结果中提取纯文本，按行聚合。

    RapidOCR 返回 result 为 list[[box, text, score]] 或 None；
    每条 item 中 item[1] 为文本字符串，item[2] 为置信度。
    """
    if not result:
        return ""

    lines: list[str] = []
    for item in result:
        if not item or len(item) < 2:
            continue
        text = item[1]
        if isinstance(text, str):
            text = text.strip()
            if text:
                lines.append(text)
    return "\n".join(lines)


def _clean_md(text: str) -> str:
    """清洗 Markdown：统一换行、压缩横向空白并保留段落空行，与 parser 风格一致。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).rstrip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
