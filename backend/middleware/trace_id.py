"""请求级 trace id 中间件。"""

from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from backend.utils.logger import reset_trace_id, set_trace_id


class TraceIdMiddleware(BaseHTTPMiddleware):
    """创建并在请求范围内传播 trace id。"""

    async def dispatch(self, request: Request, call_next) -> Response:
        """将 trace id 写入请求状态、日志上下文以及响应头。"""
        trace_id = request.headers.get("X-Trace-Id") or str(uuid4())
        request.state.trace_id = trace_id
        token = set_trace_id(trace_id)
        try:
            response = await call_next(request)
            response.headers["X-Trace-Id"] = trace_id
            return response
        finally:
            reset_trace_id(token)
