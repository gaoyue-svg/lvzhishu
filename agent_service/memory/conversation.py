"""会话短期记忆：最近消息窗口 + 可覆盖的结构化案件事实。"""

from __future__ import annotations

import asyncio
import re
from datetime import date
from typing import Any

from sqlalchemy import select

from agent_service.prompts import get_prompt
from agent_service.router.models import LegalMemory
from backend.models.conversation import Conversation, Message
from backend.utils.tokenizer import count_tokens, truncate_to_tokens


def _clip(text: str, limit: int) -> str:
    normalized = " ".join(str(text or "").split())
    return normalized if len(normalized) <= limit else normalized[:limit] + "…"


async def load_recent_history(
    db: Any,
    conversation_id: str,
    user_id: int,
    *,
    max_turns: int,
    max_tokens: int,
) -> str:
    """按用户和会话隔离读取最近消息，返回可直接注入 Prompt 的紧凑窗口。"""
    if not conversation_id or not str(conversation_id).isdigit():
        return ""
    owned = await db.scalar(
        select(Conversation.id).where(
            Conversation.id == int(conversation_id),
            Conversation.user_id == user_id,
        )
    )
    if owned is None:
        return ""
    rows = await db.scalars(
        select(Message)
        .where(Message.conversation_id == int(conversation_id))
        .order_by(Message.id.desc())
        .limit(max(1, max_turns) * 2)
    )
    messages = list(reversed(list(rows.all())))
    lines: list[str] = []
    for item in messages:
        role = "用户" if item.role == "user" else "助手" if item.role == "assistant" else "系统"
        # 用户原话优先保真；长篇助手答案只保留开头，避免挤掉关键事实。
        limit = 1600 if item.role == "user" else 700
        lines.append(f"{role}：{_clip(item.content, limit)}")
    # 按真实 token 从最新消息向前装载，避免中文场景下“字符数×2”近似偏差过大。
    selected: list[str] = []
    used = 0
    for line in reversed(lines):
        cost = count_tokens(line)
        if selected and used + cost > max_tokens:
            break
        selected.append(line if cost <= max_tokens else _tail_tokens(line, max_tokens))
        used += min(cost, max_tokens)
    return "\n".join(reversed(selected))


def enrich_legal_memory(
    existing: LegalMemory | dict[str, Any] | None,
    *,
    history_summary: str,
    current_query: str,
) -> dict[str, Any]:
    """从历史和当前输入提取稳定案件槽位；当前输入覆盖旧事实。"""
    if isinstance(existing, LegalMemory):
        payload = existing.model_dump(mode="json")
    else:
        payload = dict(existing or {})
    current_case = dict(payload.get("current_case") or {})
    # 历史窗口同时包含用户和助手消息。助手回答里的“若逃逸/若酒驾”等只是
    # 条件分析，绝不能反向写成用户案件事实；历史事实只从用户原话提取。
    user_history = _user_messages(history_summary)
    fact_source = "\n".join(part for part in (user_history, current_query) if part)

    # 清理由旧版本宽松关键词匹配造成的高风险布尔槽位污染。只有近期用户原话
    # 明确肯定或否定时才保留，宁可未知，也不能擅自认定逃逸、酒驾。
    for key in ("escaped", "drunk_driving"):
        if _extract_boolean_fact(fact_source, key) is None:
            current_case.pop(key, None)

    # 逐条用户消息提取，禁止把不同轮次的无关关键词拼接成一个事实条件。
    # 例如装修纠纷中的“临时租房”与后续“卫生间漏水”不能共同触发租赁纠纷。
    history_messages = [line.strip() for line in user_history.splitlines() if line.strip()]
    for text in (*history_messages, current_query):
        if not text:
            continue
        _extract_case_facts(text, current_case)
    if history_summary:
        current_case["recent_conversation"] = history_summary
    if current_case:
        payload["current_case"] = current_case
    payload.setdefault("current_law", None)
    payload.setdefault("citation_history", [])
    payload.setdefault("user_role", None)
    return payload


def _user_messages(history_summary: str) -> str:
    """从滚动上下文中只取用户消息，排除助手的假设、风险提示和检索结论。"""
    if not history_summary:
        return ""
    lines = []
    for line in history_summary.splitlines():
        stripped = line.strip()
        if stripped.startswith("用户："):
            lines.append(stripped.removeprefix("用户：").strip())
    # 兼容调用方传入没有角色标签的纯用户摘要。
    return "\n".join(lines) if lines else history_summary


def append_history(
    previous: str,
    *,
    query: str,
    answer: str,
    max_tokens: int,
) -> str:
    """把本轮写入滚动窗口，限制体积并保留最新内容。"""
    addition = f"用户：{_clip(query, 1600)}\n助手：{_clip(answer, 700)}"
    merged = f"{previous}\n{addition}".strip()
    return _tail_tokens(merged, max_tokens)


_SUMMARY_HEADER = "【长期案件摘要】"
_RECENT_HEADER = "【近期原文窗口】"


def split_memory_context(value: str) -> tuple[str, str]:
    """拆分模型长期摘要和近期原文；兼容升级前仅有滚动文本的 Redis 数据。"""
    text = str(value or "").strip()
    if _SUMMARY_HEADER not in text or _RECENT_HEADER not in text:
        return "", text
    summary_part, recent_part = text.split(_RECENT_HEADER, 1)
    return summary_part.removeprefix(_SUMMARY_HEADER).strip(), recent_part.strip()


def format_memory_context(summary: str, recent: str) -> str:
    """生成供 Router、Supervisor 和业务 Agent 共用的双层历史上下文。"""
    return f"{_SUMMARY_HEADER}\n{summary or '无'}\n{_RECENT_HEADER}\n{recent or '无'}".strip()


async def compress_history_with_llm(
    previous: str,
    *,
    query: str,
    answer: str,
    llm: Any,
    max_tokens: int,
    timeout: int,
    trigger_tokens: int | None = None,
    summary_tokens: int | None = None,
    recent_tokens: int | None = None,
) -> str:
    """维护“模型长期摘要 + 近期原文”记忆，总体严格受 token 预算约束。"""
    old_summary, recent = split_memory_context(previous)
    addition = f"用户：{_clip(query, 2400)}\n助手：{_clip(answer, 1200)}"
    recent = f"{recent}\n{addition}".strip()
    trigger_budget = min(max_tokens, trigger_tokens or max_tokens)
    summary_budget = min(max_tokens, summary_tokens or max(400, int(max_tokens * 0.35)))
    recent_budget = min(max_tokens, recent_tokens or max(600, int(max_tokens * 0.55)))
    # 给两个区块标题和分隔符预留空间；配置不合理时自动收缩近期窗口，避免越界。
    recent_budget = min(recent_budget, max(200, max_tokens - summary_budget - 200))

    combined = format_memory_context(old_summary, recent)
    if count_tokens(combined) <= trigger_budget:
        return combined

    older_recent, recent_tail = _split_tail_tokens(recent, recent_budget)
    source = "\n".join(part for part in (old_summary, older_recent) if part).strip()
    source = truncate_to_tokens(source, max_tokens * 2)
    summary = old_summary
    if source and llm is not None:
        try:
            summary = await asyncio.wait_for(
                llm.chat(
                    [
                        {
                            "role": "system",
                            "content": get_prompt("memory_summary_system"),
                        },
                        {
                            "role": "user",
                            "content": f"已有摘要与待压缩历史如下：\n{source}",
                        },
                    ],
                    temperature=0.1,
                    max_tokens=summary_budget,
                ),
                timeout=max(5, timeout),
            )
        except Exception:
            # 摘要模型故障不能阻断主回答；退化为确定性截断，近期原文仍完整保留。
            summary = truncate_to_tokens(source, summary_budget)
    summary = truncate_to_tokens(str(summary or "").strip(), summary_budget)
    result = format_memory_context(summary, recent_tail)
    return truncate_to_tokens(result, max_tokens)


def _split_tail_tokens(text: str, max_tokens: int) -> tuple[str, str]:
    """把文本按 token 切成“较早部分、最新窗口”，优先使用 tiktoken。"""
    if count_tokens(text) <= max_tokens:
        return "", text
    try:
        import tiktoken

        encoding = tiktoken.get_encoding("cl100k_base")
        tokens = encoding.encode(text)
        return encoding.decode(tokens[:-max_tokens]), encoding.decode(tokens[-max_tokens:])
    except Exception:
        split_at = max(0, len(text) - max_tokens * 2)
        return text[:split_at], text[split_at:]


def _tail_tokens(text: str, max_tokens: int) -> str:
    return _split_tail_tokens(text, max_tokens)[1]


def _extract_case_facts(text: str, target: dict[str, Any]) -> None:
    """提取高置信度显式事实；不对模糊内容做推断。"""
    patterns = {
        # 只接受陈述句，避免“我叫什么/对方叫什么/发生在哪里”把已经记住的事实覆盖掉。
        "user_name": r"我叫(?!什么|啥|谁)\s*([^，。；;？！?\n]{1,20})",
        "counterparty_name": r"对方叫(?!什么|啥|谁)\s*([^，。；;？！?\n]{1,20})",
        "location": r"(?:事故)?发生在(?!哪里|哪儿|什么地方)\s*([^，。；;？！?\n]{1,30})",
        "liability": r"我(?:被认定)?负\s*(全部|主要|同等|次要|无)责任",
    }
    for key, pattern in patterns.items():
        matches = re.findall(pattern, text)
        if matches:
            target[key] = matches[-1].strip()
    if "交通事故" in text or "事故发生" in text:
        target["event_type"] = "交通事故"
    if re.search(r"我(?:开车|驾驶(?:机动车)?)?[^，。；;？！?\n]{0,12}(?:撞到|撞了|碰到)[^，。；;？！?\n]{0,12}(?:骑)?电动车", text):
        target["event_type"] = "交通事故"
        target["user_vehicle_type"] = "机动车"
        target["counterparty_vehicle_type"] = "电动车"
    if re.search(r"对方(?:只是|仅是|为)?\s*(轻伤|轻微伤|重伤)", text):
        target["counterparty_injury_description"] = re.findall(
            r"对方(?:只是|仅是|为)?\s*(轻伤|轻微伤|重伤)", text
        )[-1]
    for key in ("escaped", "drunk_driving"):
        value = _extract_boolean_fact(text, key)
        if value is not None:
            target[key] = value

    # 劳动争议多轮事实：只记录用户明确说出的稳定事实，供“还能仲裁吗/去年12月离职”
    # 这类省略主语的追问续接使用。
    if (
        "欠薪" in text
        or "拖欠工资" in text
        or ("工资" in text and any(word in text for word in ("拖欠", "没发", "未发", "不发", "不给", "没给", "克扣", "少发")))
    ):
        target["labor_dispute_topic"] = "wage_arrears"
    if re.search(r"(?:我|本人)?(?:已经|已|正式)?离职(?:了|的)?|我是.+离职的", text):
        target["employment_ended"] = True
    if "仲裁" in text:
        target["labor_arbitration_question"] = True

    salary_match = re.search(r"月工资\s*(\d+(?:\.\d+)?)\s*(万)?\s*元", text)
    if salary_match:
        salary_value = float(salary_match.group(1)) * (10000 if salary_match.group(2) else 1)
        target["monthly_salary_yuan"] = int(salary_value)
    work_year_match = re.search(r"(?:工作|工龄)\s*(\d+(?:\.\d+)?)\s*年", text)
    if work_year_match:
        target["work_years"] = float(work_year_match.group(1))
    arrears_month_match = re.search(
        r"(?:拖欠|欠|没发|未发)[^，。；;？！?\n]{0,8}([一二两三四五六七八九十\d]+)\s*个?月(?:工资)?",
        text,
    )
    if arrears_month_match:
        chinese_numbers = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
                           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        raw_months = arrears_month_match.group(1)
        target["wage_arrears_months"] = int(raw_months) if raw_months.isdigit() else chinese_numbers.get(raw_months)
    if any(word in text for word in ("辞退", "开除", "解除劳动合同")):
        target["employment_ended"] = True
        target["employment_termination_event"] = True

    today = date.today()
    relative = re.search(r"去年\s*(\d{1,2})\s*月(?:[^，。；;？！?\n]{0,12})?离职", text)
    explicit = re.search(r"(20\d{2})\s*年\s*(\d{1,2})\s*月(?:[^，。；;？！?\n]{0,12})?离职", text)
    if relative:
        target["employment_ended"] = True
        target["employment_end_year"] = today.year - 1
        target["employment_end_month"] = int(relative.group(1))
        target["employment_end_date_text"] = f"{today.year - 1}年{int(relative.group(1))}月（具体日期待确认）"
    elif explicit:
        target["employment_ended"] = True
        target["employment_end_year"] = int(explicit.group(1))
        target["employment_end_month"] = int(explicit.group(2))
        target["employment_end_date_text"] = f"{int(explicit.group(1))}年{int(explicit.group(2))}月（具体日期待确认）"

    # 装修合同纠纷。明确的装修合同/装修公司事实属于强主题信号，一经确认，
    # 后续出现“临时租房、漏水、返工”等词也不能把案件改判成房屋租赁纠纷。
    renovation_signal = (
        any(word in text for word in ("装修合同", "装修公司", "装修新房", "装修工程"))
        and any(word in text for word in ("签", "合同", "施工", "完工", "工程款", "装修"))
    )
    if renovation_signal:
        target["civil_dispute_topic"] = "renovation_contract"
        target["renovation_user_role"] = "owner"
    renovation_context = target.get("civil_dispute_topic") == "renovation_contract"
    if renovation_context:
        company = re.search(r"(?:找|与|由)?\s*([^，。；;？！?\s]{2,24}(?:装饰|装修)[^，。；;？！?\s]{0,12}(?:有限公司|公司))", text)
        if company:
            company_name = re.sub(r"^(?:我找|我与|我和|找|与|由)", "", company.group(1))
            target["renovation_company_name"] = company_name
        total = re.search(r"(?:合同)?总(?:价|金额)\s*(\d+(?:\.\d+)?)\s*万\s*元", text)
        if total:
            target["renovation_contract_total_yuan"] = int(float(total.group(1)) * 10000)
        paid = re.search(r"(?:已|已经)?(?:分[一二两三四五六七八九十\d]+次)?支付(?:了)?\s*(\d+(?:\.\d+)?)\s*万\s*元", text)
        if paid:
            target["renovation_paid_yuan"] = int(float(paid.group(1)) * 10000)
        payment_count = re.search(r"分\s*([一二两三四五六七八九十\d]+)\s*次支付", text)
        if payment_count:
            nums = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
            raw = payment_count.group(1)
            target["renovation_payment_count"] = int(raw) if raw.isdigit() else nums.get(raw)

        signed = re.search(r"(?:今年)?\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日(?:签约|签订|签了)", text)
        due = re.search(r"(?:约定|合同约定)?\s*(?:今年)?\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日(?:前)?完工", text)
        if signed:
            target["renovation_contract_sign_date"] = f"{date.today().year:04d}-{int(signed.group(1)):02d}-{int(signed.group(2)):02d}"
        if due:
            target["renovation_completion_due_date"] = f"{date.today().year:04d}-{int(due.group(1)):02d}-{int(due.group(2)):02d}"
        progress = re.search(
            r"(?:到)?\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日[^，。；;？！?\n]{0,24}"
            r"(?:完成|进度)[^，。；;？！?\n\d]{0,8}(\d{1,3})\s*%",
            text,
        )
        if progress:
            target["renovation_progress_date"] = f"{date.today().year:04d}-{int(progress.group(1)):02d}-{int(progress.group(2)):02d}"
            target["renovation_progress_percent"] = int(progress.group(3))
        demand = re.search(r"(?:我在)?\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日[^，。；;？！?\n]{0,12}(?:微信|EMS)[^，。；;？！?\n]{0,8}催告", text)
        if demand:
            target["renovation_demand_date"] = f"{date.today().year:04d}-{int(demand.group(1)):02d}-{int(demand.group(2)):02d}"
            target["renovation_demand_methods"] = [method for method in ("微信", "EMS") if method in text]
        promised = re.search(r"承诺(?:在|延期至)?\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日(?:前)?完(?:工|成)", text)
        if promised:
            target["renovation_promised_completion_date"] = f"{date.today().year:04d}-{int(promised.group(1)):02d}-{int(promised.group(2)):02d}"
        still_incomplete = re.search(r"(?:到)?\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日[^，。；;？！?\n]{0,12}(?:还是|仍|依然)?没有完工", text)
        if still_incomplete:
            target["renovation_still_incomplete_as_of"] = f"{date.today().year:04d}-{int(still_incomplete.group(1)):02d}-{int(still_incomplete.group(2)):02d}"
        rent_loss = re.search(r"(?:临时租房|租房)(?:花了|费用(?:为|是)?|损失(?:为|是)?)?\s*(\d+(?:\.\d+)?)\s*元", text)
        if rent_loss:
            target["temporary_rent_loss_yuan"] = int(float(rent_loss.group(1)))
        repair_estimate = re.search(
            r"(?:返工|修复)[^，。；;？！?\n\d]{0,16}(\d+(?:\.\d+)?)\s*元",
            text,
        )
        if repair_estimate:
            target["renovation_repair_estimate_yuan"] = int(float(repair_estimate.group(1)))
        if "卫生间" in text and any(word in text for word in ("防水没做好", "漏水", "渗水")):
            target["renovation_quality_defect"] = "卫生间防水不合格并渗漏"
        if "楼下" in text and any(word in text for word in ("渗水", "受损", "墙面损失", "赔偿")):
            target["renovation_downstairs_damage"] = True
        if "第三方检测报告" in text:
            target["renovation_third_party_report"] = True
        if "工人不足" in text and "不可抗力" in text:
            target["renovation_force_majeure_defense"] = "装修公司以工人不足主张不可抗力"
        if any(word in text for word in ("解除合同", "返还多收", "返还工程款", "赔偿临时租房费", "返工费")):
            target["renovation_termination_or_settlement_requested"] = True

    # 房屋租赁维修纠纷：后续“催过三次/有微信记录”通常省略房东、漏水等主语，
    # 必须依靠结构化案件类型续接，避免被错误改写成借款催收。
    rental_context = target.get("civil_dispute_topic") == "residential_lease_repair"
    if (not renovation_context and
        any(word in text for word in ("租的房子", "租房", "承租", "出租人", "房东"))
        and any(word in text for word in ("漏水", "渗水", "维修", "修理", "不修"))
    ):
        target["civil_dispute_topic"] = "residential_lease_repair"
        target["lease_user_role"] = "tenant"
        rental_context = True
    if rental_context and any(word in text for word in ("漏水", "渗水")):
        target["rental_defect"] = "房屋漏水"
    if rental_context and re.search(
        r"(?:房东|出租人)[^，。；;？！?\n]{0,12}(?:不修|不维修|拒绝维修|一直没修|一直没有维修|仍未维修)",
        text,
    ):
        target["landlord_repair_status"] = "经通知仍未维修"

    if rental_context:
        landlord_name = re.search(r"房东(?:叫|是|姓名为?)\s*([^，。；;？！?\s]{1,12})", text)
        if landlord_name:
            extracted_name = landlord_name.group(1)
            # “房东叫什么/房东是谁”是回忆问题，疑问词绝不能覆盖已保存姓名。
            if extracted_name not in {"什么", "谁", "哪位", "哪个", "何人"}:
                target["landlord_name"] = extracted_name

        # “第一次是3月1日/第二次是3月10日”属于同一催修时间线。后续轮次往往
        # 省略“房东、漏水、催修”等主语，必须用序号把日期写入稳定案件记忆。
        ordinal_numbers = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
                           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        notice_dates = dict(target.get("repair_notice_dates") or {})
        notice_date_pattern = re.compile(
            r"第\s*([一二两三四五六七八九十\d]+)\s*次"
            r"(?:催修|催告|通知|联系)?\s*(?:是|在|为)?\s*"
            r"(今年)?\s*(?:(20\d{2})\s*年)?\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
        )
        for match in notice_date_pattern.finditer(text):
            raw_order, this_year, explicit_year, month, day = match.groups()
            order = int(raw_order) if raw_order.isdigit() else ordinal_numbers.get(raw_order)
            if order is None:
                continue
            if explicit_year:
                year = int(explicit_year)
            elif this_year:
                year = date.today().year
            else:
                year = int(target.get("repair_notice_year") or date.today().year)
            try:
                notice_date = date(year, int(month), int(day))
            except ValueError:
                continue
            notice_dates[str(order)] = notice_date.isoformat()
            target["repair_notice_year"] = year
            target["repair_notice_count"] = max(int(target.get("repair_notice_count") or 0), order)
        if notice_dates:
            target["repair_notice_dates"] = notice_dates

        notice_count = re.search(r"(?:催|通知|联系)(?:过|了)?\s*([一二两三四五六七八九十\d]+)\s*次", text)
        if notice_count:
            chinese_numbers = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
                               "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
            raw_count = notice_count.group(1)
            target["repair_notice_count"] = int(raw_count) if raw_count.isdigit() else chinese_numbers.get(raw_count)
        reverse_notice_count = re.search(r"([一二两三四五六七八九十\d]+)\s*次(?:催修|催告|通知|联系)记录", text)
        if reverse_notice_count:
            raw_count = reverse_notice_count.group(1)
            target["repair_notice_count"] = int(raw_count) if raw_count.isdigit() else ordinal_numbers.get(raw_count)
            target["repair_notice_evidence"] = f"{target['repair_notice_count']}次催修记录"
        if "微信" in text and any(word in text for word in ("聊天记录", "记录", "催", "通知", "联系")):
            target["repair_notice_evidence"] = "微信聊天记录"
        if re.search(r"(?:漏水|渗水)[^，。；;？！?\n]{0,12}(?:导致|造成)[^，。；;？！?\n]{0,8}电脑(?:损坏|进水|故障)", text):
            target["property_damage_cause"] = "房屋漏水"
            target["damaged_property"] = "电脑"
            target["property_damage_confirmed"] = True
        repair_cost = re.search(
            r"电脑(?:维修|修理)(?:花了|花费|费用(?:是|为)?|费(?:是|为)?)?\s*(\d+(?:\.\d+)?)\s*元",
            text,
        )
        if repair_cost:
            amount = int(float(repair_cost.group(1)))
            target["property_repair_cost_yuan"] = amount
            target["property_repair_cost_text"] = f"电脑维修费{amount}元"
        if "维修发票" in text or ("发票" in text and target.get("property_repair_cost_yuan")):
            target["property_repair_invoice"] = True
        if target.get("property_damage_cause") == "房屋漏水" and target.get("property_repair_cost_yuan"):
            target["property_loss_claim_text"] = f"漏水导致电脑损坏，维修费{target['property_repair_cost_yuan']}元"
        if any(word in text for word in ("卧室无法居住", "房间无法居住", "无法居住", "不能居住")):
            target["rental_habitability_impact"] = "租赁房屋部分或全部无法居住"
        if any(word in text for word in ("解除合同", "解除租赁", "退租")):
            target["tenant_seeks_termination"] = True
        if any(word in text for word in ("押金", "剩余租金", "预付租金", "退租金", "返还租金")):
            target["lease_settlement_question"] = True

    # 民间借贷诉讼时效多轮事实。金额、约定还款日、债务承认及新的履行承诺
    # 必须进入结构化记忆，不能只依赖模型从长篇历史中临时查找。
    loan_signals = ("借给", "借款", "借条", "欠钱", "欠款", "还款")
    if any(signal in text for signal in loan_signals):
        target["civil_dispute_topic"] = "private_lending"

    amount_matches = re.findall(
        r"(?:借给|借了|借款(?:本金)?(?:为|是)?|欠(?:我)?)(?:朋友|对方|他|她)?\s*"
        r"(\d+(?:\.\d+)?)\s*(万)?\s*元",
        text,
    )
    if amount_matches:
        number, unit = amount_matches[-1]
        target["loan_amount_text"] = f"{number}{unit or ''}元"
        target["loan_amount_yuan"] = int(float(number) * (10000 if unit else 1))

    due_matches = re.findall(
        r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*(前|之前)?(?:应当|应该|必须|要)?\s*还(?:款|钱)?",
        text,
    )
    if due_matches:
        year, month, day, before = due_matches[-1]
        target["loan_due_date_iso"] = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
        target["loan_due_date_text"] = f"{int(year)}年{int(month)}月{int(day)}日{'前' if before else ''}还款"

    acknowledgement_sentence = next((
        sentence for sentence in re.split(r"[。；;？！?\n]", text)
        if re.search(
            r"(?:他|她|对方|借款人)[^，]{0,12}(?:通过)?微信[^，]{0,12}"
            r"(?:承认|确认|认可)[^，]{0,8}(?:欠钱|欠款|借款|债务)",
            sentence,
        )
    ), "")
    acknowledgement = bool(acknowledgement_sentence)
    if acknowledgement:
        target["debtor_acknowledged_debt"] = True
        target["debt_acknowledgment_channel"] = "微信"
        relative_year = re.search(r"去年", acknowledgement_sentence)
        explicit_year = re.search(r"(20\d{2})\s*年", acknowledgement_sentence)
        if explicit_year:
            target["debt_acknowledgment_date_text"] = f"{int(explicit_year.group(1))}年（具体日期待确认）"
        elif relative_year:
            target["debt_acknowledgment_date_text"] = f"{today.year - 1}年（具体日期待确认）"

    promise = re.search(
        r"(?:他说|她说|对方说|借款人说|还说|并说|承诺|答应)[^，。；;？！?\n]{0,12}"
        r"((?:今年|明年|去年)?\s*年底[^，。；;？！?\n]{0,8}(?:还|还款|还钱))",
        text,
    )
    if promise:
        target["debtor_promised_repayment"] = True
        target["repayment_promise_text"] = promise.group(1).strip()
        if "明年" in promise.group(1):
            promise_year = today.year + 1
        elif "去年" in promise.group(1):
            promise_year = today.year - 1
        elif "今年" in promise.group(1):
            promise_year = today.year
        elif "去年" in text:
            # “去年……还说年底一定还”中的“年底”承接去年，不擅自补具体日期。
            promise_year = today.year - 1
        else:
            promise_year = None
        target["repayment_promise_deadline_text"] = (
            f"{promise_year}年年底（具体日期待确认）" if promise_year else "年底（年份及具体日期待确认）"
        )


def _extract_boolean_fact(text: str, key: str) -> bool | None:
    """只识别用户对自身行为的明确陈述；法律术语、条件句和提问均返回未知。"""
    if not text:
        return None
    if key == "escaped":
        negative = r"(?:我|本人)?(?:没有|并未|未曾|未)\s*(?:肇事)?逃逸"
        positive = r"(?:我|本人)(?:确实|已经|存在|有|发生了)?\s*(?:肇事)?逃逸(?:了|行为|情节)?"
    else:
        negative = r"(?:我|本人)?(?:没有|并未|未曾|未)(?:[^，。；;？！?\n]{0,8}(?:和|及|也没有|并且没有))?\s*(?:酒驾|醉驾|饮酒驾驶)"
        positive = r"(?:我|本人)(?:确实|已经|存在|有)?\s*(?:酒驾|醉驾|饮酒驾驶)(?:了|行为|情节)?"
    # 明确否定优先，防止“我没有逃逸”被肯定式中的“我…逃逸”误伤。
    if re.search(negative, text):
        return False
    if re.search(positive, text):
        return True
    return None
