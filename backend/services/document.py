"""本文件实现知识文档上传、查询、删除与重解析业务逻辑。"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from uuid import uuid4

import aiofiles
from fastapi import HTTPException, UploadFile, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.models.knowledge import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from backend.storage.oss import OSSClient
from backend.utils.logger import get_logger
from embedding_service.services.embedding import delete_document_vectors
from rag_service.retrieval.milvus_client import MilvusStore

ALLOWED_FILE_TYPES = {"pdf", "docx", "txt", "html", "jpg", "jpeg", "png", "bmp", "tiff", "tif", "webp"}
# 图片后缀统一归为 image 类型，交由 parser 的 OCR 链路处理
_IMAGE_SUFFIXES = {"jpg", "jpeg", "png", "bmp", "tiff", "tif", "webp"}
logger = get_logger(__name__)


async def upload_document(
    db: AsyncSession, user_id: int, kb_id: int, file: UploadFile, oss: OSSClient
) -> KnowledgeDocument:
    """校验文件、计算哈希、上传 OSS 并创建 pending 文档记录。"""
    kb = await _get_owned_kb(db, kb_id, user_id)
    filename = Path(file.filename or "").name
    file_type = _detect_file_type(filename)

    tmp_path, file_size, file_hash = await _save_upload_to_temp(file)
    try:
        if file_size > settings.knowledge_upload_max_bytes:
            limit_mb = settings.knowledge_upload_max_bytes // (1024 * 1024)
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"文件超过知识库单文件上限（{limit_mb} MB）",
            )
        await _ensure_not_duplicate(db, kb_id, file_hash)

        doc = KnowledgeDocument(
            kb_id=kb_id,
            user_id=user_id,
            filename=filename,
            file_type=file_type,
            file_size=file_size,
            file_hash=file_hash,
            oss_bucket=settings.oss_documents_bucket,
            oss_key=f"pending/{uuid4().hex}/{filename}",
            oss_url="pending",
            parse_status="pending",
            embedding_status="pending",
        )
        db.add(doc)
        await db.flush()

        key = f"{user_id}/{kb_id}/{doc.id}/{filename}"
        oss_url = oss.build_storage_url(settings.oss_documents_bucket, key)
        if len(oss_url) > 500:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件名过长")
        await oss.upload_file(settings.oss_documents_bucket, key, str(tmp_path))
        doc.oss_key = key
        doc.oss_url = oss_url
        kb.doc_count = (kb.doc_count or 0) + 1
        kb.total_size = (kb.total_size or 0) + file_size
        return doc
    except Exception:
        await db.rollback()
        raise
    finally:
        tmp_path.unlink(missing_ok=True)


async def get_documents(
    db: AsyncSession,
    kb_id: int,
    user_id: int,
    parse_status: str | None,
    page: int,
    page_size: int,
) -> tuple[list[KnowledgeDocument], int]:
    """分页返回某用户所属知识库下的文档。"""
    await _get_owned_kb(db, kb_id, user_id)
    stmt = select(KnowledgeDocument).where(KnowledgeDocument.kb_id == kb_id)
    if parse_status:
        stmt = stmt.where(KnowledgeDocument.parse_status == parse_status)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(
        stmt.order_by(KnowledgeDocument.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    return list(result.scalars().all()), int(total or 0)


async def get_document_by_id(db: AsyncSession, document_id: int, user_id: int) -> KnowledgeDocument:
    """获取文档并校验归属当前用户。"""
    result = await db.execute(select(KnowledgeDocument).where(KnowledgeDocument.id == document_id))
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    if doc.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限访问")
    return doc


async def delete_document(
    db: AsyncSession,
    doc: KnowledgeDocument,
    oss: OSSClient,
    milvus: MilvusStore | None = None,
) -> None:
    """删除文档及其 Chunk,并更新知识库计数。"""
    kb = await db.get(KnowledgeBase, doc.kb_id)
    try:
        await delete_document_vectors(milvus, db, doc.id)
    except Exception as exc:
        # 文档删除仍以数据库为主事务，外部向量库故障只记录告警。
        logger.warning("文档 %s 的 Milvus 向量删除失败: %s", doc.id, exc)
    await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id))
    await db.execute(delete(KnowledgeDocument).where(KnowledgeDocument.id == doc.id))
    if kb is not None:
        kb.doc_count = max((kb.doc_count or 0) - 1, 0)
        kb.chunk_count = max((kb.chunk_count or 0) - (doc.chunk_count or 0), 0)
        kb.total_size = max((kb.total_size or 0) - (doc.file_size or 0), 0)
    await db.commit()
    try:
        await oss.delete_object(doc.oss_bucket, doc.oss_key)
    except Exception as exc:
        logger.warning("OSS 删除失败: %s: %s", doc.oss_key, exc)


async def reset_for_reparse(
    db: AsyncSession, doc: KnowledgeDocument, milvus: MilvusStore | None = None
) -> None:
    """删除旧 Chunk 并将文档重置为 pending 状态。"""
    kb = await db.get(KnowledgeBase, doc.kb_id)
    old_chunk_count = doc.chunk_count or 0
    try:
        await delete_document_vectors(milvus, db, doc.id)
    except Exception as exc:
        logger.warning("文档 %s 的 Milvus 向量重置失败: %s", doc.id, exc)
    await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id))
    doc.parse_status = "pending"
    doc.embedding_status = "pending"
    doc.embedding_count = 0
    doc.embedding_failed_count = 0
    doc.error_message = None
    doc.chunk_count = 0
    doc.raw_markdown = None
    if kb is not None:
        kb.chunk_count = max((kb.chunk_count or 0) - old_chunk_count, 0)


async def _get_owned_kb(db: AsyncSession, kb_id: int, user_id: int) -> KnowledgeBase:
    """获取知识库并校验归属当前用户。"""
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    kb = result.scalar_one_or_none()
    if kb is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")
    if kb.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限访问")
    return kb


def _detect_file_type(filename: str) -> str:
    """根据文件名后缀识别文件类型,校验是否在允许范围内;图片统一归为 image 类型。"""
    suffix = Path(filename).suffix.lower().lstrip(".")
    if suffix not in ALLOWED_FILE_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不支持的文件类型")
    # 图片后缀统一映射为 image，与 parser 的 OCR 分支对应
    if suffix in _IMAGE_SUFFIXES:
        return "image"
    return suffix


async def _ensure_not_duplicate(db: AsyncSession, kb_id: int, file_hash: str) -> None:
    """根据文件哈希校验同一知识库下是否已存在相同文件。"""
    result = await db.execute(
        select(KnowledgeDocument.id).where(
            KnowledgeDocument.kb_id == kb_id,
            KnowledgeDocument.file_hash == file_hash,
        )
    )
    if result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="文档已存在")


async def _save_upload_to_temp(file: UploadFile) -> tuple[Path, int, str]:
    """将上传文件写入临时文件,返回临时路径、文件大小与 SHA256 哈希。"""
    digest = hashlib.sha256()
    size = 0
    suffix = Path(file.filename or "").suffix
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp_path = Path(handle.name)
    handle.close()
    async with aiofiles.open(tmp_path, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > settings.knowledge_upload_max_bytes:
                break
            digest.update(chunk)
            await out.write(chunk)
    await file.close()
    return tmp_path, size, digest.hexdigest()
