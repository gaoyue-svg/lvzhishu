"""本文件定义 Router Agent 输入、候选、决策与法律记忆的数据结构。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

AgentType = Literal["law_qa", "article_locate", "contract_review", "case_analysis"]
TaskType = Literal[
    "legal_question",
    "article_lookup",
    "contract_review",
    "case_search",
    "document_generation",
]
ExecutionMode = Literal["rag", "multi_step", "document_analysis"]
RiskLevel = Literal["low", "medium", "high"]
# 放宽为 str，让 apply_guardrails 对 LLM 输出的非法 type 做降级，
# 否则 Pydantic 会直接拒绝整个 RouterDecision，丢失 LLM 判定。
TimeType = str


class LegalMemory(BaseModel):
    """结构化法律记忆，帮助 Router 理解多轮对话中的省略信息。"""

    current_case: dict[str, Any] | None = None
    current_law: dict[str, Any] | None = None
    citation_history: list[dict[str, Any]] = Field(default_factory=list)
    user_role: str | None = None


class RouterInput(BaseModel):
    """Router 决策所需的用户输入、身份、记忆、文件和知识库上下文。"""

    user_query: str
    conversation_id: str = ""
    user_id: str = ""
    tenant_id: str = ""
    history_summary: str | None = None
    legal_memory: LegalMemory | None = None
    uploaded_files: list[dict[str, Any]] = Field(default_factory=list)
    available_kbs: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("user_query")
    @classmethod
    def validate_user_query(cls, value: str) -> str:
        """拒绝空问题，避免 Router 生成无意义决策。"""
        normalized = value.strip()
        if not normalized:
            raise ValueError("user_query 不能为空")
        return normalized


class Candidate(BaseModel):
    """规则候选项；agent 为空表示建议延续上一轮业务 Agent。"""

    agent: AgentType | None
    score: float = Field(ge=0.0, le=1.0)
    reason: str


class RetrievalScope(BaseModel):
    """检索范围建议，只包含领域、类别和关键词，不绑定具体知识库。"""

    domain: str = "civil"
    category: str = "general"
    keywords: list[str] = Field(default_factory=list)


class FileRequirement(BaseModel):
    """文件需求提示，供合同审查等 Agent 引导用户补充材料。"""

    type: str = "contract"
    hint: str = "请上传相关文件"


class LegalContext(BaseModel):
    """法律实体上下文，供后续检索和推理节点约束范围。"""

    law_name: str | None = None
    article_no: str | None = None
    cause_of_action: str | None = None


class TimeContext(BaseModel):
    """时间上下文，影响后续检索是否只看最新有效版本。"""

    type: TimeType = "latest"
    year: int | None = None


class RouterDecision(BaseModel):
    """Router 最终输出的结构化路由决策。"""

    task_type: TaskType
    agent: AgentType
    # 放宽到 1.0，让 apply_guardrails 统一 clamp 到 0.95；
    # 否则 LLM 输出 0.96 会直接抛 ValidationError 丢失判定。
    confidence: float = Field(ge=0.0, le=1.0)
    need_retrieval: bool = True
    retrieval_scope: RetrievalScope = Field(default_factory=RetrievalScope)
    need_file: bool = False
    file_requirement: FileRequirement | None = None
    legal_context: LegalContext = Field(default_factory=LegalContext)
    sub_questions: list[str] = Field(default_factory=list)
    time_context: TimeContext = Field(default_factory=TimeContext)
    execution_mode: ExecutionMode = "rag"
    risk_level: RiskLevel = "low"
    route_reason: str = ""
    fallback: bool = False
    needs_human_review: bool = False

