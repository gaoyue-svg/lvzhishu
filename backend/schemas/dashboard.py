"""首页 Dashboard 聚合接口的响应 Schema,字段命名与前端 types/dashboard.ts 完全对齐。"""

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class _CamelModel(BaseModel):
    """字段名序列化为 camelCase 的基类,与前端命名习惯对齐。"""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class StatItem(_CamelModel):
    """统计卡片项。"""

    key: str
    label: str
    value: int
    unit: str
    trend: str
    status: str = Field(pattern="^(up|down|stable)$")


class QuickAction(_CamelModel):
    """快捷入口项。"""

    key: str
    title: str
    description: str
    route: str
    icon: str
    tone: str = Field(pattern="^(blue|green|violet|amber)$")


class RecentChat(_CamelModel):
    """最近会话项。"""

    id: str
    title: str
    summary: str | None = None
    time: str
    category: str


class LawItem(_CamelModel):
    """热门法律项。"""

    id: str
    title: str
    authority: str
    effective_date: str
    tag: str


class DocumentItem(_CamelModel):
    """最近文档项。"""

    id: str
    name: str
    type: str
    status: str
    updated_at: str


class SearchRecord(_CamelModel):
    """检索记录项。"""

    id: str
    keyword: str
    scope: str
    count: int
    time: str


class Announcement(_CamelModel):
    """系统公告项。"""

    id: str
    title: str
    content: str
    level: str = Field(pattern="^(info|warning)$")


class SystemStatus(_CamelModel):
    """系统状态项。"""

    label: str
    value: int
    description: str
    color: str
    has_data: bool = True


class ChartPoint(_CamelModel):
    """使用趋势数据点。"""

    day: str
    qa: int
    retrieval: int
    contract: int
    document: int


class PieSlice(_CamelModel):
    """知识库分布饼图项。"""

    name: str
    value: int


class DashboardOverviewResponse(_CamelModel):
    """首页聚合数据响应。"""

    user_name: str
    stats: list[StatItem]
    quick_actions: list[QuickAction]
    recent_chats: list[RecentChat]
    hot_laws: list[LawItem]
    recent_documents: list[DocumentItem]
    search_records: list[SearchRecord]
    announcements: list[Announcement]
    system_status: list[SystemStatus]
    usage_trend: list[ChartPoint]
    knowledge_pie: list[PieSlice]
