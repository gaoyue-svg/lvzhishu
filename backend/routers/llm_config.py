"""本文件提供用户模型动态配置的 CRUD 与连通性测试接口。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.knowledge import KnowledgeBase, KnowledgeDocument
from backend.models.llm_config import UserLlmConfig
from backend.models.user import User
from backend.schemas.llm_config import (
    LlmConfigResponse,
    ModelConfigType,
    ProviderInfo,
    RuntimeModelConfigResponse,
    SaveLlmConfigRequest,
    TestLlmConfigRequest,
    TestLlmConfigResponse,
)
from backend.schemas.response import ApiResponse
from backend.services import llm_config as svc
from backend.services.auth import get_current_user
from backend.services.model_runtime import resolve_model_runtime
from backend.utils import crypto
from rag_service.retrieval.dependencies import get_milvus
from rag_service.retrieval.milvus_client import MilvusStore

router = APIRouter(prefix="/api/llm", tags=["模型配置"])


def _to_response(config: UserLlmConfig) -> LlmConfigResponse:
    """把 ORM 对象转换为脱敏响应，api_key 不返回明文。"""
    decrypted_key = crypto.decrypt(config.api_key_encrypted) if config.api_key_encrypted else ""
    return LlmConfigResponse(
        id=config.id,
        config_type=config.config_type,
        provider=config.provider,
        model_name=config.model_name,
        api_base=config.api_base,
        api_key_masked=crypto.mask(decrypted_key) if decrypted_key else "",
        has_api_key=bool(decrypted_key),
        is_active=bool(config.is_active),
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        timeout=config.timeout,
        retry=config.retry,
        dimension=config.dimension,
    )


@router.get("/config", response_model=ApiResponse[LlmConfigResponse])
async def get_my_config(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[LlmConfigResponse | None]:
    """兼容旧接口：获取当前用户 chat 大模型配置。"""
    config = await svc.get_config(db, current_user.id, "chat")
    return ApiResponse(data=_to_response(config) if config else None)


@router.put("/config", response_model=ApiResponse[LlmConfigResponse])
async def save_my_config(
    body: SaveLlmConfigRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[LlmConfigResponse]:
    """兼容旧接口：保存或更新当前用户 chat 大模型配置。"""
    body.config_type = "chat"
    config = await svc.save_config(db, current_user.id, body)
    return ApiResponse(data=_to_response(config))


@router.delete("/config", response_model=ApiResponse[None])
async def delete_my_config(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[None]:
    """兼容旧接口：删除当前用户 chat 大模型配置。"""
    await svc.delete_config(db, current_user.id, "chat")
    return ApiResponse(data=None)


@router.get("/configs", response_model=ApiResponse[list[LlmConfigResponse]])
async def list_my_configs(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[LlmConfigResponse]]:
    """获取当前用户全部模型配置。"""
    configs = await svc.list_configs(db, current_user.id)
    return ApiResponse(data=[_to_response(config) for config in configs])


@router.get("/config/{config_type}", response_model=ApiResponse[LlmConfigResponse])
async def get_my_typed_config(
    config_type: ModelConfigType,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[LlmConfigResponse | None]:
    """获取当前用户指定类型模型配置。"""
    config = await svc.get_config(db, current_user.id, config_type)
    return ApiResponse(data=_to_response(config) if config else None)


@router.put("/config/{config_type}", response_model=ApiResponse[LlmConfigResponse])
async def save_my_typed_config(
    config_type: ModelConfigType,
    body: SaveLlmConfigRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    milvus: Annotated[MilvusStore | None, Depends(get_milvus)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[LlmConfigResponse]:
    """保存或更新当前用户指定类型模型配置。"""
    body.config_type = config_type
    config = await svc.save_config(db, current_user.id, body, milvus)
    return ApiResponse(data=_to_response(config))


@router.delete("/config/{config_type}", response_model=ApiResponse[None])
async def delete_my_typed_config(
    config_type: ModelConfigType,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[None]:
    """删除当前用户指定类型模型配置。"""
    await svc.delete_config(db, current_user.id, config_type)
    return ApiResponse(data=None)


@router.get("/providers", response_model=ApiResponse[list[ProviderInfo]])
async def list_providers(
    current_user: Annotated[User, Depends(get_current_user)],
) -> ApiResponse[list[ProviderInfo]]:
    """返回内置 provider 列表，供前端下拉选择。"""
    _ = current_user
    data = [ProviderInfo(**item) for item in svc.BUILTIN_PROVIDERS]
    return ApiResponse(data=data)


@router.get("/runtime/{config_type}", response_model=ApiResponse[RuntimeModelConfigResponse])
async def get_runtime_config(
    config_type: ModelConfigType,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    document_id: int | None = Query(default=None),
    kb_id: int | None = Query(default=None),
) -> ApiResponse[RuntimeModelConfigResponse]:
    """诊断当前用户、知识库或文档最终会使用的模型运行时配置。"""
    document = await _get_owned_document_or_none(db, document_id, current_user.id)
    kb = await _get_owned_kb_or_none(db, kb_id, current_user.id)
    if document is not None:
        kb = await _get_owned_kb_or_none(db, document.kb_id, current_user.id)
    resolution = await resolve_model_runtime(
        db,
        current_user.id,
        config_type,
        document=document,
        kb=kb,
    )
    return ApiResponse(data=RuntimeModelConfigResponse(**resolution.to_public_dict()))


@router.post("/test", response_model=ApiResponse[TestLlmConfigResponse])
async def test_my_config(
    body: TestLlmConfigRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    milvus: Annotated[MilvusStore | None, Depends(get_milvus)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[TestLlmConfigResponse]:
    """测试模型配置连通性，可测已保存配置或临时传入参数。"""
    result = await svc.test_config(
        db,
        current_user.id,
        body.provider,
        body.model_name,
        body.api_base,
        body.api_key,
        config_type=body.config_type,
        dimension=body.dimension,
        milvus=milvus,
    )
    return ApiResponse(
        data=TestLlmConfigResponse(
            success=result["success"], message=result["message"], latency_ms=result["latency_ms"]
        )
    )


async def _get_owned_document_or_none(
    db: AsyncSession, document_id: int | None, user_id: int
) -> KnowledgeDocument | None:
    """读取文档并校验归属;未传 document_id 时返回 None。"""
    if document_id is None:
        return None
    document = await db.get(KnowledgeDocument, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    if document.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限访问")
    return document


async def _get_owned_kb_or_none(
    db: AsyncSession, kb_id: int | None, user_id: int
) -> KnowledgeBase | None:
    """读取知识库并校验归属;未传 kb_id 时返回 None。"""
    if kb_id is None:
        return None
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")
    if kb.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限访问")
    return kb
