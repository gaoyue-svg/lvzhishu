"""认证相关接口:注册、登录、登出。"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_db, get_redis
from backend.models.user import User
from backend.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from backend.schemas.response import ApiResponse
from backend.services.auth import (
    blacklist_token,
    create_access_token,
    create_refresh_token,
    find_user_by_username_or_email,
    get_current_user,
    hash_password,
    oauth2_scheme,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=ApiResponse[TokenResponse],
    summary="注册用户",
    description="检查用户名和邮箱唯一性，创建用户并返回访问令牌与刷新令牌。",
)
async def register(
    payload: RegisterRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[TokenResponse]:
    """注册新用户并签发访问令牌与刷新令牌。"""
    exists_result = await db.execute(
        select(User).where(or_(User.username == payload.username, User.email == payload.email))
    )
    if exists_result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名或邮箱已存在")

    user = User(
        username=payload.username,
        email=payload.email,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名或邮箱已存在",
        ) from exc
    await db.refresh(user)
    return ApiResponse(data=_build_token_response(user.id))


@router.post(
    "/login",
    response_model=ApiResponse[TokenResponse],
    summary="用户登录",
    description="使用用户名或邮箱登录，验证通过后返回访问令牌与刷新令牌。",
)
async def login(
    payload: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[TokenResponse]:
    """校验用户凭据并签发访问令牌与刷新令牌。"""
    user = await find_user_by_username_or_email(db, payload.username)
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    if user.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="用户不可用")

    user.last_login_at = datetime.now(UTC)
    await db.commit()
    return ApiResponse(data=_build_token_response(user.id))


@router.post(
    "/logout",
    response_model=ApiResponse[None],
    summary="用户退出",
    description="将当前访问令牌加入 Redis 黑名单，黑名单有效期与令牌剩余有效期一致。",
)
async def logout(
    token: Annotated[str, Depends(oauth2_scheme)],
    current_user: Annotated[User, Depends(get_current_user)],
    redis: Annotated[Redis | None, Depends(get_redis)],
) -> ApiResponse[None]:
    """在 Redis 可用时将当前 Bearer 令牌加入黑名单。"""
    await blacklist_token(token, redis)
    return ApiResponse(message="success", data=None)


def _build_token_response(user_id: int) -> TokenResponse:
    """根据用户 ID 构造令牌响应。"""
    return TokenResponse(
        access_token=create_access_token(user_id),
        refresh_token=create_refresh_token(user_id),
        expires_in=settings.access_token_expire_minutes * 60,
    )
