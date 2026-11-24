"""本文件定义用户模型配置 ORM 模型，用于持久化 Chat、Embedding 与 Rerank 的动态 BYOK 配置。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Index, Integer, SmallInteger, String, text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models import Base


class UserLlmConfig(Base):
    """用户模型配置表，一个用户可分别配置 chat、embedding、rerank 三类模型。"""

    __tablename__ = "user_llm_config"
    __table_args__ = (
        Index("uk_user_llm_config_type", "user_id", "config_type", unique=True),
        {"comment": "用户模型配置表(BYOK)"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="主键ID")
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="用户ID")
    config_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=sql_text("'chat'"),
        comment="配置类型: chat / embedding / rerank",
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False, comment="模型 provider")
    model_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="模型名")
    api_base: Mapped[str] = mapped_column(String(255), nullable=False, server_default="", comment="API base URL")
    api_key_encrypted: Mapped[str] = mapped_column(
        String(500), nullable=False, server_default="", comment="加密后的 API Key"
    )
    is_active: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=sql_text("1"), comment="是否启用")
    temperature: Mapped[float | None] = mapped_column(Float, default=None, comment="温度覆盖")
    max_tokens: Mapped[int | None] = mapped_column(Integer, default=None, comment="max tokens 覆盖")
    timeout: Mapped[int | None] = mapped_column(Integer, default=None, comment="超时秒数覆盖")
    retry: Mapped[int | None] = mapped_column(Integer, default=None, comment="重试次数覆盖")
    dimension: Mapped[int | None] = mapped_column(Integer, default=None, comment="Embedding 向量维度")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=sql_text("CURRENT_TIMESTAMP"), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=sql_text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="更新时间"
    )
