"""知识 Chunk 相关接口:列表与详情。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.knowledge import KnowledgeChunk, KnowledgeDocument
from backend.models.user import User
from backend.schemas.chunk import ChunkDetailResponse, PaginatedChunkResponse
from backend.schemas.response import ApiResponse
from backend.services.auth import get_current_user

router = APIRouter(prefix="/api/chunk", tags=["chunk"])


@router.get("", response_model=ApiResponse[PaginatedChunkResponse])
async def list_chunks(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    document_id: int = Query(...),
    kb_id: int = Query(...),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> ApiResponse[PaginatedChunkResponse]:
    """列出文档的 Chunk。"""
    await _ensure_document_owner(db, document_id, kb_id, current_user.id)
    stmt = select(KnowledgeChunk).where(
        KnowledgeChunk.document_id == document_id,
        KnowledgeChunk.kb_id == kb_id,
    )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(
        stmt.order_by(KnowledgeChunk.chunk_index.asc()).offset((page - 1) * page_size).limit(page_size)
    )
    return ApiResponse(
        data=PaginatedChunkResponse(
            items=list(result.scalars().all()),
            total=int(total or 0),
            page=page,
            page_size=page_size,
        )
    )


@router.get("/{chunk_id}", response_model=ApiResponse[ChunkDetailResponse])
async def get_chunk(
    chunk_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ChunkDetailResponse]:
    """获取单个 Chunk。"""
    result = await db.execute(select(KnowledgeChunk).where(KnowledgeChunk.id == chunk_id))
    chunk = result.scalar_one_or_none()
    if chunk is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chunk 不存在")
    await _ensure_document_owner(db, chunk.document_id, chunk.kb_id, current_user.id)
    return ApiResponse(data=chunk)


async def _ensure_document_owner(
    db: AsyncSession, document_id: int, kb_id: int, user_id: int
) -> None:
    """校验文档归属,确保当前用户拥有该文档所在知识库。"""
    result = await db.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.id == document_id,
            KnowledgeDocument.kb_id == kb_id,
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    if doc.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限访问")
