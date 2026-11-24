"""本文件提供 Agent 会话列表、详情、消息分页、删除和反馈接口。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.conversation import Conversation, Message
from backend.models.user import User
from backend.schemas.response import ApiResponse
from backend.services.auth import get_current_user

router = APIRouter(prefix="/api/conversation", tags=["会话"])


class FeedbackRequest(BaseModel):
    """消息反馈请求体。"""

    feedback: str = Field(pattern="^(like|dislike)$")
    comment: str | None = None


@router.get("/list", response_model=ApiResponse[dict[str, Any]])
async def list_conversations(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ApiResponse[dict[str, Any]]:
    """分页返回当前用户的活跃会话列表。"""
    base = select(Conversation).where(Conversation.user_id == current_user.id, Conversation.status == "active")
    total_result = await db.execute(
        select(func.count()).select_from(Conversation).where(
            Conversation.user_id == current_user.id,
            Conversation.status == "active",
        )
    )
    result = await db.execute(
        base.order_by(desc(Conversation.updated_at)).offset((page - 1) * page_size).limit(page_size)
    )
    items = [_conversation_payload(item) for item in result.scalars().all()]
    return ApiResponse(data={"items": items, "total": int(total_result.scalar_one() or 0)})


@router.get("/{conversation_id}", response_model=ApiResponse[dict[str, Any]])
async def get_conversation(
    conversation_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[dict[str, Any]]:
    """返回会话详情和最近消息。"""
    conversation = await _get_owned_conversation(db, current_user.id, conversation_id)
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(desc(Message.created_at))
        .limit(50)
    )
    messages = [_message_payload(item) for item in reversed(list(result.scalars().all()))]
    return ApiResponse(data={**_conversation_payload(conversation), "messages": messages})


@router.get("/{conversation_id}/messages", response_model=ApiResponse[dict[str, Any]])
async def list_messages(
    conversation_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ApiResponse[dict[str, Any]]:
    """分页返回指定会话的消息历史。"""
    conversation = await _get_owned_conversation(db, current_user.id, conversation_id)
    total_result = await db.execute(
        select(func.count()).select_from(Message).where(Message.conversation_id == conversation.id)
    )
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return ApiResponse(
        data={
            "items": [_message_payload(item) for item in result.scalars().all()],
            "total": int(total_result.scalar_one() or 0),
        }
    )


@router.delete("/{conversation_id}", response_model=ApiResponse[dict[str, str]])
async def delete_conversation(
    conversation_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[dict[str, str]]:
    """软删除会话，保留消息便于审计。"""
    conversation = await _get_owned_conversation(db, current_user.id, conversation_id)
    conversation.status = "archived"
    await db.commit()
    return ApiResponse(data={"status": "archived"})


@router.post("/{conversation_id}/message/{message_id}/feedback", response_model=ApiResponse[dict[str, str]])
async def feedback_message(
    conversation_id: int,
    message_id: int,
    body: FeedbackRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[dict[str, str]]:
    """保存 assistant 消息的点赞或点踩反馈。"""
    conversation = await _get_owned_conversation(db, current_user.id, conversation_id)
    result = await db.execute(
        select(Message).where(Message.id == message_id, Message.conversation_id == conversation.id)
    )
    message = result.scalar_one_or_none()
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="消息不存在")
    message.feedback = body.feedback
    message.feedback_comment = body.comment
    await db.commit()
    return ApiResponse(data={"feedback": body.feedback})


async def _get_owned_conversation(db: AsyncSession, user_id: int, conversation_id: int) -> Conversation:
    """读取当前用户拥有的未归档会话。"""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
            Conversation.status == "active",
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    return conversation


def _conversation_payload(conversation: Conversation) -> dict[str, Any]:
    """把会话 ORM 转成接口字典。"""
    return {
        "id": str(conversation.id),
        "title": conversation.title,
        "agent_type": conversation.agent_type,
        "kb_id": str(conversation.kb_id) if conversation.kb_id is not None else None,
        "summary": conversation.summary,
        "message_count": conversation.message_count,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
    }


def _message_payload(message: Message) -> dict[str, Any]:
    """把消息 ORM 转成接口字典。"""
    return {
        "id": str(message.id),
        "conversation_id": str(message.conversation_id),
        "role": message.role,
        "content": message.content,
        "citations": message.citations,
        "feedback": message.feedback,
        "retrieval_trace_id": message.retrieval_trace_id,
        "created_at": message.created_at,
    }

