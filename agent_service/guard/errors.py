"""Guard 拦截异常：携带 HTTP 状态码、提示语与检查项名，便于统一转 4xx 与埋点。"""

from __future__ import annotations


class GuardError(Exception):
    """Guard 拦截异常。"""

    def __init__(self, status_code: int, message: str, check: str) -> None:
        """构造拦截异常：status_code=HTTP 状态码；check=检查项名（用于指标 label）。"""
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.check = check
