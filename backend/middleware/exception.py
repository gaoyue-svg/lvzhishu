"""全局异常处理器，统一输出 ApiResponse 形状的响应。"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from backend.config import settings
from backend.utils.logger import get_logger

logger = get_logger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    """在 FastAPI 应用上注册全部全局异常处理器。"""

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        """将 FastAPI HTTP 异常转换为 ApiResponse JSON。"""
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.status_code, "message": str(exc.detail), "data": None},
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """将请求校验错误转换为字段级响应数据。"""
        return JSONResponse(
            status_code=422,
            content={"code": 422, "message": "Validation error", "data": exc.errors()},
        )

    @app.exception_handler(ValidationError)
    async def validation_handler(request: Request, exc: ValidationError) -> JSONResponse:
        """将 Pydantic 校验错误转换为字段级响应数据。"""
        return JSONResponse(
            status_code=422,
            content={"code": 422, "message": "Validation error", "data": exc.errors()},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """隐藏未预期异常的细节，同时在服务端记录上下文。"""
        logger.exception("未处理的异常")
        message = "Internal server error"
        if settings.app_debug:
            message = f"{message}: {exc.__class__.__name__}"
        return JSONResponse(
            status_code=500,
            content={"code": 500, "message": message, "data": None},
        )
