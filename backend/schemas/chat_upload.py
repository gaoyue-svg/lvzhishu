"""会话临时上传文件相关请求/响应 Schema。"""

from typing import Any

from pydantic import BaseModel, Field


class ChatUploadResponse(BaseModel):
    """上传成功后的文件引用信息，供前端随对话请求携带。"""

    upload_id: str = Field(description="上传ID")
    filename: str = Field(description="原始文件名")
    file_type: str = Field(description="文件类型")
    doc_type: str = Field(default="contract", description="业务文档类型")
    parse_status: str = Field(description="解析状态: pending / parsing / completed / failed")
    char_count: int = Field(default=0, description="解析字符数")
    clause_count: int = Field(default=0, description="合同条款数量")
    parse_warnings: list[str] = Field(default_factory=list, description="解析降级提示")
    error_message: str | None = Field(default=None, description="解析失败原因")
