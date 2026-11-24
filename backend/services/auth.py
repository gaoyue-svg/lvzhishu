"""认证服务工具:密码哈希、JWT 令牌签发与校验、当前用户解析与令牌黑名单。"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt import ExpiredSignatureError, InvalidTokenError
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_db, get_redis
from backend.models.user import User
from backend.utils.logger import get_logger

logger = get_logger(__name__)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def hash_password(password: str) -> str:
    """使用 bcrypt 对明文密码进行哈希。"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """校验明文密码是否与 bcrypt 哈希匹配。"""
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: int) -> str:
    """为用户签发带签名的 JWT 访问令牌。"""
    expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": str(user_id), "exp": expire, "type": "access"}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: int) -> str:
    """为用户签发带签名的 JWT 刷新令牌。"""
    expire = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    payload = {"sub": str(user_id), "exp": expire, "type": "refresh"}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any]:
    """解码并校验 JWT 令牌。"""
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except ExpiredSignatureError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="令牌已过期") from exc
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="令牌无效") from exc


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis | None, Depends(get_redis)],
) -> User:
    """从 Authorization Bearer 令牌解析当前用户。"""
    await ensure_token_not_blacklisted(token, redis)
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="令牌类型无效")

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if user is None or user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不可用")
    return user


async def find_user_by_username_or_email(db: AsyncSession, value: str) -> User | None:
    """按用户名或邮箱查找用户。"""
    result = await db.execute(select(User).where(or_(User.username == value, User.email == value)))
    return result.scalar_one_or_none()


async def ensure_token_not_blacklisted(token: str, redis: Redis | None) -> None:
    """令牌存在于 Redis 黑名单中则拒绝。"""
    if redis is None:
        return
    try:
        if await redis.exists(f"blacklist:{token}"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="令牌已被吊销")
    except RedisError as exc:
        logger.warning("跳过 Redis 黑名单检查: %s", exc.__class__.__name__)


async def blacklist_token(token: str, redis: Redis | None) -> None:
    """将令牌加入 Redis 黑名单,有效期至 JWT 过期。"""
    if redis is None:
        return
    payload = decode_token(token)
    exp = payload.get("exp")
    ttl = max(int(exp - datetime.now(UTC).timestamp()), 1) if exp else 1
    try:
        await redis.setex(f"blacklist:{token}", ttl, "1")
    except RedisError as exc:
        logger.warning("跳过 Redis 黑名单写入: %s", exc.__class__.__name__)
