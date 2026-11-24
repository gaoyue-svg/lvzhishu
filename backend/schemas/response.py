"""统一 API 响应 Schema 定义。"""

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """通用 API 响应包装。"""

    code: int = 0
    message: str = "success"
    data: T | None = None


class PaginatedResponse(BaseModel, Generic[T]):
    """通用分页 API 响应包装。"""

    code: int = 0
    message: str = "success"
    data: list[T] = Field(default_factory=list)
    total: int
    page: int
    page_size: int
