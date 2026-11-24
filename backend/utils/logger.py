"""带请求级 trace id 支持的日志辅助工具。"""

import contextvars
import logging
import sys


trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="-")


class TraceIdFilter(logging.Filter):
    """将当前 trace id 注入每条日志记录。"""

    def filter(self, record: logging.LogRecord) -> bool:
        """将 trace_id 附加到日志记录上。"""
        record.trace_id = trace_id_var.get()
        return True


def configure_logging() -> None:
    """一次性配置进程级日志。"""
    root = logging.getLogger()
    if getattr(root, "_lawrag_configured", False):
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(TraceIdFilter())
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [trace_id=%(trace_id)s] %(name)s: %(message)s"
        )
    )
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)
    root._lawrag_configured = True


def set_trace_id(trace_id: str) -> contextvars.Token[str]:
    """设置当前上下文的 trace id 并返回重置 token。"""
    return trace_id_var.set(trace_id)


def reset_trace_id(token: contextvars.Token[str]) -> None:
    """根据 token 重置当前上下文的 trace id。"""
    trace_id_var.reset(token)


def get_logger(name: str) -> logging.Logger:
    """返回已应用全局日志配置的模块 logger。"""
    configure_logging()
    return logging.getLogger(name)
