"""知识库相关接口:列表、创建、详情、更新与删除。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.user import User
from backend.schemas.kb import CreateKBRequest, KnowledgeBaseResponse, UpdateKBRequest
from backend.schemas.response import ApiResponse
from backend.services.auth import get_current_user
from backend.services import kb as kb_service
from rag_service.retrieval.dependencies import get_milvus
from rag_service.retrieval.milvus_client import MilvusStore

router = APIRouter(prefix="/api/kb", tags=["knowledge-base"])


@router.get("", response_model=ApiResponse[list[KnowledgeBaseResponse]])
async def list_kb(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    kb_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> ApiResponse[list[KnowledgeBaseResponse]]:
    """列出当前用户的知识库。"""
    items = await kb_service.get_user_kbs(db, current_user.id, kb_type, status)
    return ApiResponse(data=items)


@router.post("", response_model=ApiResponse[KnowledgeBaseResponse])
async def create_kb(
    body: CreateKBRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[KnowledgeBaseResponse]:
    """创建知识库。"""
    kb = await kb_service.create_kb(db, current_user.id, body)
    return ApiResponse(data=kb)


@router.get("/{kb_id}", response_model=ApiResponse[KnowledgeBaseResponse])
async def get_kb(
    kb_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[KnowledgeBaseResponse]:
    """获取知识库详情。"""
    kb = await kb_service.get_kb_by_id(db, kb_id, current_user.id)
    return ApiResponse(data=kb)


@router.put("/{kb_id}", response_model=ApiResponse[KnowledgeBaseResponse])
async def update_kb(
    kb_id: int,
    body: UpdateKBRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[KnowledgeBaseResponse]:
    """更新知识库配置。"""
    kb = await kb_service.get_kb_by_id(db, kb_id, current_user.id)
    updated = await kb_service.update_kb(db, kb, body)
    return ApiResponse(data=updated)


@router.delete("/{kb_id}", response_model=ApiResponse[None])
async def delete_kb(
    kb_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    milvus: Annotated[MilvusStore | None, Depends(get_milvus)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[None]:
    """删除知识库,同步清理数据库与 Milvus 向量数据。"""
    kb = await kb_service.get_kb_by_id(db, kb_id, current_user.id)
    await kb_service.delete_kb(db, kb, milvus)
    return ApiResponse(data=None)
