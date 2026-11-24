"""Input Guard（doc 21 §4.1，Phase 2）：请求进入 pipeline 前的安全与预算闸门。

- checks.py：纯函数检查项（输入合法性/提示注入/敏感词/越权/预算/并发）；
- dependencies.py：run_input_guard 编排入口，fail-open 语义，挂在各端点开头。
"""
