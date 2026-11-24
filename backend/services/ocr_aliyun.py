"""本文件封装阿里云文字识别 OCR（通用文字识别），用于图片与扫描件识别。

优先走阿里云 OCR（按量计费、中文合同版面识别更稳定），失败自动降级本地 RapidOCR。
未配置密钥（aliyun_ocr_enabled=false 或 AccessKey 为空）时，所有入口直接返回空串，不影响上层降级。

SDK：alibabacloud_ocr_api20210707（接入点 ocr-api.{region}.aliyuncs.com）。
识别结果按行拼成纯文本；PDF 用 PyMuPDF 逐页渲染后逐页识别，带 <!-- page:N --> 页码标记。
"""

from __future__ import annotations

import io
import json
import logging
from typing import Any

from backend.config import settings

logger = logging.getLogger(__name__)


def ocr_image_aliyun(image_path: str) -> str:
    """对单张图片执行阿里云通用文字识别，返回按行拼接的文本；失败返回空串。"""
    if not _enabled():
        return ""
    try:
        with open(image_path, "rb") as f:
            image_bytes = f.read()
        return _recognize_general(image_bytes)
    except Exception as exc:  # noqa: BLE001
        logger.warning("阿里云 OCR 图片识别失败，降级本地 RapidOCR: %s", exc)
        return ""


def ocr_pdf_aliyun(pdf_path: str) -> str:
    """把 PDF 逐页渲染为 PNG 后调用阿里云 OCR，返回带页码标记的 Markdown；失败返回空串。"""
    if not _enabled():
        return ""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.warning("PyMuPDF 未安装，无法执行阿里云 PDF OCR")
        return ""

    pages_markdown: list[str] = []
    try:
        document = fitz.open(pdf_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("PyMuPDF 打开 PDF 失败: %s", exc)
        return ""
    try:
        total = len(document)
        if total <= 0:
            return ""
        for page_number in range(min(total, settings.aliyun_ocr_max_pages)):
            page = document[page_number]
            pix = page.get_pixmap(dpi=200)
            text = _recognize_general(pix.tobytes("png"))
            if text.strip():
                pages_markdown.append(f"<!-- page:{page_number + 1} -->\n\n{text}")
    finally:
        document.close()
    return "\n\n".join(pages_markdown)


def _recognize_general(image_bytes: bytes) -> str:
    """对图片字节执行阿里云通用文字识别并解析出按行文本。"""
    from alibabacloud_ocr_api20210707 import models as ocr_models
    from alibabacloud_ocr_api20210707.client import Client
    from alibabacloud_tea_openapi import models as open_api_models
    from alibabacloud_tea_util.models import RuntimeOptions

    config = open_api_models.Config(
        access_key_id=settings.aliyun_ocr_access_key_id,
        access_key_secret=settings.aliyun_ocr_access_key_secret,
        endpoint=f"ocr-api.{settings.aliyun_ocr_region}.aliyuncs.com",
    )
    client = Client(config)
    request = ocr_models.RecognizeGeneralRequest()
    request.body = image_bytes
    response = client.recognize_general_with_options(request, RuntimeOptions())
    data = response.body.data
    return _parse_ocr_data(data)


def _parse_ocr_data(data: Any) -> str:
    """兼容不同 SDK 版本返回的数据形状，统一提取按行文本。

    常见形状：
    - dict：{ "prism_wordsInfo": [{"word": "..."}, ...] }
    - str：OCR 服务端返回的 JSON 字符串
    - list：元素为 {word/Text/text: "..."} 的行列表
    """
    if data is None:
        return ""
    if isinstance(data, str):
        stripped = data.strip()
        if not stripped:
            return ""
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            # 纯文本直接返回
            return stripped
    if isinstance(data, dict):
        words = data.get("prism_wordsInfo") or data.get("words") or data.get("prism_words") or []
        lines = [_word_text(item) for item in words if isinstance(item, dict)]
        if lines:
            return _join_lines(lines)
        return str(data.get("text") or "")
    if isinstance(data, list):
        lines = [_word_text(item) if isinstance(item, dict) else str(item) for item in data if item]
        return _join_lines(lines)
    return ""


def _word_text(item: dict[str, Any]) -> str:
    """从单条识别结果中提取文本字段。"""
    return str(item.get("word") or item.get("Text") or item.get("text") or "").strip()


def _join_lines(lines: list[str]) -> str:
    """合并识别行，过滤空行。"""
    return "\n".join(line for line in lines if line)


def _enabled() -> bool:
    """是否启用且已配置密钥。"""
    return bool(
        settings.aliyun_ocr_enabled
        and settings.aliyun_ocr_access_key_id
        and settings.aliyun_ocr_access_key_secret
    )
