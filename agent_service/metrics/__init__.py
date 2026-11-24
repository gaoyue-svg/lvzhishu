"""Agent Harness Prometheus 指标（doc 21 §4.3）：Agent/Tool/Pipeline/LLM 指标导出。

- init_metrics()：幂等注册指标处理器到 HookBus（Agent/Pipeline 边界指标）；
- LLM 指标在 provider 采集时实时累加（见 agent_service/llm/usage.py）；
- /metrics 端点见 metrics/router.py。
"""

from agent_service.metrics.registry import init_metrics  # noqa: E402, F401

