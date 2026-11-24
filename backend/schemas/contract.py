"""本文件定义合同审查任务接口的请求与响应结构。"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ContractReviewRequest(BaseModel):
    """创建合同审查任务请求。"""

    document_id: int
    contract_type: str = "other"
    review_level: str = "standard"
    review_dimensions: list[str] = ["legality", "fairness", "completeness"]


class ContractReviewTaskResponse(BaseModel):
    """合同审查任务创建响应。"""

    task_id: int
    document_id: int
    status: str

    model_config = ConfigDict(from_attributes=True)


class ContractRiskItem(BaseModel):
    """单条合同风险项。"""

    id: int
    task_id: int
    document_id: int
    clause_id: int | None
    article_no: str | None
    risk_level: str
    risk_type: str
    title: str
    description: str
    excerpt: str | None
    suggestion: str | None
    law_references: list[str] | None
    source: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ContractTaskStatusResponse(BaseModel):
    """合同审查任务进度查询响应。"""

    task_id: int
    document_id: int
    status: str
    progress: int = 0
    risk_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    error_message: str | None = None
    created_at: datetime | None = None
    finished_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ContractReviewResultResponse(BaseModel):
    """合同审查完整结果响应，包含风险列表与报告摘要。"""

    task_id: int
    document_id: int
    status: str
    risk_score: int = 0
    risks: list[ContractRiskItem] = []
    report: str | None = None
    contract_name: str | None = None
    parties: list[dict[str, str]] = []


class ContractDocumentResponse(BaseModel):
    """合同原文响应，供结果页左侧展示。直接上传审查模式下从 task_log.input_params 读取。"""

    task_id: int
    filename: str
    markdown: str
