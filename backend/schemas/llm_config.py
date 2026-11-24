"""本文件定义用户模型动态配置的请求与响应 Schema。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ModelConfigType = Literal["chat", "embedding", "rerank", "tavily"]


class SaveLlmConfigRequest(BaseModel):
    """保存或更新用户模型配置，api_key 为空时保留已保存密钥。"""

    config_type: ModelConfigType = Field(default="chat", description="配置类型: chat / embedding / rerank / tavily")
    provider: str = Field(min_length=1, description="模型 provider")
    model_name: str = Field(min_length=1, description="模型名")
    api_base: str = Field(default="", description="API base URL，为空时走 provider 默认")
    api_key: str | None = Field(default=None, description="明文 API Key，后端加密存储；为空时保留旧 Key")
    is_active: bool = Field(default=True, description="是否启用")
    temperature: float | None = Field(default=None, ge=0, le=2, description="温度覆盖，仅 chat 生效")
    max_tokens: int | None = Field(default=None, ge=1, description="max tokens 覆盖，仅 chat 生效")
    timeout: int | None = Field(default=None, ge=1, description="超时秒数覆盖")
    retry: int | None = Field(default=None, ge=0, description="重试次数覆盖")
    dimension: int | None = Field(default=None, ge=1, description="Embedding 向量维度，仅 embedding 生效")


class LlmConfigResponse(BaseModel):
    """用户模型配置响应，api_key 脱敏返回，不泄露明文。"""

    id: int
    config_type: ModelConfigType
    provider: str
    model_name: str
    api_base: str
    api_key_masked: str
    has_api_key: bool
    is_active: bool
    temperature: float | None = None
    max_tokens: int | None = None
    timeout: int | None = None
    retry: int | None = None
    dimension: int | None = None


class ProviderInfo(BaseModel):
    """单个 provider 元信息，供前端下拉选择和默认值填充。"""

    name: str
    label: str
    config_types: list[ModelConfigType] = Field(default_factory=list)
    default_api_base: str
    popular_models: list[str] = Field(default_factory=list)
    default_dimension: int | None = None
    requires_api_key: bool = True


class TestLlmConfigRequest(BaseModel):
    """测试模型配置可用性；可测试已保存配置或临时配置。"""

    config_type: ModelConfigType = Field(default="chat")
    provider: str | None = Field(default=None)
    model_name: str | None = Field(default=None)
    api_base: str | None = Field(default=None)
    api_key: str | None = Field(default=None, description="明文 Key；测试已保存配置时可不传")
    dimension: int | None = Field(default=None, description="Embedding 测试维度")


class TestLlmConfigResponse(BaseModel):
    """模型连通性测试结果。"""

    success: bool
    message: str
    latency_ms: int


class RuntimeModelConfigResponse(BaseModel):
    """模型运行时配置诊断响应,不返回明文 API Key。"""

    config_type: ModelConfigType
    provider: str
    model_name: str
    api_base: str
    has_api_key: bool
    dimension: int | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    timeout: int | None = None
    retry: int | None = None
    source: str
    source_config_id: int | None = None
    source_user_id: int | None = None
    document_id: int | None = None
    kb_id: int | None = None
    kb_embedding_model: str | None = None
    kb_rerank_model: str | None = None
    warnings: list[str] = Field(default_factory=list)
