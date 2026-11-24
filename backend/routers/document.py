"""本文件提供知识文档上传、列表、详情、删除与重解析接口。"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db, get_redis
from backend.models.task import TaskLog
from backend.models.user import User
from backend.schemas.document import (
    DocumentDetailResponse,
    DocumentMarkdownResponse,
    DocumentUploadResponse,
    PaginatedDocumentResponse,
)
from backend.schemas.response import ApiResponse
from backend.services.auth import get_current_user
from backend.services import document as document_service
from backend.storage.oss import OSSClient, get_oss
from backend.utils.logger import get_logger
from backend.worker.task_queue import DOCUMENT_PARSE_STREAM, TaskQueue
from rag_service.retrieval.dependencies import get_milvus
from rag_service.retrieval.milvus_client import MilvusStore

router = APIRouter(prefix="/api/document", tags=["document"])
logger = get_logger(__name__)


@router.post("/upload", response_model=ApiResponse[DocumentUploadResponse])
async def upload_document(
    current_user: Annotated[User, Depends(get_current_user)],
    oss: Annotated[OSSClient, Depends(get_oss)],
    redis: Annotated[Redis | None, Depends(get_redis)],
    db: Annotated[AsyncSession, Depends(get_db)],
    kb_id: int = Form(...),
    file: UploadFile = File(...),
) -> ApiResponse[DocumentUploadResponse]:
    """上传文档并入队解析任务。"""
    if redis is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Redis 不可用")
    # 先落库再入队：upload_document 内部已 flush 拿到 doc.id 并上传 OSS，
    # 这里先 commit 让文档记录对 Worker 可见，再写入 Redis Stream。
    # 原顺序是"先 enqueue 后 commit"，一旦 commit 失败会留下孤儿消息，
    # Worker 查不到文档就报"文档不存在"，且 MySQL 自增 ID 不回退形成幽灵 ID。
    doc = await document_service.upload_document(db, current_user.id, kb_id, file, oss)
    await db.commit()
    await db.refresh(doc)

    task = {
        "document_id": doc.id,
        "kb_id": kb_id,
        "file_type": doc.file_type,
        "oss_bucket": doc.oss_bucket,
        "oss_key": doc.oss_key,
    }
    # 入队失败时不回滚数据库：文档已落库为 pending，用户可走 reparse 接口安全重试。
    try:
        msg_id = await TaskQueue(redis).enqueue(DOCUMENT_PARSE_STREAM, task)
    except Exception:
        logger.exception("入队解析任务失败 document_id=%s，请通过 reparse 重试", doc.id)
        return ApiResponse(
            data=DocumentUploadResponse(
                document_id=doc.id,
                filename=doc.filename,
                file_size=doc.file_size,
                oss_url=doc.oss_url,
                parse_status=doc.parse_status,
            )
        )

    # TaskLog 仅作审计日志，写入失败不影响解析主流程。
    try:
        db.add(
            TaskLog(
                task_type="document_parse",
                resource_type="knowledge_document",
                resource_id=doc.id,
                user_id=current_user.id,
                status="pending",
                input_params={**task, "stream_msg_id": msg_id},
            )
        )
        await db.commit()
    except Exception:
        await db.rollback()
        logger.warning("写入 TaskLog 失败 document_id=%s", doc.id)

    return ApiResponse(
        data=DocumentUploadResponse(
            document_id=doc.id,
            filename=doc.filename,
            file_size=doc.file_size,
            oss_url=doc.oss_url,
            parse_status=doc.parse_status,
        )
    )


@router.get("", response_model=ApiResponse[PaginatedDocumentResponse])
async def list_documents(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    kb_id: int = Query(...),
    parse_status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ApiResponse[PaginatedDocumentResponse]:
    """列出知识库下的文档。"""
    items, total = await document_service.get_documents(
        db, kb_id, current_user.id, parse_status, page, page_size
    )
    return ApiResponse(
        data=PaginatedDocumentResponse(items=items, total=total, page=page, page_size=page_size)
    )


@router.get("/{document_id}", response_model=ApiResponse[DocumentDetailResponse])
async def get_document(
    document_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[DocumentDetailResponse]:
    """获取文档详情。"""
    doc = await document_service.get_document_by_id(db, document_id, current_user.id)
    return ApiResponse(data=doc)


@router.get("/{document_id}/markdown", response_model=ApiResponse[DocumentMarkdownResponse])
async def get_document_markdown(
    document_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[DocumentMarkdownResponse]:
    """获取文档解析后的 Markdown 原文。"""
    doc = await document_service.get_document_by_id(db, document_id, current_user.id)
    return ApiResponse(
        data=DocumentMarkdownResponse(
            document_id=doc.id,
            filename=doc.filename,
            raw_markdown=doc.raw_markdown,
        )
    )


@router.delete("/{document_id}", response_model=ApiResponse[None])
async def delete_document(
    document_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    oss: Annotated[OSSClient, Depends(get_oss)],
    milvus: Annotated[MilvusStore | None, Depends(get_milvus)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[None]:
    """删除文档及其 Chunk。"""
    doc = await document_service.get_document_by_id(db, document_id, current_user.id)
    await document_service.delete_document(db, doc, oss, milvus)
    return ApiResponse(data=None)


@router.post("/{document_id}/reparse", response_model=ApiResponse[None])
async def reparse_document(
    document_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    redis: Annotated[Redis | None, Depends(get_redis)],
    milvus: Annotated[MilvusStore | None, Depends(get_milvus)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[None]:
    """重置文档状态并重新入队解析。"""
    if redis is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Redis 不可用")
    doc = await document_service.get_document_by_id(db, document_id, current_user.id)
    if doc.parse_status == "parsing":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="文档正在解析中")
    await document_service.reset_for_reparse(db, doc, milvus)
    # 先提交向量/Chunk 清理，再入队；入队失败时用户可安全重试，不会留下假 vector_id。
    await db.commit()
    task = {
        "document_id": doc.id,
        "kb_id": doc.kb_id,
        "file_type": doc.file_type,
        "oss_bucket": doc.oss_bucket,
        "oss_key": doc.oss_key,
    }
    msg_id = await TaskQueue(redis).enqueue(DOCUMENT_PARSE_STREAM, task)
    db.add(
        TaskLog(
            task_type="document_parse",
            resource_type="knowledge_document",
            resource_id=doc.id,
            user_id=current_user.id,
            status="pending",
            input_params={**task, "stream_msg_id": msg_id},
        )
    )
    await db.commit()
    return ApiResponse(data=None)
