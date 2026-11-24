"""本文件定义 Router 规则候选生成逻辑，规则只产出候选而不直接做最终决策。"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TypeAlias

from agent_service.router.models import Candidate, RouterInput

RuleCondition: TypeAlias = Callable[[str, RouterInput], bool]
RouterRule: TypeAlias = tuple[RuleCondition, str | None, float, str]

ARTICLE_PATTERN = re.compile(r"第[一二三四五六七八九十百千万零〇0-9]+条")
LAW_NAMES = ("民法典", "刑法", "劳动合同法", "劳动法", "公司法", "行政法", "行政处罚法", "民事诉讼法")
CONTRACT_REVIEW_KEYWORDS = ("审查", "风险", "条款问题", "看看合同", "合同有没有问题", "合同问题")
# 注意：含裸词"案例"，覆盖"热门案例/典型案例/案例检索"等；"案列"为常见错别字。
CASE_KEYWORDS = ("案例", "案列", "判例", "怎么判", "判决书", "裁判规则", "实际案件")
DOCUMENT_GENERATION_KEYWORDS = (
    "生成律师函", "法律意见书", "起草合同", "写一份律师函", "写律师函",
    "合同模板", "协议模板", "文书模板", "给我一份合同", "提供一份合同",
    "起草一份", "草拟一份", "拟一份", "起诉状", "起讼状", "答辩状",
    "上诉状", "反诉状", "仲裁申请书", "执行申请书",
)


def has_article_and_law(query: str, _: RouterInput) -> bool:
    """识别同时包含法律名称和具体条号的法条定位诉求。"""
    return bool(ARTICLE_PATTERN.search(query)) and any(name in query for name in LAW_NAMES)


def has_law_and_topic_query(query: str, _: RouterInput) -> bool:
    """识别法律名+主题查询（无具体条号），作为 article_locate 低分候选。"""
    if not any(name in query for name in LAW_NAMES):
        return False
    return any(word in query for word in ("规定", "条款", "内容", "关于", "适用"))


def has_uploaded_contract(_: str, ctx: RouterInput) -> bool:
    """识别会话中已经上传合同文件的审查场景。"""
    return any(file.get("doc_type") == "contract" for file in ctx.uploaded_files)


def has_contract_review_intent(query: str, _: RouterInput) -> bool:
    """识别用户明确要求审查合同或条款风险。"""
    return ("合同" in query and any(word in query for word in ("审查", "风险", "看看", "有没有问题"))) or any(
        word in query for word in CONTRACT_REVIEW_KEYWORDS
    )


def has_case_analysis_intent(query: str, _: RouterInput) -> bool:
    """识别案例检索、判例和裁判规则相关诉求。"""
    return any(word in query for word in CASE_KEYWORDS)


def is_document_generation_query(query: str) -> bool:
    """识别直接生成正式法律文书的请求，并兼容“起讼状”等常见错别字。"""
    normalized = query.replace("起讼状", "起诉状").replace("起诉书模板", "起诉状模板")
    return any(word in normalized for word in DOCUMENT_GENERATION_KEYWORDS)


def has_document_generation_intent(query: str, _: RouterInput) -> bool:
    """识别需要直接起草正式文书/模板的诉求。"""
    return is_document_generation_query(query)


def has_memory_continuation(_: str, ctx: RouterInput) -> bool:
    """识别多轮对话延续候选，具体 Agent 由 LLM 结合上下文确认。"""
    memory = ctx.legal_memory
    return bool(memory and (memory.current_case or memory.current_law))


ROUTER_RULES: list[RouterRule] = [
    (has_article_and_law, "article_locate", 0.8, "query 含法条编号+法律名"),
    (has_law_and_topic_query, "article_locate", 0.6, "query 含法律名+主题查询"),
    (has_uploaded_contract, "contract_review", 0.85, "已上传合同文件"),
    (has_contract_review_intent, "contract_review", 0.75, "用户明确要求审查合同或条款风险"),
    (has_case_analysis_intent, "case_analysis", 0.7, "案例检索关键词"),
    (has_document_generation_intent, "law_qa", 0.9, "正式文书生成，使用 law_qa 检索后按文书模式输出"),
    (has_memory_continuation, None, 0.5, "多轮延续（延续上一轮 agent）"),
]


def generate_candidates(router_input: RouterInput) -> list[Candidate]:
    """运行全部规则并返回按分数降序排列的候选列表。"""
    candidates: list[Candidate] = []
    query = router_input.user_query
    for condition, agent, score, reason in ROUTER_RULES:
        try:
            matched = condition(query, router_input)
        except Exception:
            matched = False
        if matched:
            candidates.append(Candidate(agent=agent, score=score, reason=reason))
    return sorted(candidates, key=lambda item: item.score, reverse=True)

