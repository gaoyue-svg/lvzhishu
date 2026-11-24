"""本文件定义可注册的 Embedding 模型抽象及 OpenAI 兼容、本地 BGE 实现。"""

import asyncio
from abc import ABC, abstractmethod
from typing import Any

class BaseEmbedding(ABC):
    """Embedding 模型统一异步接口。"""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """将一批增强文本转换为等长向量列表。"""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """返回向量维度。"""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """返回远端或本地模型名称。"""


class OpenAICompatibleEmbedding(BaseEmbedding):
    """封装遵循 OpenAI Embeddings 协议的异步服务。"""

    DIMENSION_MAP = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
        "text-embedding-v4": 1024,
    }

    def __init__(
        self,
        model_name: str,
        api_base: str | None = None,
        api_key: str | None = None,
        dimension: int | None = None,
    ):
        """初始化 OpenAI 兼容客户端和维度信息。"""
        kwargs: dict[str, Any] = {"api_key": api_key or "not-configured"}
        if api_base:
            kwargs["base_url"] = api_base
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(**kwargs)
        self._model_name = model_name
        self._dimension = dimension or self.DIMENSION_MAP.get(model_name, 1536)

    @property
    def dimension(self) -> int:
        """返回配置或模型默认的向量维度。"""
        return self._dimension

    @property
    def model_name(self) -> str:
        """返回模型名称。"""
        return self._model_name

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """每批最多 100 条，失败时按 1、2、4 秒指数退避重试。"""
        vectors: list[list[float]] = []
        for start in range(0, len(texts), 100):
            batch = texts[start : start + 100]
            response = await self._request_with_retry(batch)
            ordered = sorted(response.data, key=lambda item: item.index)
            vectors.extend([list(item.embedding) for item in ordered])
        return vectors

    async def _request_with_retry(self, texts: list[str]):
        """执行单批 API 请求并最多重试三次。"""
        last_error: Exception | None = None
        for delay in (1, 2, 4):
            try:
                params: dict[str, Any] = {"model": self.model_name, "input": texts}
                # OpenAI 与百炼的文本向量模型允许显式指定输出维度。
                if self.model_name.startswith(
                    ("text-embedding-3", "text-embedding-v", "qwen3.7-text-embedding")
                ):
                    params["dimensions"] = self.dimension
                return await self.client.embeddings.create(**params)
            except Exception as exc:
                if _is_non_retryable_http_error(exc):
                    raise
                last_error = exc
                await asyncio.sleep(delay)
        assert last_error is not None
        raise last_error


class OpenAIEmbedding(OpenAICompatibleEmbedding):
    """OpenAI 官方 Embedding 服务实现。"""


class DeepSeekEmbedding(OpenAICompatibleEmbedding):
    """使用 OpenAI 兼容协议的 DeepSeek Embedding 实现。"""


class QwenEmbedding(OpenAICompatibleEmbedding):
    """使用 OpenAI 兼容协议的通义千问 Embedding 实现。"""


class BGEEmbedding(BaseEmbedding):
    """通过本地 TEI HTTP 服务调用 BGE 中文向量模型。"""

    def __init__(
        self,
        model_name: str,
        api_base: str | None = None,
        api_key: str | None = None,
        dimension: int | None = None,
    ):
        """初始化本地 BGE 服务地址与模型维度。"""
        self._model_name = model_name
        self._dimension = dimension or 1024
        self.api_base = (api_base or "http://127.0.0.1:8080").rstrip("/")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        import httpx

        self.client = httpx.AsyncClient(headers=headers, timeout=60.0)

    @property
    def dimension(self) -> int:
        """返回 BGE 向量维度。"""
        return self._dimension

    @property
    def model_name(self) -> str:
        """返回 BGE 模型名称。"""
        return self._model_name

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """按 100 条分批调用 TEI `/embed` 接口并执行指数退避。"""
        vectors: list[list[float]] = []
        for start in range(0, len(texts), 100):
            vectors.extend(await self._request_with_retry(texts[start : start + 100]))
        return vectors

    async def _request_with_retry(self, texts: list[str]) -> list[list[float]]:
        """兼容 TEI 的 inputs 请求格式。"""
        last_error: Exception | None = None
        for delay in (1, 2, 4):
            try:
                response = await self.client.post(f"{self.api_base}/embed", json={"inputs": texts})
                response.raise_for_status()
                payload = response.json()
                return [[float(value) for value in vector] for vector in payload]
            except Exception as exc:
                if _is_non_retryable_http_error(exc):
                    raise
                last_error = exc
                await asyncio.sleep(delay)
        assert last_error is not None
        raise last_error


class EmbeddingFactory:
    """使用注册表创建 Embedding 实例，新增 provider 时无需修改分支逻辑。"""

    _registry: dict[str, type[BaseEmbedding]] = {}

    @classmethod
    def register(cls, provider: str, embedding_cls: type[BaseEmbedding]) -> None:
        """注册一个 provider 名称及其实现类。"""
        cls._registry[provider.lower()] = embedding_cls

    @classmethod
    def create(
        cls,
        provider: str,
        model_name: str,
        api_base: str | None,
        api_key: str | None,
        dimension: int | None = None,
    ) -> BaseEmbedding:
        """根据 provider 构造模型，不识别时给出已注册列表。"""
        embedding_cls = cls._registry.get(provider.lower())
        if embedding_cls is None:
            raise ValueError(
                f"未知的 Embedding provider: {provider}. 已注册: {list(cls._registry)}"
            )
        return embedding_cls(
            model_name=model_name,
            api_base=api_base,
            api_key=api_key,
            dimension=dimension,
        )


EmbeddingFactory.register("openai", OpenAIEmbedding)
EmbeddingFactory.register("bge", BGEEmbedding)
EmbeddingFactory.register("deepseek", DeepSeekEmbedding)
EmbeddingFactory.register("qwen", QwenEmbedding)


def _is_non_retryable_http_error(exc: Exception) -> bool:
    """识别 4xx 中不应重试的错误,避免配额或参数错误反复刷日志。"""
    status_code = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status_code is None and response is not None:
        status_code = getattr(response, "status_code", None)
    return isinstance(status_code, int) and 400 <= status_code < 500 and status_code != 429
