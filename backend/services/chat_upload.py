"""会话临时上传文件（合同分析）业务逻辑。"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import AsyncSessionLocal
from backend.models.chat_upload import ChatUpload
from backend.services.document import _detect_file_type, _save_upload_to_temp
from backend.services.parser import parse_document_with_metadata
from backend.storage.oss import OSSClient
from backend.utils.logger import get_logger

logger = get_logger(__name__)


async def upload_chat_file(
    db: AsyncSession,
    user_id: int,
    file: UploadFile,
    oss: OSSClient,
    conversation_id: int | None = None,
) -> ChatUpload:
    """校验文件，优先持久化到 OSS，并创建待后台解析的上传记录。

    OSS 未配置时保留本地同步解析作为开发环境降级，避免本地功能完全不可用。
    OSS 已配置时接口只等待对象上传，不再等待耗时的 OCR；解析由后台任务完成。
    """
    filename = Path(file.filename or "").name
    file_type = _detect_file_type(filename)
    tmp_path, file_size, file_hash = await _save_upload_to_temp(file)
    try:
        if file_size > settings.chat_upload_max_bytes:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="文件过大")
        await _purge_expired(db, user_id, oss)

        if _oss_is_configured(oss):
            record = ChatUpload(
                user_id=user_id,
                conversation_id=conversation_id,
                filename=filename,
                file_type=file_type,
                doc_type="contract",
                file_size=file_size,
                file_hash=file_hash,
                oss_bucket=settings.oss_documents_bucket,
                parse_status="pending",
                expires_at=datetime.utcnow() + timedelta(hours=settings.chat_upload_ttl_hours),
            )
            db.add(record)
            await db.flush()
            key = f"chat-upload/{user_id}/{record.id}/{filename}"
            oss_url = oss.build_storage_url(settings.oss_documents_bucket, key)
            if len(oss_url) > 500:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件名过长")
            await oss.upload_file(settings.oss_documents_bucket, key, str(tmp_path))
            record.oss_key = key
            record.oss_url = oss_url
            await db.commit()
            await db.refresh(record)
            return record

        logger.warning("OSS 凭证未配置，会话附件临时使用本地同步解析")
        parsed = await parse_document_with_metadata(str(tmp_path), file_type)
        markdown = (parsed.markdown or "").strip()
        record = ChatUpload(
            user_id=user_id,
            conversation_id=conversation_id,
            filename=filename,
            file_type=file_type,
            doc_type="contract",
            file_size=file_size,
            file_hash=file_hash,
            parse_status="completed" if markdown else "failed",
            parse_warnings=list(parsed.warnings or []),
            raw_markdown=markdown or None,
            expires_at=datetime.utcnow() + timedelta(hours=settings.chat_upload_ttl_hours),
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        return record
    except Exception:
        await db.rollback()
        raise
    finally:
        tmp_path.unlink(missing_ok=True)


async def parse_chat_upload(upload_id: int, oss: OSSClient) -> None:
    """从 OSS 下载会话附件并在响应返回后执行 OCR/文档解析。"""
    tmp_path: Path | None = None
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ChatUpload).where(ChatUpload.id == upload_id))
        record = result.scalar_one_or_none()
        if record is None or record.parse_status not in {"pending", "parsing"}:
            return
        if not record.oss_bucket or not record.oss_key:
            record.parse_status = "failed"
            record.parse_warnings = ["OSS 文件位置缺失，无法解析"]
            await db.commit()
            return

        try:
            record.parse_status = "parsing"
            await db.commit()
            suffix = Path(record.filename).suffix
            fd, temp_name = tempfile.mkstemp(prefix="lawagent-chat-", suffix=suffix)
            os.close(fd)
            tmp_path = Path(temp_name)
            await oss.download_file(record.oss_bucket, record.oss_key, str(tmp_path))
            parsed = await parse_document_with_metadata(str(tmp_path), record.file_type)
            markdown = (parsed.markdown or "").strip()
            record.parse_status = "completed" if markdown else "failed"
            record.parse_warnings = list(parsed.warnings or [])
            record.raw_markdown = markdown or None
            await db.commit()
        except Exception as exc:
            await db.rollback()
            result = await db.execute(select(ChatUpload).where(ChatUpload.id == upload_id))
            failed_record = result.scalar_one_or_none()
            if failed_record is not None:
                failed_record.parse_status = "failed"
                failed_record.parse_warnings = [f"后台解析失败: {exc.__class__.__name__}"]
                await db.commit()
            logger.exception("会话附件后台解析失败 upload_id=%s", upload_id)
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)


async def get_upload(db: AsyncSession, upload_id: int, user_id: int) -> ChatUpload:
    """获取上传记录并校验归属当前用户且未过期。"""
    result = await db.execute(select(ChatUpload).where(ChatUpload.id == upload_id))
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="上传文件不存在或已过期")
    if record.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限访问")
    return record


async def mark_analysis_result(
    db: AsyncSession,
    upload: ChatUpload,
    *,
    report: str,
    summary: str,
    elements: dict[str, Any] | None,
    risks: list[Any] | None,
    status_: str = "completed",
) -> None:
    """分析结束后把最终报告与结构化结果回写上传记录。"""
    upload.analysis_status = status_
    upload.analysis_report = report or None
    upload.analysis_summary = summary or None
    upload.analysis_elements = elements
    upload.analysis_risks = risks
    await db.commit()


async def _purge_expired(db: AsyncSession, user_id: int, oss: OSSClient | None = None) -> None:
    """清理当前用户已过期的临时上传记录（上传时顺带执行）。"""
    now = datetime.utcnow()
    if oss is not None and _oss_is_configured(oss):
        result = await db.execute(
            select(ChatUpload).where(ChatUpload.user_id == user_id, ChatUpload.expires_at < now)
        )
        for record in result.scalars():
            if record.oss_bucket and record.oss_key:
                try:
                    await oss.delete_object(record.oss_bucket, record.oss_key)
                except Exception as exc:
                    logger.warning(
                        "清理过期会话附件 OSS 对象失败 upload_id=%s error=%s",
                        record.id,
                        exc.__class__.__name__,
                    )
    await db.execute(delete(ChatUpload).where(ChatUpload.user_id == user_id, ChatUpload.expires_at < now))


def _oss_is_configured(oss: OSSClient) -> bool:
    """判断 OSS 客户端与会话附件 Bucket 是否具备上传条件。"""
    return bool(
        oss.access_key_id
        and oss.access_key_secret
        and settings.oss_documents_bucket
        and settings.oss_endpoint
    )
