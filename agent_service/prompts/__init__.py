"""本文件集中导出 agent_service 的 LLM Prompt 加载 API。

Prompt 文本存放在 md/ 子目录，由 registry.yml 索引，loader.py 启动时加载到内存。
上层统一通过本模块获取 prompt，不直接读 md 或 yml。
"""

from agent_service.prompts.loader import (
    build_supervisor_user_prompt,
    build_synthesizer_user_prompt,
    build_user_prompt,
    format_prompt,
    get_active_prompt_versions,
    get_prompt,
    list_prompt_versions,
    reset_prompt_versions,
    set_prompt_versions,
)

__all__ = [
    "get_prompt",
    "format_prompt",
    "build_user_prompt",
    "build_supervisor_user_prompt",
    "build_synthesizer_user_prompt",
    "list_prompt_versions",
    "set_prompt_versions",
    "reset_prompt_versions",
    "get_active_prompt_versions",
]
