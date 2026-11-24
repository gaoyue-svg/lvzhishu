"""当前用户资料相关接口:获取、更新资料与修改密码。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.user import User
from backend.schemas.auth import (
    PasswordUpdateRequest,
    UserProfileResponse,
    UserProfileUpdateRequest,
)
from backend.schemas.response import ApiResponse
from backend.services.auth import get_current_user, hash_password, verify_password

router = APIRouter(prefix="/api/user", tags=["user"])


@router.get(
    "/profile",
    response_model=ApiResponse[UserProfileResponse],
    summary="获取当前用户资料",
    description="根据 Authorization Bearer 令牌返回当前登录用户的公开资料。",
)
async def get_profile(
    current_user: Annotated[User, Depends(get_current_user)],
) -> ApiResponse[UserProfileResponse]:
    """返回当前用户的资料。"""
    return ApiResponse(data=UserProfileResponse.model_validate(current_user))


@router.put(
    "/profile",
    response_model=ApiResponse[UserProfileResponse],
    summary="更新当前用户资料",
    description="更新当前登录用户的用户名、邮箱或手机号，并检查用户名和邮箱唯一性。",
)
async def update_profile(
    payload: UserProfileUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[UserProfileResponse]:
    """更新当前用户可编辑的资料字段。"""
    if payload.username is not None or payload.email is not None:
        checks = []
        if payload.username is not None:
            checks.append(User.username == payload.username)
        if payload.email is not None:
            checks.append(User.email == payload.email)
        result = await db.execute(
            select(User).where(and_(User.id != current_user.id, or_(*checks)))
        )
        if result.scalar_one_or_none() is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名或邮箱已存在")

    if payload.username is not None:
        current_user.username = payload.username
    if payload.email is not None:
        current_user.email = payload.email
    if payload.phone is not None:
        current_user.phone = payload.phone
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名或邮箱已存在",
        ) from exc
    await db.refresh(current_user)
    return ApiResponse(data=UserProfileResponse.model_validate(current_user))


@router.put(
    "/password",
    response_model=ApiResponse[None],
    summary="修改当前用户密码",
    description="验证旧密码后，将新密码以 bcrypt 哈希写入数据库。",
)
async def update_password(
    payload: PasswordUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[None]:
    """修改当前用户的密码。"""
    if not verify_password(payload.old_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="旧密码不正确")
    current_user.password_hash = hash_password(payload.new_password)
    await db.commit()
    return ApiResponse(data=None)
