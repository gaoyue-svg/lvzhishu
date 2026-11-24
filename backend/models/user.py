"""用户 ORM 模型,对应 sql/init.sql 中的 user 表。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models import Base


class User(Base):
    """用户表,映射自 sql/init.sql。"""

    __tablename__ = "user"
    __table_args__ = {"comment": "用户表"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="用户ID")
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, comment="用户名")
    email: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, comment="邮箱")
    phone: Mapped[str | None] = mapped_column(String(20), default=None, comment="手机号")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, comment="密码哈希(bcrypt)")
    avatar: Mapped[str | None] = mapped_column(String(500), default=None, comment="头像OSS地址")
    role: Mapped[str] = mapped_column(String(20), nullable=False, server_default=sql_text("'user'"), comment="角色: admin / user")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=sql_text("'active'"), comment="状态: active / disabled")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, default=None, comment="最后登录时间")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=sql_text("CURRENT_TIMESTAMP"), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=sql_text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="更新时间")
