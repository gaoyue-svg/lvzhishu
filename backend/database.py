"""异步数据库与 Redis 连接辅助工具。"""

from collections.abc import AsyncGenerator
from pathlib import Path
import re

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.config import settings
from backend.utils.logger import get_logger

logger = get_logger(__name__)

engine = create_async_engine(
    settings.mysql_url,
    pool_size=settings.mysql_pool_size,
    max_overflow=settings.mysql_max_overflow,
    pool_pre_ping=True,
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
redis_client: Redis | None = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """为 FastAPI 依赖注入产出异步数据库会话。"""
    async with AsyncSessionLocal() as session:
        yield session


async def init_redis() -> Redis | None:
    """创建并校验 Redis 连接池。"""
    global redis_client
    # socket_timeout 必须 > Stream XREADGROUP 的 BLOCK 时长（Worker 默认 5000ms），
    # 否则 Redis 服务端仍在 BLOCK 等消息时客户端会先抛 TimeoutError。
    # 这里给 10s 余量，并开启周期性健康检查以便自动重连。
    redis_client = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_timeout=10.0,
        socket_connect_timeout=5.0,
        health_check_interval=30,
    )
    try:
        await redis_client.ping()
        logger.info("Redis 连接就绪")
    except RedisError as exc:
        logger.warning("Redis 不可用: %s", exc.__class__.__name__)
    return redis_client


async def get_redis() -> AsyncGenerator[Redis | None, None]:
    """若共享 Redis 客户端存在则产出，否则产出 None。"""
    yield redis_client


async def close_connections() -> None:
    """关闭异步数据库与 Redis 资源。"""
    global redis_client
    if redis_client is not None:
        await redis_client.aclose()
        redis_client = None
    await engine.dispose()


async def init_database_if_empty() -> None:
    """当数据库无表时创建配置的数据库并执行 sql/init.sql。"""
    await _ensure_database_exists()
    async with engine.begin() as conn:
        table_count = await conn.scalar(
            text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = :database_name"
            ),
            {"database_name": settings.mysql_database},
        )
        if table_count:
            logger.info("数据库已初始化，共有 %s 张表", table_count)
            return

        logger.info("数据库为空，开始执行 sql/init.sql")
        for statement in _load_init_statements():
            await conn.execute(text(statement))


async def _ensure_database_exists() -> None:
    """在连接到指定 schema 引擎之前创建 MySQL 数据库。"""
    bootstrap_engine = create_async_engine(settings.mysql_server_url, pool_pre_ping=True)
    try:
        async with bootstrap_engine.begin() as conn:
            await conn.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS `{settings.mysql_database}` "
                    "DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_unicode_ci"
                )
            )
    finally:
        await bootstrap_engine.dispose()


def _load_init_statements() -> list[str]:
    """加载 sql/init.sql 并拆分为可执行的 SQL 语句。"""
    sql_path = Path(__file__).resolve().parents[1] / "sql" / "init.sql"
    sql_text = sql_path.read_text(encoding="utf-8")
    without_comments = re.sub(r"^\s*--.*$", "", sql_text, flags=re.MULTILINE)
    statements = [statement.strip() for statement in without_comments.split(";")]
    return [statement for statement in statements if statement]
