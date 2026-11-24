"""本文件统一解析模型运行时配置,用于解释最终使用的 provider、模型和配置来源。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.models.knowledge import KnowledgeBase, KnowledgeDocument
from backend.models.llm_config import UserLlmConfig
from backend.schemas.llm_config import ModelConfigType
from backend.utils import crypto
from backend.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class RuntimeModelResolution:
    """模型运行时配置解析结果,包含敏感 key 和可解释的来源信息。"""

    config_type: ModelConfigType
    provider: str
    model_name: str
    api_base: str
    api_key: str
    dimension: int | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    timeout: int | None = None
    retry: int | None = None
    source: str = "global_config"
    source_config_id: int | None = None
    source_user_id: int | None = None
    document_id: int | None = None
    kb_id: int | None = None
    kb_embedding_model: str | None = None
    kb_rerank_model: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def has_api_key(self) -> bool:
        """返回是否存在可用 API Key,不暴露明文。"""
        return bool(self.api_key)

    def to_public_dict(self) -> dict[str, Any]:
        """返回接口可安全展示的运行时配置。"""
        return {
            "config_type": self.config_type,
            "provider": self.provider,
            "model_name": self.model_name,
            "api_base": self.api_base,
            "has_api_key": self.has_api_key,
            "dimension": self.dimension,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
            "retry": self.retry,
            "source": self.source,
            "source_config_id": self.source_config_id,
            "source_user_id": self.source_user_id,
            "document_id": self.document_id,
            "kb_id": self.kb_id,
            "kb_embedding_model": self.kb_embedding_model,
            "kb_rerank_model": self.kb_rerank_model,
            "warnings": self.warnings,
        }

    def to_task_snapshot(self) -> dict[str, Any]:
        """返回可写入任务 payload 的非敏感配置快照。"""
        return {
            "config_type": self.config_type,
            "provider": self.provider,
            "model_name": self.model_name,
            "api_base": self.api_base,
            "dimension": self.dimension,
            "timeout": self.timeout,
            "retry": self.retry,
            "source": self.source,
            "source_config_id": self.source_config_id,
            "source_user_id": self.source_user_id,
            "kb_embedding_model": self.kb_embedding_model,
            "kb_rerank_model": self.kb_rerank_model,
            "warnings": self.warnings,
        }


async def resolve_model_runtime(
    db: AsyncSession,
    user_id: int,
    config_type: ModelConfigType,
    *,
    document: KnowledgeDocument | None = None,
    kb: KnowledgeBase | None = None,
    snapshot: dict[str, Any] | None = None,
) -> RuntimeModelResolution:
    """按任务快照、知识库绑定、用户配置、全局配置的顺序解析最终模型配置。"""
    if document is not None and kb is None:
        kb = await db.get(KnowledgeBase, document.kb_id)
    base = await _resolve_user_or_global_config(db, user_id, config_type)
    resolution = _apply_context(base, document, kb)
    snapshot_resolution = await _resolve_snapshot(db, user_id, config_type, snapshot, resolution)
    if snapshot_resolution is not None:
        return snapshot_resolution
    if config_type == "embedding":
        return _apply_embedding_kb_override(resolution, kb)
    if config_type == "rerank":
        return _apply_rerank_kb_override(resolution, kb)
    return resolution


async def resolve_embedding_runtime(
    db: AsyncSession,
    document: KnowledgeDocument,
    kb: KnowledgeBase | None = None,
    *,
    snapshot: dict[str, Any] | None = None,
) -> RuntimeModelResolution:
    """解析文档 Embedding 任务实际使用的运行时模型配置。"""
    return await resolve_model_runtime(
        db,
        document.user_id,
        "embedding",
        document=document,
        kb=kb,
        snapshot=snapshot,
    )


async def _resolve_user_or_global_config(
    db: AsyncSession, user_id: int, config_type: ModelConfigType
) -> RuntimeModelResolution:
    """优先读取用户启用配置,没有时回退到全局配置。"""
    if settings.byok_enabled:
        result = await db.execute(
            select(UserLlmConfig).where(
                UserLlmConfig.user_id == user_id,
                UserLlmConfig.config_type == config_type,
                UserLlmConfig.is_active == 1,
            )
        )
        config = result.scalar_one_or_none()
        if config is not None:
            return RuntimeModelResolution(
                config_type=config_type,
                provider=config.provider,
                model_name=config.model_name,
                api_base=config.api_base,
                api_key=crypto.decrypt(config.api_key_encrypted) if config.api_key_encrypted else "",
                dimension=config.dimension,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                timeout=config.timeout,
                retry=config.retry,
                source="user_config",
                source_config_id=config.id,
                source_user_id=user_id,
            )
    if not settings.byok_fallback_to_global:
        raise ValueError(f"用户 {user_id} 未启用 {config_type} 配置且禁止全局兜底")
    return _global_resolution(config_type, user_id)


def _global_resolution(config_type: ModelConfigType, user_id: int) -> RuntimeModelResolution:
    """将 .env 全局兜底配置转换为统一运行时结果。"""
    if config_type == "chat":
        return RuntimeModelResolution(
            config_type="chat",
            provider=settings.llm_provider,
            model_name=settings.llm_model,
            api_base=settings.llm_api_base,
            api_key=settings.llm_api_key,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            timeout=settings.llm_timeout,
            retry=settings.llm_retry,
            source_user_id=user_id,
        )
    if config_type == "embedding":
        return RuntimeModelResolution(
            config_type="embedding",
            provider=settings.embedding_provider,
            model_name=settings.embedding_model,
            api_base=settings.embedding_api_base,
            api_key=settings.embedding_api_key,
            dimension=settings.embedding_dim,
            source_user_id=user_id,
        )
    return RuntimeModelResolution(
        config_type="rerank",
        provider=settings.reranker_provider,
        model_name=settings.reranker_model,
        api_base=settings.reranker_api_base,
        api_key="",
        source_user_id=user_id,
    )


def _apply_context(
    resolution: RuntimeModelResolution,
    document: KnowledgeDocument | None,
    kb: KnowledgeBase | None,
) -> RuntimeModelResolution:
    """补充文档、知识库上下文,便于日志和诊断接口解释。"""
    return RuntimeModelResolution(
        **{
            **resolution.__dict__,
            "document_id": document.id if document is not None else None,
            "kb_id": kb.id if kb is not None else (document.kb_id if document is not None else None),
            "kb_embedding_model": kb.embedding_model if kb is not None else None,
            "kb_rerank_model": kb.rerank_model if kb is not None else None,
        }
    )


async def _resolve_snapshot(
    db: AsyncSession,
    user_id: int,
    config_type: ModelConfigType,
    snapshot: dict[str, Any] | None,
    fallback: RuntimeModelResolution,
) -> RuntimeModelResolution | None:
    """解析任务快照;快照不保存明文 key,因此 key 仍从同一配置记录或当前配置补齐。"""
    if not snapshot or snapshot.get("config_type") != config_type:
        return None
    provider = str(snapshot.get("provider") or "")
    model_name = str(snapshot.get("model_name") or "")
    if not provider or not model_name:
        return None
    config = await _get_snapshot_config(db, user_id, snapshot)
    api_key = ""
    if config is not None and config.api_key_encrypted:
        api_key = crypto.decrypt(config.api_key_encrypted)
    elif fallback.provider == provider:
        api_key = fallback.api_key
    warnings = [*fallback.warnings, *list(snapshot.get("warnings") or [])]
    # bge provider 调用本地 TEI 服务，默认不要求 API Key；无密钥是合法配置，
    # 不应与 OpenAI/Qwen 等远程 provider 一样产生误导性告警。
    if not api_key and provider.lower() != "bge":
        warnings.append("任务快照未找到同 provider 的可用密钥,请检查当前用户模型配置")
    return RuntimeModelResolution(
        config_type=config_type,
        provider=provider,
        model_name=model_name,
        api_base=str(snapshot.get("api_base") or ""),
        api_key=api_key,
        dimension=int(snapshot["dimension"]) if snapshot.get("dimension") else fallback.dimension,
        temperature=fallback.temperature,
        max_tokens=fallback.max_tokens,
        timeout=int(snapshot["timeout"]) if snapshot.get("timeout") else fallback.timeout,
        retry=int(snapshot["retry"]) if snapshot.get("retry") is not None else fallback.retry,
        source="task_snapshot",
        source_config_id=int(snapshot["source_config_id"])
        if snapshot.get("source_config_id")
        else fallback.source_config_id,
        source_user_id=user_id,
        document_id=fallback.document_id,
        kb_id=fallback.kb_id,
        kb_embedding_model=fallback.kb_embedding_model,
        kb_rerank_model=fallback.kb_rerank_model,
        warnings=warnings,
    )


async def _get_snapshot_config(
    db: AsyncSession, user_id: int, snapshot: dict[str, Any]
) -> UserLlmConfig | None:
    """按快照中的配置 ID 找回密钥,找不到时由调用方回退。"""
    config_id = snapshot.get("source_config_id")
    if not config_id:
        return None
    result = await db.execute(
        select(UserLlmConfig).where(
            UserLlmConfig.id == int(config_id),
            UserLlmConfig.user_id == user_id,
            UserLlmConfig.is_active == 1,
        )
    )
    return result.scalar_one_or_none()


def _apply_embedding_kb_override(
    resolution: RuntimeModelResolution, kb: KnowledgeBase | None
) -> RuntimeModelResolution:
    """在知识库模型与运行时 provider 一致时使用知识库绑定模型。"""
    kb_model = (kb.embedding_model if kb is not None else None) or ""
    if not kb_model:
        return resolution
    kb_provider = _resolve_provider(kb_model, resolution.provider)
    if kb_provider != resolution.provider:
        warning = (
            f"知识库Embedding模型 {kb_model} 与运行时 provider={resolution.provider} 不一致,"
            f"已使用运行时模型 {resolution.model_name}"
        )
        logger.warning(warning)
        return _with_warning(resolution, warning)
    if kb_model == resolution.model_name:
        return resolution
    return RuntimeModelResolution(
        **{
            **resolution.__dict__,
            "model_name": kb_model,
            "source": f"{resolution.source}+kb_model",
            "warnings": [
                *resolution.warnings,
                f"知识库绑定模型覆盖运行时模型: {resolution.model_name} -> {kb_model}",
            ],
        }
    )


def _apply_rerank_kb_override(
    resolution: RuntimeModelResolution, kb: KnowledgeBase | None
) -> RuntimeModelResolution:
    """在知识库绑定了 rerank 模型时记录来源;provider 不明确时不强制覆盖。"""
    kb_model = (kb.rerank_model if kb is not None else None) or ""
    if not kb_model:
        return resolution
    return RuntimeModelResolution(
        **{
            **resolution.__dict__,
            "model_name": kb_model,
            "source": f"{resolution.source}+kb_model",
            "warnings": [
                *resolution.warnings,
                f"知识库绑定 Rerank 模型覆盖运行时模型: {resolution.model_name} -> {kb_model}",
            ],
        }
    )


def _with_warning(resolution: RuntimeModelResolution, warning: str) -> RuntimeModelResolution:
    """返回追加 warning 的不可变解析结果。"""
    return RuntimeModelResolution(**{**resolution.__dict__, "warnings": [*resolution.warnings, warning]})


def _resolve_provider(model_name: str, fallback_provider: str) -> str:
    """根据模型名识别常见 provider,无法识别时回退到传入 provider。"""
    lowered = model_name.lower()
    if "bge" in lowered:
        return "bge"
    if "qwen" in lowered or "text-embedding-v" in lowered:
        return "qwen"
    if "deepseek" in lowered:
        return "deepseek"
    if model_name.startswith("text-embedding-3") or model_name == "text-embedding-ada-002":
        return "openai"
    return fallback_provider
