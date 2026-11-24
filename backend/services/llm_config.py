"""本文件实现用户模型动态配置的 CRUD、加解密、运行时解析和连通性测试。"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_service.llm.factory import LLMFactory
from agent_service.llm.registry import invalidate
from backend.config import settings
from backend.models.llm_config import UserLlmConfig
from backend.schemas.llm_config import ModelConfigType, SaveLlmConfigRequest
from backend.utils import crypto
from backend.utils.logger import get_logger
from embedding_service.embedding.embedding import EmbeddingFactory
from rag_service.retrieval.milvus_client import MilvusStore

logger = get_logger(__name__)

CONFIG_TYPES: tuple[ModelConfigType, ...] = ("chat", "embedding", "rerank", "tavily")

# 内置 provider 元信息用于前端选项、默认 api_base 和基础校验。
BUILTIN_PROVIDERS: list[dict[str, Any]] = [
    {
        "name": "deepseek",
        "label": "DeepSeek",
        "config_types": ["chat"],
        "default_api_base": "https://api.deepseek.com/v1",
        "popular_models": ["deepseek-chat", "deepseek-reasoner"],
        "requires_api_key": True,
    },
    {
        "name": "openai",
        "label": "OpenAI",
        "config_types": ["chat", "embedding"],
        "default_api_base": "",
        "popular_models": ["gpt-4o-mini", "gpt-4o", "text-embedding-3-small", "text-embedding-3-large"],
        "default_dimension": 1536,
        "requires_api_key": True,
    },
    {
        "name": "qwen",
        "label": "通义千问",
        "config_types": ["chat", "embedding", "rerank"],
        "default_api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "popular_models": ["qwen-plus", "qwen-max", "text-embedding-v4", "gte-rerank-v2"],
        "default_dimension": 1024,
        "requires_api_key": True,
    },
    {
        "name": "bge",
        "label": "BGE/TEI",
        "config_types": ["embedding", "rerank"],
        "default_api_base": "http://127.0.0.1:8080",
        "popular_models": ["bge-large-zh-v1.5", "bge-m3", "bge-reranker-v2-m3"],
        "default_dimension": 1024,
        "requires_api_key": False,
    },
    {
        "name": "rule",
        "label": "规则重排",
        "config_types": ["rerank"],
        "default_api_base": "",
        "popular_models": ["law-rule-reranker"],
        "requires_api_key": False,
    },
    {
        "name": "custom",
        "label": "自定义兼容服务",
        "config_types": ["chat", "embedding", "rerank"],
        "default_api_base": "",
        "popular_models": [],
        "requires_api_key": False,
    },
    {
        "name": "tavily",
        "label": "Tavily 联网搜索",
        "config_types": ["tavily"],
        "default_api_base": "https://api.tavily.com",
        "popular_models": ["tavily-search"],
        "requires_api_key": True,
    },
]


@dataclass(frozen=True)
class RuntimeModelConfig:
    """运行时已经解密并归一化后的模型配置。"""

    config_type: ModelConfigType
    provider: str
    model_name: str
    api_base: str
    api_key: str
    temperature: float | None = None
    max_tokens: int | None = None
    timeout: int | None = None
    retry: int | None = None
    dimension: int | None = None


def provider_requires_api_key(provider: str, config_type: ModelConfigType) -> bool:
    """判断 provider 在指定配置类型下是否必须提供 API Key。"""
    info = _provider_info(provider, config_type)
    return bool(info.get("requires_api_key", True)) if info else True


async def get_config(
    db: AsyncSession, user_id: int, config_type: ModelConfigType = "chat"
) -> UserLlmConfig | None:
    """查询当前用户某一类模型配置，不存在返回 None。"""
    result = await db.execute(
        select(UserLlmConfig).where(
            UserLlmConfig.user_id == user_id,
            UserLlmConfig.config_type == config_type,
        )
    )
    return result.scalar_one_or_none()


async def list_configs(db: AsyncSession, user_id: int) -> list[UserLlmConfig]:
    """查询当前用户全部模型配置，按固定类型顺序返回。"""
    result = await db.execute(select(UserLlmConfig).where(UserLlmConfig.user_id == user_id))
    configs = list(result.scalars().all())
    order = {name: index for index, name in enumerate(CONFIG_TYPES)}
    return sorted(configs, key=lambda item: order.get(item.config_type, 99))


async def get_active_config(
    db: AsyncSession, user_id: int, config_type: ModelConfigType = "chat"
) -> UserLlmConfig | None:
    """查询已启用的指定类型模型配置，未配置或未启用返回 None。"""
    result = await db.execute(
        select(UserLlmConfig).where(
            UserLlmConfig.user_id == user_id,
            UserLlmConfig.config_type == config_type,
            UserLlmConfig.is_active == 1,
        )
    )
    return result.scalar_one_or_none()


async def save_config(
    db: AsyncSession,
    user_id: int,
    data: SaveLlmConfigRequest,
    milvus: MilvusStore | None = None,
) -> UserLlmConfig:
    """保存或更新用户模型配置；api_key 为空时沿用旧密钥。"""
    _validate_provider(data.provider, data.config_type)
    dimension = _resolve_dimension(data)
    if data.config_type == "embedding":
        _validate_embedding_dimension(dimension, milvus)

    config = await get_config(db, user_id, data.config_type)
    encrypted_key = _resolve_encrypted_key(data, config)
    if config is None:
        config = UserLlmConfig(user_id=user_id, config_type=data.config_type)
        db.add(config)

    config.provider = data.provider
    config.model_name = data.model_name
    config.api_base = data.api_base
    config.api_key_encrypted = encrypted_key
    config.is_active = 1 if data.is_active else 0
    config.temperature = data.temperature if data.config_type == "chat" else None
    config.max_tokens = data.max_tokens if data.config_type == "chat" else None
    config.timeout = data.timeout
    config.retry = data.retry
    config.dimension = dimension if data.config_type == "embedding" else None

    await db.commit()
    await db.refresh(config)
    invalidate(config.id)
    logger.info(
        "用户 %s 模型配置已保存: type=%s provider=%s model=%s",
        user_id,
        data.config_type,
        data.provider,
        data.model_name,
    )
    return config


async def delete_config(
    db: AsyncSession, user_id: int, config_type: ModelConfigType = "chat"
) -> None:
    """删除用户指定类型模型配置，系统将回退到全局兜底配置。"""
    config = await get_config(db, user_id, config_type)
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模型配置不存在")
    invalidate(config.id)
    await db.delete(config)
    await db.commit()
    logger.info("用户 %s 模型配置已删除: type=%s", user_id, config_type)


async def resolve_runtime_config(
    db: AsyncSession,
    user_id: int,
    config_type: ModelConfigType,
) -> RuntimeModelConfig | None:
    """优先读取用户动态配置；没有配置时根据系统开关回退到 `.env` 兜底值。"""
    if settings.byok_enabled:
        config = await get_active_config(db, user_id, config_type)
        if config is not None:
            return RuntimeModelConfig(
                config_type=config_type,
                provider=config.provider,
                model_name=config.model_name,
                api_base=config.api_base,
                api_key=crypto.decrypt(config.api_key_encrypted) if config.api_key_encrypted else "",
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                timeout=config.timeout,
                retry=config.retry,
                dimension=config.dimension,
            )
    if not settings.byok_fallback_to_global:
        return None
    return _global_runtime_config(config_type)


async def test_config(
    db: AsyncSession,
    user_id: int,
    provider: str | None,
    model_name: str | None,
    api_base: str | None,
    api_key: str | None,
    config_type: ModelConfigType = "chat",
    dimension: int | None = None,
    milvus: MilvusStore | None = None,
) -> dict[str, Any]:
    """测试模型配置连通性；传明文参数时测试临时配置，不传时测试已保存配置。"""
    runtime_or_error = await _resolve_test_runtime(
        db, user_id, provider, model_name, api_base, api_key, config_type, dimension
    )
    if isinstance(runtime_or_error, dict):
        return runtime_or_error
    runtime = runtime_or_error

    if config_type == "chat":
        return await _test_chat(runtime)
    if config_type == "embedding":
        return await _test_embedding(runtime, milvus)
    if config_type == "tavily":
        return await _test_tavily(runtime)
    return await _test_rerank(runtime)


async def _resolve_test_runtime(
    db: AsyncSession,
    user_id: int,
    provider: str | None,
    model_name: str | None,
    api_base: str | None,
    api_key: str | None,
    config_type: ModelConfigType,
    dimension: int | None = None,
) -> RuntimeModelConfig | dict[str, Any]:
    """合并当前表单参数和已保存密钥,得到测试用运行时配置。"""
    # 完全显式传参（provider + model + api_key 齐全）：直接测临时配置，不查库；
    # 其余设置走默认，_test_* 只用 provider/model/api_base/api_key/dimension。
    if provider and model_name and (api_key or "").strip():
        _validate_provider(provider, config_type)
        return RuntimeModelConfig(
            config_type=config_type,
            provider=provider,
            model_name=model_name,
            api_base=api_base or "",
            api_key=(api_key or "").strip(),
            temperature=None,
            max_tokens=None,
            timeout=None,
            retry=None,
            dimension=(dimension or settings.embedding_dim) if config_type == "embedding" else dimension,
        )

    saved = await get_active_config(db, user_id, config_type)
    if provider and model_name:
        _validate_provider(provider, config_type)
        saved_key = ""
        if saved is not None and saved.provider == provider and saved.api_key_encrypted:
            saved_key = crypto.decrypt(saved.api_key_encrypted)
        effective_key = (api_key or "").strip() or saved_key
        if provider_requires_api_key(provider, config_type) and not effective_key:
            return {"success": False, "message": "请填写 API Key", "latency_ms": 0}
        return RuntimeModelConfig(
            config_type=config_type,
            provider=provider,
            model_name=model_name,
            api_base=api_base or "",
            api_key=effective_key,
            temperature=saved.temperature if saved and config_type == "chat" else None,
            max_tokens=saved.max_tokens if saved and config_type == "chat" else None,
            timeout=saved.timeout if saved else None,
            retry=saved.retry if saved else None,
            dimension=(dimension or settings.embedding_dim) if config_type == "embedding" else dimension,
        )
    if saved is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先保存并启用模型配置")
    return RuntimeModelConfig(
        config_type=config_type,
        provider=saved.provider,
        model_name=saved.model_name,
        api_base=saved.api_base,
        api_key=crypto.decrypt(saved.api_key_encrypted) if saved.api_key_encrypted else "",
        temperature=saved.temperature,
        max_tokens=saved.max_tokens,
        timeout=saved.timeout,
        retry=saved.retry,
        dimension=saved.dimension,
    )


async def _test_chat(runtime: RuntimeModelConfig) -> dict[str, Any]:
    """通过一次极短 chat 请求测试大模型可用性。"""
    try:
        llm = LLMFactory.create(
            provider=runtime.provider,
            model_name=runtime.model_name,
            api_base=runtime.api_base or None,
            api_key=runtime.api_key,
        )
    except ValueError as exc:
        return {"success": False, "message": str(exc), "latency_ms": 0}

    started = perf_counter()
    try:
        await llm.chat([{"role": "user", "content": "ping"}], max_tokens=5)
        return {"success": True, "message": "连接成功", "latency_ms": int((perf_counter() - started) * 1000)}
    except Exception as exc:
        return {"success": False, "message": f"{exc.__class__.__name__}: {exc}", "latency_ms": _elapsed(started)}


async def _test_embedding(
    runtime: RuntimeModelConfig, milvus: MilvusStore | None = None
) -> dict[str, Any]:
    """通过一次 embed 请求测试 Embedding 配置，并校验向量维度。

    维度校验改为对比实际 Milvus Collection 维度:Collection 不存在时跳过,
    允许用户在删除 Collection 后切换到不同维度的 embedding 模型。
    """
    dimension = runtime.dimension or settings.embedding_dim
    collection_dim = _get_collection_dim(milvus)
    if collection_dim is not None and dimension != collection_dim:
        return {
            "success": False,
            "message": f"Embedding 维度必须与当前 Milvus Collection 一致: {collection_dim}",
            "latency_ms": 0,
        }
    try:
        embedding = EmbeddingFactory.create(
            runtime.provider,
            runtime.model_name,
            runtime.api_base or None,
            runtime.api_key or None,
            dimension=dimension,
        )
    except ValueError as exc:
        return {"success": False, "message": str(exc), "latency_ms": 0}

    started = perf_counter()
    try:
        vectors = await embedding.embed(["ping"])
        actual_dimension = len(vectors[0]) if vectors else 0
        if actual_dimension != dimension:
            return {
                "success": False,
                "message": f"向量维度不匹配: 期望 {dimension}, 实际 {actual_dimension}",
                "latency_ms": _elapsed(started),
            }
        return {"success": True, "message": "Embedding 连接成功", "latency_ms": _elapsed(started)}
    except Exception as exc:
        return {"success": False, "message": f"{exc.__class__.__name__}: {exc}", "latency_ms": _elapsed(started)}


async def _test_rerank(runtime: RuntimeModelConfig) -> dict[str, Any]:
    """测试 Rerank 配置；规则重排无需外部服务，其余 provider 需要兼容 HTTP 服务。"""
    if runtime.provider == "rule":
        return {"success": True, "message": "规则重排已启用，无需外部 API", "latency_ms": 0}
    if not runtime.api_base:
        return {"success": False, "message": "远程 Rerank 服务需要配置 API Base", "latency_ms": 0}

    import httpx

    started = perf_counter()
    try:
        headers = {"Authorization": f"Bearer {runtime.api_key}"} if runtime.api_key else None
        async with httpx.AsyncClient(timeout=runtime.timeout or settings.llm_timeout) as client:
            response = await client.post(
                runtime.api_base.rstrip("/"),
                headers=headers,
                json={"model": runtime.model_name, "query": "ping", "documents": ["pong"]},
            )
            response.raise_for_status()
        return {"success": True, "message": "Rerank 服务连接成功", "latency_ms": _elapsed(started)}
    except Exception as exc:
        return {"success": False, "message": f"{exc.__class__.__name__}: {exc}", "latency_ms": _elapsed(started)}


async def _test_tavily(runtime: RuntimeModelConfig) -> dict[str, Any]:
    """通过一次极小 Tavily Search 请求测试 API Key 可用性。"""
    if not runtime.api_key:
        return {"success": False, "message": "请填写 Tavily API Key", "latency_ms": 0}
    api_base = runtime.api_base or settings.tavily_api_base

    import httpx

    started = perf_counter()
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{api_base.rstrip('/')}/search",
                json={
                    "api_key": runtime.api_key,
                    "query": "ping",
                    "max_results": 1,
                    "search_depth": "basic",
                },
            )
            response.raise_for_status()
        return {"success": True, "message": "Tavily 连接成功", "latency_ms": _elapsed(started)}
    except Exception as exc:
        return {"success": False, "message": f"{exc.__class__.__name__}: {exc}", "latency_ms": _elapsed(started)}


async def get_active_tavily_api_key(db: AsyncSession, user_id: int) -> str:
    """返回当前用户已启用的 Tavily API Key 明文; 未配置或未启用时返回空字符串。

    供 WebSearchTool 运行时调用, 未配置时由工具直接走降级路径, 不调用 Tavily。
    """
    config = await get_active_config(db, user_id, "tavily")
    if config is None or not config.api_key_encrypted:
        return ""
    return crypto.decrypt(config.api_key_encrypted)


def _resolve_encrypted_key(data: SaveLlmConfigRequest, config: UserLlmConfig | None) -> str:
    """决定保存新密钥、沿用旧密钥或允许空密钥。"""
    api_key = (data.api_key or "").strip()
    if api_key:
        return crypto.encrypt(api_key)
    if config is not None and config.api_key_encrypted:
        return config.api_key_encrypted
    if provider_requires_api_key(data.provider, data.config_type) and data.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请填写 API Key")
    return ""


def _resolve_dimension(data: SaveLlmConfigRequest) -> int | None:
    """为 Embedding 配置补齐向量维度，其他配置类型返回 None。"""
    if data.config_type != "embedding":
        return None
    if data.dimension:
        return data.dimension
    info = _provider_info(data.provider, data.config_type)
    return int(info.get("default_dimension") or settings.embedding_dim) if info else settings.embedding_dim


def _get_collection_dim(milvus: MilvusStore | None) -> int | None:
    """安全地获取 Milvus Collection 维度;失败或不可用时返回 None。

    milvus 为 None 或调用异常都视为"Collection 不存在",交给上层跳过维度校验,
    避免维度保护把用户彻底卡死。这与 lifespan 中 Milvus 不可用降级为 BM25 的策略一致。
    """
    if milvus is None:
        return None
    try:
        return milvus.get_collection_dim()
    except Exception as exc:
        logger.warning("获取 Milvus Collection 维度失败,跳过维度校验: %s", exc)
        return None


def _validate_embedding_dimension(dimension: int | None, milvus: MilvusStore | None) -> None:
    """校验 embedding 维度与实际 Milvus Collection 一致;Collection 不存在时跳过。"""
    collection_dim = _get_collection_dim(milvus)
    if collection_dim is None:
        return
    if dimension != collection_dim:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Embedding 维度必须与当前 Milvus Collection 一致: {collection_dim}",
        )


def _validate_provider(provider: str, config_type: ModelConfigType) -> None:
    """校验 provider 是否支持当前配置类型。"""
    if _provider_info(provider, config_type) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{provider} 不支持 {config_type} 配置",
        )


def _provider_info(provider: str, config_type: ModelConfigType) -> dict[str, Any] | None:
    """按 provider 名称和配置类型查找元信息。"""
    lowered = provider.lower()
    for item in BUILTIN_PROVIDERS:
        if item["name"] == lowered and config_type in item["config_types"]:
            return item
    return None


def _global_runtime_config(config_type: ModelConfigType) -> RuntimeModelConfig | None:
    """把 `.env` 兜底配置转换为统一运行时结构。"""
    if config_type == "chat":
        return RuntimeModelConfig(
            config_type="chat",
            provider=settings.llm_provider,
            model_name=settings.llm_model,
            api_base=settings.llm_api_base,
            api_key=settings.llm_api_key,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            timeout=settings.llm_timeout,
            retry=settings.llm_retry,
        )
    if config_type == "embedding":
        return RuntimeModelConfig(
            config_type="embedding",
            provider=settings.embedding_provider,
            model_name=settings.embedding_model,
            api_base=settings.embedding_api_base,
            api_key=settings.embedding_api_key,
            dimension=settings.embedding_dim,
        )
    if config_type == "rerank":
        return RuntimeModelConfig(
            config_type="rerank",
            provider=settings.reranker_provider,
            model_name=settings.reranker_model,
            api_base=settings.reranker_api_base,
            api_key="",
        )
    return None


def _elapsed(started: float) -> int:
    """返回从 started 到当前的毫秒数。"""
    return int((perf_counter() - started) * 1000)
