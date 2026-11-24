"""本文件用策略模式为不同法律 Chunk 构造仅供 Embedding 使用的增强文本。"""

from abc import ABC, abstractmethod
from typing import Any

from backend.utils.tokenizer import count_tokens, truncate_to_tokens


def _content(metadata: dict[str, Any]) -> str:
    """兼容 metadata.content 与调用方补充的 text 字段。"""
    return str(metadata.get("content") or metadata.get("text") or "").strip()


def _label(*parts: Any) -> str:
    """拼接非空层级字段并包装为中文书名式标签。"""
    value = " ".join(str(part).strip() for part in parts if part not in (None, ""))
    return f"【{value}】" if value else ""


class BaseEnhancer(ABC):
    """每种 chunk_type 独立实现的上下文增强策略接口。"""

    @property
    @abstractmethod
    def chunk_type(self) -> str:
        """返回当前策略处理的 Chunk 大类。"""

    @abstractmethod
    async def enhance(self, metadata: dict[str, Any]) -> str:
        """根据结构化 metadata 生成增强文本。"""


class LawEnhancer(BaseEnhancer):
    """按法律名称、编、章、节、条逐级增强法条文本。"""

    chunk_type = "law"

    async def enhance(self, metadata: dict[str, Any]) -> str:
        """生成携带完整法律层级归属的 Embedding 文本。"""
        lines = [
            _label(metadata.get("law_name")),
            _label(metadata.get("part_no"), metadata.get("part_title")),
            _label(metadata.get("chapter_no"), metadata.get("chapter_title")),
            _label(metadata.get("section_no"), metadata.get("section_title")),
            _label(metadata.get("article_no") or metadata.get("article")),
            _content(metadata),
        ]
        return "\n".join(line for line in lines if line)


class JudicialEnhancer(LawEnhancer):
    """复用法律层级规则增强司法解释 Chunk。"""

    chunk_type = "judicial"


class CaseEnhancer(BaseEnhancer):
    """使用案件名称、法院、案由、裁判日期与正文增强案例 Chunk。"""

    chunk_type = "case"

    async def enhance(self, metadata: dict[str, Any]) -> str:
        """生成案例 Embedding 文本。"""
        header = _label(
            metadata.get("case_name"),
            metadata.get("court"),
            metadata.get("cause_of_action"),
            metadata.get("judgment_date"),
        )
        return "\n".join(part for part in (header, _content(metadata)[:200]) if part)


class ContractEnhancer(BaseEnhancer):
    """使用合同名称和条款类型增强合同 Chunk。"""

    chunk_type = "contract"
    CLAUSE_NAMES = {
        "party_info": "当事人信息", "liability": "违约责任", "payment": "付款条款",
        "termination": "解除终止", "dispute": "争议解决",
    }

    async def enhance(self, metadata: dict[str, Any]) -> str:
        """生成合同 Embedding 文本。"""
        subtype = metadata.get("chunk_subtype") or metadata.get("clause_type")
        header = _label(metadata.get("contract_name"), self.CLAUSE_NAMES.get(str(subtype), subtype))
        return "\n".join(part for part in (header, _content(metadata)) if part)


class EnterpriseEnhancer(BaseEnhancer):
    """使用制度标题、关键词与正文摘要增强企业制度 Chunk。"""

    chunk_type = "enterprise"

    async def enhance(self, metadata: dict[str, Any]) -> str:
        """生成企业制度 Embedding 文本。"""
        keywords = metadata.get("keywords") or []
        if isinstance(keywords, str):
            keywords = [keywords]
        header = _label(metadata.get("title"), "、".join(str(item) for item in keywords))
        return "\n".join(part for part in (header, _content(metadata)[:200]) if part)


class ContextEnhancer:
    """通过注册表分发增强策略，并统一执行父级跳过与 token 上限控制。"""

    PARENT_LEVELS = {"book", "chapter", "section"}

    def __init__(self, max_tokens: int = 500, model_name: str = "cl100k_base"):
        """初始化增强器注册表和模型长度限制。"""
        self.max_tokens = max_tokens
        self.model_name = model_name
        self._registry: dict[str, BaseEnhancer] = {}

    def register(self, enhancer: BaseEnhancer) -> None:
        """注册或替换一种 Chunk 大类的增强策略。"""
        self._registry[enhancer.chunk_type] = enhancer

    async def enhance(self, metadata: dict[str, Any]) -> str:
        """增强单个 Chunk；父级 Chunk 直接使用规则摘要正文。"""
        original = _content(metadata)
        if metadata.get("chunk_level") in self.PARENT_LEVELS:
            return truncate_to_tokens(original, self.max_tokens, self.model_name)
        enhancer = self._registry.get(str(metadata.get("chunk_type") or ""))
        enhanced = await enhancer.enhance(metadata) if enhancer else original
        if count_tokens(enhanced, self.model_name) <= self.max_tokens:
            return enhanced

        # 超长时优先保留法律名称、条号与原文，裁剪中间层级。
        priority = "\n".join(
            part for part in (
                _label(metadata.get("law_name")),
                _label(metadata.get("article_no") or metadata.get("article")),
                original,
            ) if part
        )
        return truncate_to_tokens(priority, self.max_tokens, self.model_name)

    async def enhance_batch(self, chunks: list[dict[str, Any]]) -> list[str]:
        """按输入顺序批量生成增强文本。"""
        return [await self.enhance(chunk) for chunk in chunks]


def create_default_enhancer(max_tokens: int = 500, model_name: str = "cl100k_base") -> ContextEnhancer:
    """创建并注册阶段三内置策略的增强器门面。"""
    enhancer = ContextEnhancer(max_tokens=max_tokens, model_name=model_name)
    for strategy in (LawEnhancer(), JudicialEnhancer(), CaseEnhancer(), ContractEnhancer(), EnterpriseEnhancer()):
        enhancer.register(strategy)
    return enhancer


context_enhancer = create_default_enhancer()
