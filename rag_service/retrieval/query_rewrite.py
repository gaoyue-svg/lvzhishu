"""本文件提供可替换的查询重写接口及阶段三规则词典实现。"""

import json
import re
from abc import ABC, abstractmethod
from pathlib import Path

from .models import RewriteResult


class BaseQueryRewriter(ABC):
    """Retriever 依赖的查询重写抽象接口。"""

    @abstractmethod
    async def rewrite(self, user_query: str) -> RewriteResult:
        """将口语查询转换为语义检索与关键词检索两路查询。"""


class RuleQueryRewriter(BaseQueryRewriter):
    """使用同义词和法律术语映射完成不依赖 LLM 的查询重写。"""

    DEFAULT_SYNONYMS = {
        "借钱不还": "民间借贷 借款合同 违约责任",
        "欠钱不还": "民间借贷 借款合同 违约责任",
        "老板不发工资": "劳动报酬 工资拖欠 劳动争议",
        "离婚分财产": "离婚 财产分割 夫妻共同财产",
        "被开除": "解除劳动合同 违法解除 经济补偿",
        "合同不算数": "合同无效 可撤销合同",
        "醉驾": "醉酒驾驶 危险驾驶罪 刑法第一百三十三条之一 拘役 罚金",
        "酒驾": "饮酒驾驶 醉酒驾驶 道路交通安全法 危险驾驶罪",
    }

    def __init__(self, dict_path: str | None = None):
        """加载可选 JSON 词典，并保留内置法律口语映射。"""
        self.synonym_map = dict(self.DEFAULT_SYNONYMS)
        self.entity_dict: set[str] = set()
        if dict_path and Path(dict_path).is_file() and Path(dict_path).suffix.lower() == ".json":
            payload = json.loads(Path(dict_path).read_text(encoding="utf-8"))
            self.synonym_map.update(payload.get("synonyms", {}))
            self.entity_dict.update(payload.get("entities", []))

    async def rewrite(self, user_query: str) -> RewriteResult:
        """扩展命中的口语表达，并抽取条号、法规名称和词典实体。"""
        query = re.sub(r"\s+", " ", user_query).strip()
        expansions = [value for key, value in self.synonym_map.items() if key in query]
        legal_query = " ".join(dict.fromkeys([query, *expansions]))
        entities = [entity for entity in self.entity_dict if entity in query]
        entities.extend(re.findall(r"《([^》]{1,100})》", query))
        entities.extend(re.findall(r"第[一二三四五六七八九十百千万零〇0-9]+条", query))
        for expansion in expansions:
            entities.extend(expansion.split())
        entities = list(dict.fromkeys(entities))
        keyword_query = " ".join(dict.fromkeys([query, *entities, *expansions]))
        return RewriteResult(
            original_query=query,
            legal_query=legal_query,
            keyword_query=keyword_query,
            entity_list=entities,
        )


class LLMQueryRewriter(BaseQueryRewriter):
    """阶段四预留的 LLM 查询重写适配器。"""

    def __init__(self, llm_client):
        """保存外部注入的 LLM 客户端。"""
        self.llm = llm_client

    async def rewrite(self, user_query: str) -> RewriteResult:
        """当前阶段不启用 LLM 重写，避免隐式模型调用。"""
        raise NotImplementedError("LLM 查询重写预留至阶段四")
