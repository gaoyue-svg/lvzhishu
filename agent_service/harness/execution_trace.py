"""提问级 Agent/工具执行链路采集（doc 21 扩展）：请求级 ExecutionTracer + question_trace 落库。

目标：**每个提问**都记录背后调度了哪些 Agent、调用了哪些工具，覆盖全部编排路径
（Supervisor V1 默认 / v2 Pipeline / 单 Agent / 合同审查）。

采集点：
- BaseAgent.tool_exec_node：每个工具调用（全部路径的工具都汇聚到这里）；
- BaseAgent.invoke_for_supervisor：Supervisor V1 与 v2 Executor 的 Agent 调用；
- /api/agent/chat 单 Agent 分支、/api/agent/contract/review：astream 包裹 begin/end。

并发安全：current_agent 用 ContextVar（asyncio task 级），v2 并行 step 各自绑定互不串扰；
agents 列表 append 在事件循环单线程内天然原子。全部 best-effort，失败只 warning。
"""

from __future__ import annotations

import json
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from backend.config import settings
from backend.utils.logger import get_logger

logger = get_logger(__name__)

_SUMMARY_LIMIT = 180          # 工具入参/出参摘要长度
_QUERY_LIMIT = 4000           # 提问文本上限
_ANSWER_SNIPPET_LIMIT = 500   # 最终答案摘要长度


@dataclass
class ExecutionTracer:
    """请求级 Agent/工具执行链路采集器。

    - agents：每个 Agent 调用一条记录，tools 嵌套在该 Agent 下；
    - orphan_tools：无 Agent 上下文时的工具调用（防御性兜底）；
    - begin/end 用 ContextVar 记录当前 Agent，asyncio task 级隔离。
    """

    agents: list[dict[str, Any]] = field(default_factory=list)
    orphan_tools: list[dict[str, Any]] = field(default_factory=list)
    _started: float = field(default_factory=perf_counter)

    def begin_agent(
        self,
        agent: str,
        *,
        round_num: int = 0,
        input_summary: str = "",
    ) -> int:
        """开始一次 Agent 调用；把当前 task 绑定到该 Agent（v2 并行 step 安全）。"""
        # v2 Executor / 单 Agent 分支没有 current_round，用顺序计数兜底。
        round_num = int(round_num or 0)
        if round_num <= 0:
            round_num = len(self.agents) + 1
        entry: dict[str, Any] = {
            "agent": agent,
            "round": round_num,
            "status": "running",
            "input_summary": _summarize(input_summary),
            "latency_ms": 0,
            "chunks_count": 0,
            "citations_count": 0,
            "output_summary": "",
            "tools": [],
            "_token": None,
            "_started": perf_counter(),
        }
        self.agents.append(entry)
        index = len(self.agents) - 1
        entry["_token"] = _current_agent_idx.set(index)
        return index

    def end_agent(
        self,
        index: int,
        *,
        status: str,
        output_summary: str = "",
        chunks_count: int = 0,
        citations_count: int = 0,
    ) -> None:
        """结束一次 Agent 调用，固化耗时/产出并解除当前 task 绑定。"""
        if index < 0 or index >= len(self.agents):
            return
        entry = self.agents[index]
        entry["status"] = status or "success"
        entry["output_summary"] = _summarize(output_summary)
        entry["chunks_count"] = int(chunks_count or 0)
        entry["citations_count"] = int(citations_count or 0)
        entry["latency_ms"] = int((perf_counter() - entry.pop("_started", perf_counter())) * 1000)
        token = entry.pop("_token", None)
        if token is not None:
            try:
                _current_agent_idx.reset(token)
            except (ValueError, LookupError):
                pass

    def add_tool(
        self,
        name: str,
        *,
        input_summary: Any = "",
        output_summary: Any = "",
        ok: bool = True,
        latency_ms: int = 0,
    ) -> None:
        """记录一次工具调用，绑定到当前 task 的 Agent；无 Agent 上下文进 orphan 兜底。"""
        record: dict[str, Any] = {
            "name": name,
            "agent": None,
            "input_summary": _summarize(input_summary),
            "output_summary": _summarize(output_summary),
            "ok": ok,
            "latency_ms": int(latency_ms or 0),
        }
        current = _current_agent_idx.get()
        if current is not None and 0 <= current < len(self.agents):
            record["agent"] = self.agents[current]["agent"]
            self.agents[current]["tools"].append(record)
        else:
            self.orphan_tools.append(record)

    def to_payload(self) -> list[dict[str, Any]]:
        """导出可落库的 agents 序列（剥除内部 _token/_started 字段）。"""
        return [{key: value for key, value in entry.items() if not key.startswith("_")} for entry in self.agents]

    def total_latency_ms(self) -> int:
        """本次请求累计耗时（首次采集到当前）。"""
        return int((perf_counter() - self._started) * 1000)


# ---- 请求级 contextvar：绑定 tracer 与当前 Agent ----
_tracer: ContextVar[ExecutionTracer | None] = ContextVar("execution_tracer", default=None)
_current_agent_idx: ContextVar[int | None] = ContextVar("execution_current_agent", default=None)


def get_current_tracer() -> ExecutionTracer | None:
    """返回当前请求绑定的采集器；未绑定返回 None。"""
    return _tracer.get()


def set_execution_tracer(tracer: ExecutionTracer) -> Any:
    """绑定当前请求的采集器，返回用于恢复的 Token。"""
    return _tracer.set(tracer)


def reset_execution_tracer(token: Any) -> None:
    """解除采集器绑定。"""
    _tracer.reset(token)


def _summarize(value: Any, limit: int = _SUMMARY_LIMIT) -> str:
    """把任意值压缩为可读摘要（压缩空白 + JSON 序列化 + 截断）。"""
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except TypeError:
            text = str(value)
    return " ".join(text.split())[:limit]


async def flush_execution_trace(
    tracer: ExecutionTracer | None,
    *,
    trace_id: str,
    user_id: int | None = None,
    conversation_id: int | None = None,
    query: str = "",
    intent: str = "",
    engine: str = "",
    status: str = "success",
    answer_snippet: str = "",
    error: str = "",
) -> None:
    """把采集器落 question_trace。best-effort：失败只 warning，绝不阻断在线请求。

    即使本次提问没有产生任何 Agent/工具记录（如 Guard 拦截 / 编排器创建失败），
    也写入一条最小记录，保证"每个提问都被记录"。
    """
    if not settings.harness_enabled:
        return
    if not trace_id:
        return

    from backend.database import AsyncSessionLocal
    from backend.models.harness import QuestionTrace

    row = QuestionTrace(
        trace_id=trace_id,
        conversation_id=_safe_int(conversation_id),
        user_id=_safe_int(user_id),
        query=(query or "")[:_QUERY_LIMIT],
        intent=intent or None,
        engine=engine or None,
        status=status or "success",
        agents=tracer.to_payload() if (tracer and tracer.agents) else None,
        total_latency_ms=tracer.total_latency_ms() if tracer else 0,
        answer_snippet=(answer_snippet or "")[:_ANSWER_SNIPPET_LIMIT],
        error=error or None,
    )
    try:
        async with AsyncSessionLocal() as session:
            session.add(row)
            await session.commit()
    except Exception:  # noqa: BLE001
        logger.warning("[ExecutionTrace] question_trace 落库失败 trace_id=%s", trace_id, exc_info=True)


def _safe_int(value: Any) -> int | None:
    """安全转换为 int；无法转换返回 None。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
