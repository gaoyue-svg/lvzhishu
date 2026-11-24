"""A/B Test 框架（doc 21 Phase 3）：按 user_id 哈希稳定分流 prompt 版本。

- ab.py：变体分配 + 实验定义 + 应用到当前请求的 prompt 版本覆盖；
- 分流结果（如 "synthesizer_ab:B"）随 shared_state 写入 agent_run_trace.experiment_variant，供结果对比。
"""

from agent_service.experiment.ab import apply_experiment, assign_variant  # noqa: F401
