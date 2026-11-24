"""首页 Dashboard 聚合数据服务,按用户聚合会话、文档、知识库与使用趋势等数据。"""

from datetime import datetime, timedelta
import re

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.conversation import Conversation, Message
from backend.models.harness import QuestionTrace
from backend.models.knowledge import KnowledgeBase, KnowledgeDocument
from backend.models.task import RagTrace
from backend.models.user import User
from backend.schemas.dashboard import (
    ChartPoint,
    DashboardOverviewResponse,
    DocumentItem,
    PieSlice,
    QuickAction,
    RecentChat,
    SearchRecord,
    StatItem,
    SystemStatus,
)

# 静态快捷入口,后续可改为按用户角色动态返回。
_QUICK_ACTIONS: list[QuickAction] = [
    QuickAction(key="qa", title="AI智能问答", description="引用法条的专业问答", route="/assistant", icon="MessageCircle", tone="blue"),
    QuickAction(key="laws", title="法律法规", description="检索现行法规与条文", route="/laws", icon="Search", tone="green"),
    QuickAction(key="contract", title="合同审查", description="识别条款风险与建议", route="/assistant?scene=contract", icon="ShieldCheck", tone="violet"),
    QuickAction(key="doc", title="法律文书", description="生成诉状、函件与合同", route="/assistant?scene=document", icon="FileText", tone="amber"),
]

# 知识库类型到中文标签的映射,用于饼图展示。
_KB_TYPE_LABELS: dict[str, str] = {
    "law": "法规条文",
    "case": "裁判案例",
    "judicial": "司法解释",
    "contract": "合同模板",
    "enterprise": "内部文档",
}

_WEEKDAYS_CN: list[str] = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


async def build_dashboard_overview(
    db: AsyncSession,
    user: User,
    *,
    trend_days: int = 7,
) -> DashboardOverviewResponse:
    """聚合首页所需的所有数据。"""
    # AsyncSession 不支持并发查询,这里顺序执行各模块查询。
    recent_chats = await _get_recent_chats(db, user.id)
    recent_documents = await _get_recent_documents(db, user.id)
    search_records = await _get_search_records(db, user.id)
    knowledge_pie = await _get_knowledge_pie(db, user.id)
    kb_count = await _get_kb_count(db, user.id)
    activity_counts = await _get_activity_counts(db, user.id)
    usage_trend = await _get_usage_trend(db, user.id, days=trend_days)
    system_status = await _get_system_status(db, user.id)

    stats = _build_stats(
        kb_count=kb_count,
        ai_calls=activity_counts["ai_calls"],
        contracts=activity_counts["contracts"],
        documents=activity_counts["documents"],
        legal_searches=activity_counts["legal_searches"],
    )
    return DashboardOverviewResponse(
        user_name=user.username,
        stats=stats,
        quick_actions=_QUICK_ACTIONS,
        recent_chats=recent_chats,
        hot_laws=[],  # TODO: 接入检索日志后补齐热门法律排序
        recent_documents=recent_documents,
        search_records=search_records,
        announcements=[],  # TODO: 新增公告表后补齐系统公告
        system_status=system_status,
        usage_trend=usage_trend,
        knowledge_pie=knowledge_pie,
    )


def _build_stats(
    *, kb_count: int, ai_calls: int, contracts: int, documents: int, legal_searches: int
) -> list[StatItem]:
    """构造首页统计卡片列表。"""
    # trend 字段当前无法计算环比,先用占位字符串,后续接入历史聚合表后补齐。
    return [
        StatItem(key="aiCalls", label="AI调用次数", value=ai_calls, unit="次", trend="—", status="stable"),
        StatItem(key="knowledgeBases", label="知识库数量", value=kb_count, unit="个", trend="—", status="stable"),
        StatItem(
            key="legalDocuments",
            label="合同与文书",
            value=contracts + documents,
            unit="份",
            trend="—",
            status="stable",
        ),
        StatItem(
            key="legalSearches",
            label="法规检索次数",
            value=legal_searches,
            unit="次",
            trend="—",
            status="stable",
        ),
    ]


async def _get_system_status(db: AsyncSession, user_id: int) -> list[SystemStatus]:
    """根据当前用户的真实检索轨迹和文档状态构造系统状态。"""
    since = datetime.now() - timedelta(hours=24)
    rag_result = await db.execute(
        select(RagTrace.total_latency_ms).where(
            RagTrace.user_id == user_id,
            RagTrace.created_at >= since,
            RagTrace.final_context.is_not(None),
        )
    )
    rag_latencies = [int(value or 0) for value in rag_result.scalars().all()]

    document_result = await db.execute(
        select(KnowledgeDocument.parse_status, KnowledgeDocument.embedding_status).where(
            KnowledgeDocument.user_id == user_id
        )
    )
    documents = list(document_result.all())

    def status_counts(index: int, completed: set[str], active: set[str]) -> tuple[int, int, int, int, int]:
        statuses = [str(row[index] or "pending") for row in documents]
        done = sum(status in completed for status in statuses)
        running = sum(status in active for status in statuses)
        failed = sum(status in {"failed", "partial_failed"} for status in statuses)
        total = len(statuses)
        percent = round(done * 100 / total) if total else 0
        return total, done, running, failed, percent

    embedding_total, embedding_done, embedding_running, embedding_failed, embedding_percent = status_counts(
        1, {"completed"}, {"pending", "processing"}
    )
    parse_total, parse_done, parse_running, parse_failed, parse_percent = status_counts(
        0, {"completed"}, {"pending", "parsing"}
    )

    if rag_latencies:
        rag_description = f"近24小时完成 {len(rag_latencies)} 次，平均 {round(sum(rag_latencies) / len(rag_latencies))} ms"
        rag_value = 100
        rag_has_data = True
    else:
        rag_description = "近24小时暂无检索记录"
        rag_value = 0
        rag_has_data = False

    def queue_description(total: int, done: int, running: int, failed: int, empty: str) -> str:
        if total == 0:
            return empty
        return f"共 {total} 个文档：完成 {done}，处理中 {running}，失败 {failed}"

    return [
        SystemStatus(
            label="RAG检索",
            value=rag_value,
            description=rag_description,
            color="#16a34a",
            has_data=rag_has_data,
        ),
        SystemStatus(
            label="Embedding队列",
            value=embedding_percent,
            description=queue_description(
                embedding_total, embedding_done, embedding_running, embedding_failed, "暂无向量化文档"
            ),
            color="#2563eb",
            has_data=embedding_total > 0,
        ),
        SystemStatus(
            label="文档解析",
            value=parse_percent,
            description=queue_description(parse_total, parse_done, parse_running, parse_failed, "暂无解析文档"),
            color="#7c3aed",
            has_data=parse_total > 0,
        ),
    ]


async def _get_recent_chats(db: AsyncSession, user_id: int) -> list[RecentChat]:
    """读取当前用户最近 5 条活跃会话。"""
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id, Conversation.status == "active")
        .order_by(desc(Conversation.updated_at))
        .limit(5)
    )
    now = datetime.now()
    items: list[RecentChat] = []
    for conv in result.scalars().all():
        items.append(
            RecentChat(
                id=str(conv.id),
                title=conv.title,
                summary=conv.summary,
                time=_format_relative_time(conv.updated_at, now),
                category=_agent_type_label(conv.agent_type),
            )
        )
    return items


async def _get_recent_documents(db: AsyncSession, user_id: int) -> list[DocumentItem]:
    """读取当前用户最近 5 条文档。"""
    result = await db.execute(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.user_id == user_id)
        .order_by(desc(KnowledgeDocument.created_at))
        .limit(5)
    )
    now = datetime.now()
    items: list[DocumentItem] = []
    for doc in result.scalars().all():
        items.append(
            DocumentItem(
                id=str(doc.id),
                name=doc.filename,
                type=doc.file_type.upper(),
                status=_document_status_label(doc.parse_status, doc.embedding_status),
                updated_at=_format_relative_time(doc.created_at, now),
            )
        )
    return items


async def _get_search_records(db: AsyncSession, user_id: int) -> list[SearchRecord]:
    """读取法规检索页面最近 5 条真实历史记录。"""
    result = await db.execute(
        select(RagTrace)
        .where(RagTrace.user_id == user_id, RagTrace.agent_type == "legal_search")
        .order_by(desc(RagTrace.created_at))
        .limit(5)
    )
    now = datetime.now()
    records: list[SearchRecord] = []
    for trace in result.scalars().all():
        details = dict(trace.expanded_queries or {})
        intent = (details.get("query_intent") or {}).get("intent_type")
        records.append(
            SearchRecord(
                id=trace.trace_id,
                keyword=trace.original_query,
                scope=_retrieval_intent_label(intent),
                count=len(trace.reranked_results or []),
                time=_format_relative_time(trace.created_at, now),
            )
        )
    return records


def _retrieval_intent_label(intent: str | None) -> str:
    """把检索路由意图转换为首页可读标签。"""
    return {
        "article_locate": "法条定位",
        "chapter_summary": "章节检索",
        "law_qa": "法规问答",
        "case_search": "案例检索",
    }.get(intent or "", "智能检索")


async def _get_knowledge_pie(db: AsyncSession, user_id: int) -> list[PieSlice]:
    """按知识库类型聚合文档数量，饼图展示内容资产而非知识库个数。"""
    result = await db.execute(
        select(KnowledgeBase.kb_type, func.sum(KnowledgeBase.doc_count).label("c"))
        .where(KnowledgeBase.user_id == user_id)
        .group_by(KnowledgeBase.kb_type)
    )
    slices: list[PieSlice] = []
    for kb_type, count in result.all():
        label = _KB_TYPE_LABELS.get(kb_type, kb_type)
        slices.append(PieSlice(name=label, value=int(count)))
    return slices


async def _get_kb_count(db: AsyncSession, user_id: int) -> int:
    """统计当前用户知识库总数。"""
    result = await db.execute(
        select(func.count()).select_from(KnowledgeBase).where(KnowledgeBase.user_id == user_id)
    )
    return int(result.scalar_one() or 0)


async def _get_activity_counts(db: AsyncSession, user_id: int) -> dict[str, int]:
    """按真实回复、运行轨迹和用户意图统计首页业务指标。

    Conversation.agent_type 在 Supervisor 编排下统一为 ``supervisor``，不能再作为
    业务分类依据；否则所有统计都会长期为零。
    """
    ai_calls = await db.scalar(
        select(func.count())
        .select_from(Message)
        .where(Message.user_id == user_id, Message.role == "assistant")
    )
    contracts = await db.scalar(
        select(func.count())
        .select_from(QuestionTrace)
        .where(
            QuestionTrace.user_id == user_id,
            QuestionTrace.status == "success",
            QuestionTrace.intent.like("contract_review%"),
        )
    )
    legal_searches = await db.scalar(
        select(func.count())
        .select_from(RagTrace)
        .where(RagTrace.user_id == user_id, RagTrace.agent_type == "legal_search")
    )
    user_messages = await db.scalars(
        select(Message.content).where(Message.user_id == user_id, Message.role == "user")
    )
    return {
        "ai_calls": int(ai_calls or 0),
        "contracts": int(contracts or 0),
        "documents": sum(_is_document_generation_query(content) for content in user_messages),
        "legal_searches": int(legal_searches or 0),
    }


def _is_document_generation_query(query: str) -> bool:
    """识别起草、生成或索取模板类规范法律文书请求。"""
    normalized = re.sub(r"\s+", "", query or "")
    document_type = re.compile(
        r"民事起诉状|行政起诉状|刑事自诉状|离婚诉讼书|诉讼书|起诉状|起诉书|"
        r"答辩状|反诉状|上诉状|申诉书|劳动仲裁申请书|仲裁申请书|执行申请书|"
        r"财产保全申请书|申请书|劳动合同|合同|协议书|律师函|催告函|通知书|"
        r"授权委托书|委托书|遗嘱|借条|欠条|收据|法律意见书|举报信|投诉书"
    )
    intent = re.compile(
        r"帮我写|替我写|代写|写一份|起草|草拟|拟定|拟一份|撰写|编写|出具|"
        r"生成|制作|提供.{0,12}模板|给我.{0,12}模板|文书模板"
    )
    return bool(document_type.search(normalized) and intent.search(normalized))


async def _get_usage_trend(db: AsyncSession, user_id: int, *, days: int = 7) -> list[ChartPoint]:
    """聚合指定天数的问答、检索、合同审查与文书生成使用次数。"""
    if days not in (7, 14, 30):
        raise ValueError("usage trend days must be 7, 14 or 30")
    today = datetime.now()
    start = (today - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)

    # AI 问答按成功保存的 assistant 回复计数；Supervisor 会话类型不影响统计。
    answer_result = await db.execute(
        select(
            func.date(Message.created_at).label("d"),
            func.count().label("c"),
        )
        .where(Message.user_id == user_id, Message.role == "assistant", Message.created_at >= start)
        .group_by("d")
    )
    answer_map = {str(day): int(count) for day, count in answer_result.all()}

    # 仅统计法规检索页面产生的检索轨迹，避免把普通聊天中的 RAG 调用混入。
    retrieval_result = await db.execute(
        select(func.date(RagTrace.created_at).label("d"), func.count().label("c"))
        .where(
            RagTrace.user_id == user_id,
            RagTrace.agent_type == "legal_search",
            RagTrace.created_at >= start,
        )
        .group_by("d")
    )
    retrieval_map = {str(day): int(count) for day, count in retrieval_result.all()}

    # 合同审查使用 QuestionTrace 的最终意图，兼容 contract_review_upload。
    contract_result = await db.execute(
        select(func.date(QuestionTrace.created_at).label("d"), func.count().label("c"))
        .where(
            QuestionTrace.user_id == user_id,
            QuestionTrace.status == "success",
            QuestionTrace.intent.like("contract_review%"),
            QuestionTrace.created_at >= start,
        )
        .group_by("d")
    )
    contract_map = {str(day): int(count) for day, count in contract_result.all()}

    # 文书生成目前由 Supervisor 以 law_qa 运行，需从用户原始请求识别生成意图。
    document_result = await db.execute(
        select(Message.created_at, Message.content).where(
            Message.user_id == user_id,
            Message.role == "user",
            Message.created_at >= start,
        )
    )
    document_map: dict[str, int] = {}
    for created_at, content in document_result.all():
        if _is_document_generation_query(content):
            day_key = created_at.strftime("%Y-%m-%d")
            document_map[day_key] = document_map.get(day_key, 0) + 1

    points: list[ChartPoint] = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        day_str = day.strftime("%Y-%m-%d")
        points.append(
            ChartPoint(
                day=_day_label(day, today) if days == 7 else ("今天" if offset == 0 else day.strftime("%m-%d")),
                qa=answer_map.get(day_str, 0),
                retrieval=retrieval_map.get(day_str, 0),
                contract=contract_map.get(day_str, 0),
                document=document_map.get(day_str, 0),
            )
        )
    return points


def _day_label(dt: datetime, today: datetime) -> str:
    """把日期转成展示标签:今天显示'今天',其他显示中文星期。"""
    if dt.date() == today.date():
        return "今天"
    return _WEEKDAYS_CN[dt.weekday()]


def _format_relative_time(dt: datetime, now: datetime) -> str:
    """把 datetime 格式化为相对时间字符串。"""
    delta = now - dt
    if delta.days == 0:
        if delta.seconds < 60:
            return "刚刚"
        if delta.seconds < 3600:
            return f"{delta.seconds // 60}分钟前"
        return f"{delta.seconds // 3600}小时前"
    if delta.days == 1:
        return "昨天"
    if delta.days < 7:
        return f"{delta.days}天前"
    return dt.strftime("%Y-%m-%d")


def _agent_type_label(agent_type: str) -> str:
    """把 Agent 类型转成中文展示标签,用于最近会话的 category 字段。"""
    mapping = {
        "law_qa": "法律问答",
        "case_analysis": "案件分析",
        "contract_review": "合同审查",
        "article_locate": "法条定位",
        "document_generate": "文书生成",
    }
    return mapping.get(agent_type, agent_type)


def _document_status_label(parse_status: str, embedding_status: str) -> str:
    """把文档解析与向量化状态合并为前端展示状态。"""
    if parse_status == "failed":
        return "解析失败"
    if parse_status in ("pending", "parsing"):
        return "待审核"
    if embedding_status == "completed":
        return "解析完成"
    if embedding_status in ("processing", "pending"):
        return "Embedding中"
    if embedding_status in ("partial_failed", "failed"):
        return "部分失败"
    return "待审核"
