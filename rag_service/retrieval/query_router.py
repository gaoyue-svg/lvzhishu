"""本文件以规则识别检索意图、版本查询和 RRF 动态权重。"""

import re

from .models import QueryIntent


class QueryRouter:
    """判断法条定位、章节总结、案例分析、合同审查与一般法律问答。"""

    DEFAULT_RERANK_WEIGHTS = {
        "semantic": 0.45,
        "bm25": 0.30,
        "legal_level": 0.10,
        "chunk_level": 0.10,
        "freshness": 0.05,
    }

    async def route(self, user_query: str) -> QueryIntent:
        """根据关键词和条号模式返回意图、检索权重与过滤条件。"""
        query = user_query.strip()
        filters: dict[str, object] = {}
        year_match = re.search(r"((?:19|20)\d{2})\s*年?(?:版|当时|以前|原规定|旧法)?", query)
        historical = any(word in query for word in ("当时", "旧法", "原规定", "历史版本"))
        if historical or (year_match and "年" in query):
            filters["is_latest"] = None
            if year_match:
                filters["version"] = year_match.group(1)
        else:
            filters["is_latest"] = True

        if any(
            word in query
            for word in (
                "醉驾", "酒驾", "醉酒驾驶", "危险驾驶", "判刑", "刑事责任",
                "犯罪", "拘役", "有期徒刑", "死刑", "刑法",
            )
        ):
            filters["legal_domain"] = "criminal"

        if re.search(r"第[一二三四五六七八九十百千万零〇0-9]+条", query):
            return self._intent("article_lookup", {"bm25": 0.65, "semantic": 0.35}, filters, "article")
        if any(word in query for word in ("哪些规定", "有何规定", "总结", "结构", "体系", "章节", "哪几章", "哪几节")):
            return self._intent("chapter_summary", {"bm25": 0.35, "semantic": 0.65}, filters)
        if any(word in query for word in ("案例", "判决", "法院认为", "裁判", "案情")):
            return self._intent("case_analysis", {"bm25": 0.30, "semantic": 0.70}, filters)
        if any(word in query for word in ("合同审查", "条款", "甲方", "乙方", "违约金")):
            return self._intent("contract_review", {"bm25": 0.40, "semantic": 0.60}, filters)
        return self._intent("law_qa", {"bm25": 0.45, "semantic": 0.55}, filters)

    def _intent(
        self,
        name: str,
        weights: dict[str, float],
        filters: dict[str, object],
        chunk_level: str | None = None,
    ) -> QueryIntent:
        """统一构造意图并按需添加 Chunk 层级过滤。"""
        if chunk_level:
            filters = {**filters, "chunk_level": chunk_level}
        return QueryIntent(
            intent_type=name,
            weights=weights,
            rerank_weights=dict(self.DEFAULT_RERANK_WEIGHTS),
            filters=filters,
        )
