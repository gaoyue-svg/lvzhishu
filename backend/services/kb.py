"""知识库业务逻辑:创建、查询、更新与删除。"""

import asyncio

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.knowledge import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from backend.models.task import TaskLog
from backend.schemas.kb import CreateKBRequest, UpdateKBRequest
from backend.utils.logger import get_logger
from rag_service.retrieval.milvus_client import MilvusStore

logger = get_logger(__name__)


async def create_kb(db: AsyncSession, user_id: int, data: CreateKBRequest) -> KnowledgeBase:
    """为用户创建知识库。"""
    kb = KnowledgeBase(
        user_id=user_id,
        name=data.name,
        description=data.description,
        kb_type=data.kb_type,
        embedding_model=data.embedding_model,
        chunk_size=data.chunk_size,
        chunk_overlap=data.chunk_overlap,
    )
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return kb


async def get_user_kbs(
    db: AsyncSession, user_id: int, kb_type: str | None = None, status_: str | None = None
) -> list[KnowledgeBase]:
    """列出某用户拥有的知识库。"""
    stmt = select(KnowledgeBase).where(KnowledgeBase.user_id == user_id)
    if kb_type:
        stmt = stmt.where(KnowledgeBase.kb_type == kb_type)
    if status_:
        stmt = stmt.where(KnowledgeBase.status == status_)
    stmt = stmt.order_by(KnowledgeBase.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_kb_by_id(db: AsyncSession, kb_id: int, user_id: int) -> KnowledgeBase:
    """获取知识库并校验归属当前用户。"""
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    kb = result.scalar_one_or_none()
    if kb is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")
    if kb.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限访问")
    return kb


async def update_kb(db: AsyncSession, kb: KnowledgeBase, data: UpdateKBRequest) -> KnowledgeBase:
    """更新知识库可修改的字段。"""
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(kb, field, value)
    await db.commit()
    await db.refresh(kb)
    return kb


async def delete_kb(db: AsyncSession, kb: KnowledgeBase, milvus: MilvusStore | None = None) -> None:
    """在没有文档处于解析中时删除知识库,并清理 Milvus 向量数据。"""
    active_count = await db.scalar(
        select(func.count())
        .select_from(KnowledgeDocument)
        .where(
            KnowledgeDocument.kb_id == kb.id,
            KnowledgeDocument.parse_status.in_(("pending", "parsing")),
        )
    )
    if active_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="知识库存在正在处理的文档",
        )
    # 先清理 Milvus 向量,必须在数据库删除 Chunk 之前查 chunk_id,否则丢失对应关系。
    # 向量删除失败只记录告警,不阻塞数据库删除(与文档删除策略一致)。
    if milvus is not None:
        chunk_id_rows = await db.execute(
            select(KnowledgeChunk.id).where(KnowledgeChunk.kb_id == kb.id)
        )
        chunk_ids = [str(item) for item in chunk_id_rows.scalars().all()]
        if chunk_ids:
            try:
                await asyncio.to_thread(milvus.delete_by_chunk_ids, chunk_ids)
            except Exception as exc:
                logger.warning("知识库 %s 的 Milvus 向量删除失败: %s", kb.id, exc)
    result = await db.execute(
        select(KnowledgeDocument.oss_bucket, KnowledgeDocument.oss_key).where(
            KnowledgeDocument.kb_id == kb.id
        )
    )
    objects = [{"bucket": bucket, "key": key} for bucket, key in result.all()]
    if objects:
        db.add(
            TaskLog(
                task_type="oss_cleanup",
                resource_type="knowledge_base",
                resource_id=kb.id,
                user_id=kb.user_id,
                status="pending",
                input_params={"objects": objects},
            )
        )
    # 显式删除 Chunk 与文档,不依赖外键级联,避免外键约束缺失时产生孤儿数据。
    # 删除顺序:先 Chunk(依赖 document/kb),再 document(依赖 kb),最后 kb。
    await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.kb_id == kb.id))
    await db.execute(delete(KnowledgeDocument).where(KnowledgeDocument.kb_id == kb.id))
    await db.execute(delete(KnowledgeBase).where(KnowledgeBase.id == kb.id))
    await db.commit()
