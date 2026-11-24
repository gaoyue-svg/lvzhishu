"""本文件实现 Router 低置信度、LLM 失败和字段异常时的兜底与校验策略。"""

from __future__ import annotations

import re
from typing import Any

from agent_service.router.models import (
    Candidate,
    FileRequirement,
    LegalContext,
    RetrievalScope,
    RouterDecision,
    RouterInput,
    TimeContext,
)
from agent_service.router.rules import is_document_generation_query

ALLOWED_DOMAINS = {"civil", "criminal", "administrative", "commercial"}
AGENT_DEFAULTS: dict[str, tuple[str, str, str]] = {
    "law_qa": ("legal_question", "rag", "low"),
    "article_locate": ("article_lookup", "rag", "low"),
    "contract_review": ("contract_review", "document_analysis", "medium"),
    "case_analysis": ("case_search", "multi_step", "medium"),
}
LAW_NAMES = ("民法典", "刑法", "劳动合同法", "劳动法", "公司法", "行政法", "行政处罚法", "民事诉讼法")
HIGH_RISK_KEYWORDS = ("杀人", "伤害", "自杀", "自残", "毒品", "赌博", "未成年", "学生", "校园", "暴力", "还手", "刑事")
LEGAL_KEYWORDS = (
    "违约金", "合同解除", "租赁", "漏水", "维修", "借款", "民间借贷", "正当防卫", "故意伤害",
    "加班", "劳动合同", "股权", "公司", "离婚", "抚养", "侵权", "赔偿", "律师函", "裁判规则",
)


def fallback_from_candidates(
    router_input: RouterInput,
    candidates: list[Candidate],
    *,
    reason: str,
) -> RouterDecision:
    """LLM 不可用或输出不可解析时，退回到最高分规则候选或 law_qa。"""
    best = _best_actionable_candidate(candidates)
    agent = best.agent if best else "law_qa"
    score = best.score if best else 0.5
    route_reason = f"{reason}: {best.reason}" if best else reason
    return build_default_decision(
        router_input,
        agent=agent,
        confidence=score,
        route_reason=route_reason,
        fallback=True,
    )


def low_confidence_fallback(router_input: RouterInput, decision: RouterDecision) -> RouterDecision:
    """当最终置信度过低时强制降级到最通用的 law_qa。"""
    return build_default_decision(
        router_input,
        agent="law_qa",
        confidence=min(decision.confidence, 0.5),
        route_reason=f"置信度低于阈值，降级到 law_qa；原路由: {decision.agent}",
        fallback=True,
    )


def build_default_decision(
    router_input: RouterInput,
    *,
    agent: str = "law_qa",
    confidence: float = 0.5,
    route_reason: str = "默认兜底到法律咨询",
    fallback: bool = False,
) -> RouterDecision:
    """按规则候选生成可运行的默认 RouterDecision。"""
    agent = agent if agent in AGENT_DEFAULTS else "law_qa"
    task_type, execution_mode, default_risk = AGENT_DEFAULTS[agent]
    if _has_document_generation_intent(router_input.user_query):
        task_type = "document_generation"
        agent = "law_qa"
        execution_mode = "rag"
        default_risk = "low"

    risk_level = "high" if _is_high_risk(router_input.user_query) else default_risk
    scope = infer_retrieval_scope(router_input.user_query)
    legal_context = infer_legal_context(router_input.user_query, scope.category)
    sub_questions = infer_sub_questions(router_input.user_query, agent)
    time_context = infer_time_context(router_input.user_query)
    need_file = agent == "contract_review"
    return RouterDecision(
        task_type=task_type,  # type: ignore[arg-type]
        agent=agent,  # type: ignore[arg-type]
        confidence=max(0.0, min(float(confidence), 0.95)),
        need_retrieval=True,
        retrieval_scope=scope,
        need_file=need_file,
        file_requirement=FileRequirement(type="contract", hint="请上传合同或相关条款文件") if need_file else None,
        legal_context=legal_context,
        sub_questions=sub_questions,
        time_context=time_context,
        execution_mode=execution_mode,  # type: ignore[arg-type]
        risk_level=risk_level,  # type: ignore[arg-type]
        route_reason=route_reason,
        fallback=fallback,
        needs_human_review=risk_level == "high",
    )


def apply_guardrails(
    decision: RouterDecision,
    router_input: RouterInput,
    *,
    confidence_threshold: float,
    confidence_max: float,
) -> RouterDecision:
    """统一修正 RouterDecision 的置信度上限、风险、人审和字段一致性。"""
    if decision.confidence < confidence_threshold:
        return low_confidence_fallback(router_input, decision)

    data = decision.model_dump()
    data["confidence"] = max(0.0, min(float(data["confidence"]), confidence_max, 0.95))
    data["risk_level"] = "high" if _is_high_risk(router_input.user_query) else data.get("risk_level") or "low"
    data["needs_human_review"] = bool(data.get("needs_human_review")) or data["risk_level"] == "high"

    agent = data["agent"]
    # 关键一致性：不同 Agent 的执行模式和文件需求必须稳定，避免后续编排分支跑偏。
    if agent in AGENT_DEFAULTS and data.get("task_type") != "document_generation":
        expected_task, expected_mode, expected_risk = AGENT_DEFAULTS[agent]
        data["task_type"] = expected_task
        data["execution_mode"] = expected_mode
        if data["risk_level"] != "high" and agent in {"contract_review", "case_analysis"}:
            data["risk_level"] = expected_risk

    if agent in {"article_locate", "contract_review"}:
        data["sub_questions"] = []

    data["need_file"] = agent == "contract_review" or bool(data.get("need_file"))
    if data["need_file"] and not data.get("file_requirement"):
        data["file_requirement"] = {"type": "contract", "hint": "请上传相关文件"}
    if not data["need_file"]:
        data["file_requirement"] = None

    scope = dict(data.get("retrieval_scope") or {})
    if scope.get("domain") not in ALLOWED_DOMAINS:
        scope["domain"] = "civil"
    scope.setdefault("category", "general")
    scope["keywords"] = list(scope.get("keywords") or [])
    data["retrieval_scope"] = scope

    legal_context = dict(data.get("legal_context") or {})
    legal_context.setdefault("law_name", None)
    legal_context.setdefault("article_no", None)
    legal_context.setdefault("cause_of_action", None)
    data["legal_context"] = legal_context

    time_context = dict(data.get("time_context") or {})
    if time_context.get("type") == "historical" and not time_context.get("year"):
        time_context = {"type": "current", "year": None}
    if time_context.get("type") not in {"latest", "current", "historical"}:
        time_context = {"type": "latest", "year": None}
    data["time_context"] = time_context
    data["route_reason"] = data.get("route_reason") or "Router 完成字段校验后输出决策"
    return RouterDecision.model_validate(data)


def infer_retrieval_scope(query: str) -> RetrievalScope:
    """从用户问题中抽取粗粒度检索范围建议。"""
    domain = "civil"
    if any(word in query for word in ("刑法", "刑事", "伤害", "正当防卫", "毒品", "赌博")):
        domain = "criminal"
    elif any(word in query for word in ("行政", "处罚", "复议", "许可")):
        domain = "administrative"
    elif any(word in query for word in ("公司", "股权", "商事", "破产")):
        domain = "commercial"

    category = "general"
    if any(word in query for word in ("合同", "违约", "租赁", "借款", "违约金")):
        category = "contract"
    elif any(word in query for word in ("侵权", "赔偿", "伤害")):
        category = "tort"
    elif any(word in query for word in ("离婚", "抚养", "婚姻")):
        category = "marriage"
    elif any(word in query for word in ("劳动", "加班", "工资")):
        category = "labor"
    elif any(word in query for word in ("公司", "股权")):
        category = "company"
    elif any(word in query for word in ("起诉", "仲裁", "律师函")):
        category = "procedure"

    keywords = [word for word in LEGAL_KEYWORDS if word in query]
    article = _extract_article_no(query)
    if article:
        keywords.append(article)
    return RetrievalScope(domain=domain, category=category, keywords=list(dict.fromkeys(keywords)))


def infer_legal_context(query: str, category: str) -> LegalContext:
    """抽取法律名称、条号和常见案由。"""
    law_name = next((name for name in LAW_NAMES if name in query), None)
    article_no = _extract_article_no(query)
    cause = None
    if category == "contract":
        cause = "合同纠纷"
    elif category == "labor":
        cause = "劳动争议"
    elif category == "marriage":
        cause = "婚姻家庭纠纷"
    elif category == "tort":
        cause = "侵权责任纠纷"
    return LegalContext(law_name=law_name, article_no=article_no, cause_of_action=cause)


def infer_time_context(query: str) -> TimeContext:
    """识别用户是否询问历史版本或现行最新规定。"""
    year_match = re.search(r"(20[0-9]{2})年", query)
    if year_match and any(word in query for word in ("当时", "历史", "旧", "之前", "以前", "那时")):
        return TimeContext(type="historical", year=int(year_match.group(1)))
    if any(word in query for word in ("现行", "现在", "当前")):
        return TimeContext(type="current", year=None)
    return TimeContext(type="latest", year=None)


def infer_sub_questions(query: str, agent: str) -> list[str]:
    """为法律咨询和案例分析生成轻量子问题，供后续多路检索使用。"""
    if agent not in {"law_qa", "case_analysis"}:
        return []
    if agent == "case_analysis":
        return [f"{query} 的裁判规则", f"{query} 的类似案例"]
    return [query]


def _best_actionable_candidate(candidates: list[Candidate]) -> Candidate | None:
    """忽略 agent=None 的延续提示，选择可执行的最高分候选。"""
    return next((candidate for candidate in candidates if candidate.agent), None)


def _extract_article_no(query: str) -> str | None:
    """抽取中文或数字法条编号。"""
    match = re.search(r"第[一二三四五六七八九十百千万零〇0-9]+条", query)
    return match.group(0) if match else None


def _is_high_risk(query: str) -> bool:
    """识别需要强制人工审核的高风险法律场景。"""
    return any(word in query for word in HIGH_RISK_KEYWORDS)


def _has_document_generation_intent(query: str) -> bool:
    """判断用户是否请求直接生成可使用的法律文书或模板。"""
    return is_document_generation_query(query)

