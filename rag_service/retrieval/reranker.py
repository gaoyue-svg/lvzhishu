"""本文件实现由独立打分组件组成的阶段三法律规则重排器。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any


def _value(candidate: dict[str, Any], key: str, default=None):
    """优先读取顶层字段，再从 metadata 读取。"""
    if candidate.get(key) is not None:
        return candidate[key]
    return (candidate.get("metadata") or {}).get(key, default)


class BaseScorer(ABC):
    """可单独替换和测试的重排打分维度接口。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """返回打分维度名称。"""

    @abstractmethod
    def score(self, candidate: dict[str, Any], context: dict[str, Any]) -> float:
        """返回 0 到 1 之间的分数。"""


class SemanticScorer(BaseScorer):
    """使用 Milvus COSINE 相似度作为阶段三语义分。"""

    name = "semantic"

    def score(self, candidate: dict[str, Any], context: dict[str, Any]) -> float:
        """优先使用已归一化相似度，兼容旧 distance 字段。"""
        similarity = _value(candidate, "milvus_score")
        if similarity is not None:
            return max(0.0, min(1.0, float(similarity)))
        distance = float(_value(candidate, "milvus_distance", 1.0) or 1.0)
        return max(0.0, min(1.0, 1.0 - distance))


class BM25Scorer(BaseScorer):
    """使用已在 BM25 通路归一化的关键词匹配分。"""

    name = "bm25"

    def score(self, candidate: dict[str, Any], context: dict[str, Any]) -> float:
        """限制分数到 0 到 1。"""
        return max(0.0, min(1.0, float(_value(candidate, "bm25_score", 0.0) or 0.0)))


class LegalLevelScorer(BaseScorer):
    """仅按 metadata.legal_level 固定映射法律位阶，不根据名称猜测。"""

    name = "legal_level"
    LEVEL_MAP = {
        "constitution": 1.0,
        "basic_law": 1.0,
        "administrative_regulation": 0.8,
        "judicial_interpretation": 0.7,
        "local_regulation": 0.65,
        "departmental_rule": 0.6,
    }

    def score(self, candidate: dict[str, Any], context: dict[str, Any]) -> float:
        """查询明确 metadata 枚举并提供中性默认值。"""
        return self.LEVEL_MAP.get(str(_value(candidate, "legal_level", "")), 0.5)


class ChunkLevelScorer(BaseScorer):
    """一般问答优先 Article，章节总结意图则提升父级 Chunk。"""

    name = "chunk_level"
    LEVEL_MAP = {"article": 1.0, "clause": 0.95, "paragraph": 0.9, "section": 0.7, "chapter": 0.5, "book": 0.3}
    SUMMARY_MAP = {"book": 1.0, "chapter": 1.0, "section": 0.9, "article": 0.55, "paragraph": 0.4, "clause": 0.4}

    def score(self, candidate: dict[str, Any], context: dict[str, Any]) -> float:
        """根据意图选择层级评分表。"""
        level = str(_value(candidate, "chunk_level", ""))
        mapping = self.SUMMARY_MAP if context.get("intent_type") == "chapter_summary" else self.LEVEL_MAP
        return mapping.get(level, 0.5)


class FreshnessScorer(BaseScorer):
    """最新版本满分，历史版本按生效日期以十年窗口衰减。"""

    name = "freshness"

    def score(self, candidate: dict[str, Any], context: dict[str, Any]) -> float:
        """历史查询不额外偏爱最新版，其余查询计算时效分。"""
        if context.get("historical"):
            return 0.5
        if bool(_value(candidate, "is_latest", False)):
            return 1.0
        effective_date = int(_value(candidate, "effective_date", 0) or 0)
        if not effective_date:
            return 0.5
        age_days = max(0.0, (datetime.now(timezone.utc).timestamp() - effective_date) / 86400)
        return max(0.1, 1.0 - age_days / 3650)


class KeywordMatchScorer(BaseScorer):
    """预留的结构化关键词交集打分组件。"""

    name = "keyword"

    def score(self, candidate: dict[str, Any], context: dict[str, Any]) -> float:
        """计算查询关键词和 Chunk 关键词的覆盖率。"""
        query_keywords = set(context.get("query_keywords", []))
        if not query_keywords:
            return 0.5
        chunk_keywords = set(_value(candidate, "keywords", []) or [])
        haystack = " ".join(
            str(_value(candidate, key, "") or "")
            for key in ("law_name", "article_no", "text")
        )
        matched = {
            keyword for keyword in query_keywords
            if keyword in chunk_keywords or str(keyword) in haystack
        }
        return min(1.0, len(matched) / len(query_keywords))


class RetrievalAgreementScorer(BaseScorer):
    """双路共同召回的候选优先，避免单路高分压过一致命中。"""

    name = "agreement"

    def score(self, candidate: dict[str, Any], context: dict[str, Any]) -> float:
        has_semantic = _value(candidate, "milvus_score") is not None
        has_bm25 = _value(candidate, "bm25_score") is not None
        if has_semantic and has_bm25:
            return 1.0
        if has_semantic or has_bm25:
            return 0.2
        return 0.0


class LegalDomainScorer(BaseScorer):
    """根据查询领域对法规来源进行软排序，不用硬过滤误伤相关司法解释。"""

    name = "domain"

    def score(self, candidate: dict[str, Any], context: dict[str, Any]) -> float:
        domain = context.get("legal_domain")
        if not domain:
            return 0.5
        law_name = str(_value(candidate, "law_name", "") or "")
        text = str(_value(candidate, "text", "") or "")[:300]
        if domain == "criminal":
            if any(marker in law_name for marker in ("刑法", "刑事诉讼", "刑事")):
                return 1.0
            if any(marker in text for marker in ("犯罪", "刑事责任", "拘役", "有期徒刑")):
                return 0.7
            if "治安管理处罚" in law_name:
                return 0.4
            return 0.0
        return 0.5


class ScorePipeline:
    """按配置执行多个 Scorer 并输出加权总分与分项明细。"""

    def __init__(self):
        """创建空打分流水线。"""
        self._scorers: list[tuple[BaseScorer, float]] = []

    def add_scorer(self, scorer: BaseScorer, weight: float) -> "ScorePipeline":
        """链式添加打分器及权重。"""
        self._scorers.append((scorer, weight))
        return self

    def compute_final_score(
        self, candidate: dict[str, Any], context: dict[str, Any]
    ) -> tuple[float, dict[str, float]]:
        """计算总分并返回便于 Trace 调试的分项分数。"""
        components = {scorer.name: scorer.score(candidate, context) for scorer, _ in self._scorers}
        total = sum(weight * components[scorer.name] for scorer, weight in self._scorers)
        return total, components

    @property
    def weights(self) -> dict[str, float]:
        """返回当前流水线权重。"""
        return {scorer.name: weight for scorer, weight in self._scorers}


def create_default_pipeline() -> ScorePipeline:
    """创建兼顾语义、关键词、双路一致性与法律领域的默认公式。"""
    return (
        ScorePipeline()
        .add_scorer(SemanticScorer(), 0.30)
        .add_scorer(BM25Scorer(), 0.15)
        .add_scorer(RetrievalAgreementScorer(), 0.15)
        .add_scorer(KeywordMatchScorer(), 0.15)
        .add_scorer(LegalDomainScorer(), 0.10)
        .add_scorer(LegalLevelScorer(), 0.05)
        .add_scorer(ChunkLevelScorer(), 0.05)
        .add_scorer(FreshnessScorer(), 0.05)
    )


class RuleLegalReranker:
    """不依赖 Cross-Encoder 的阶段三法律规则重排器。"""

    def __init__(self, pipeline: ScorePipeline | None = None):
        """注入打分流水线，默认使用文档规定公式。"""
        self.pipeline = pipeline or create_default_pipeline()

    async def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_k: int = 8,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """为候选计算分项及总分，降序返回 TopK。"""
        score_context = {"query": query, **(context or {})}
        ranked = []
        for candidate in candidates:
            item = dict(candidate)
            item["final_score"], item["score_components"] = self.pipeline.compute_final_score(
                item, score_context
            )
            item["score"] = item["final_score"]
            ranked.append(item)
        ranked.sort(key=lambda item: item["final_score"], reverse=True)
        return ranked[:top_k]


class ConfigurableLegalReranker(RuleLegalReranker):
    """支持动态配置的重排器；rule 走本地规则，远程服务失败时降级到规则重排。"""

    def __init__(
        self,
        *,
        provider: str = "rule",
        model_name: str = "law-rule-reranker",
        api_base: str = "",
        api_key: str = "",
        timeout: int = 30,
        pipeline: ScorePipeline | None = None,
    ):
        """保存远程 Rerank 配置，并初始化规则重排兜底流水线。"""
        super().__init__(pipeline)
        self.provider = provider
        self.model_name = model_name
        self.api_base = api_base
        self.api_key = api_key
        self.timeout = timeout

    async def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_k: int = 8,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """根据配置选择远程 Rerank 或本地规则重排。"""
        if self.provider == "rule" or not self.api_base or not candidates:
            return await super().rerank(query, candidates, top_k=top_k, context=context)
        try:
            return await self._remote_rerank(query, candidates, top_k)
        except Exception:
            return await super().rerank(query, candidates, top_k=top_k, context=context)

    async def _remote_rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        """调用兼容 Rerank HTTP 服务，支持 scores 或 results 两种常见响应形态。"""
        import httpx

        documents = [str(item.get("text") or (item.get("metadata") or {}).get("content") or "") for item in candidates]
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else None
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self.api_base.rstrip("/"),
                headers=headers,
                json={"model": self.model_name, "query": query, "documents": documents, "top_k": top_k},
            )
            response.raise_for_status()
            payload = response.json()

        scores = self._extract_scores(payload, len(candidates))
        ranked = []
        for index, candidate in enumerate(candidates):
            item = dict(candidate)
            item["final_score"] = float(scores[index])
            item["score"] = item["final_score"]
            item["score_components"] = {"remote_rerank": item["final_score"]}
            ranked.append(item)
        ranked.sort(key=lambda item: item["final_score"], reverse=True)
        return ranked[:top_k]

    @staticmethod
    def _extract_scores(payload: dict[str, Any], expected_count: int) -> list[float]:
        """从远程响应中解析每个候选文档的重排分数。"""
        if isinstance(payload.get("scores"), list):
            raw_scores = payload["scores"]
            return [float(raw_scores[index]) if index < len(raw_scores) else 0.0 for index in range(expected_count)]
        results = payload.get("results")
        scores = [0.0 for _ in range(expected_count)]
        if isinstance(results, list):
            for rank, item in enumerate(results):
                index = int(item.get("index", rank)) if isinstance(item, dict) else rank
                if 0 <= index < expected_count:
                    scores[index] = float(item.get("score", item.get("relevance_score", 0.0)))
        return scores
