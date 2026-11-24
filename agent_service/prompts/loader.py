"""本文件实现 Prompt 加载器：读取 registry.yml 索引并加载 md 文件内容到内存缓存。

对外提供三个 API：
- get_prompt(name, version=None)：取 system prompt 原文（支持按版本取）
- format_prompt(name, **kwargs)：取 user 模板并用 kwargs 填充占位符（支持按版本取）
- build_user_prompt(router_input, candidates)：Router 用户提示词组装（含 Python 逻辑）

版本机制（doc 21 Phase 3 A/B）：registry.yml 中每个 prompt 可声明 versions: {label: file}；
缺省单文件按 v1 处理。版本解析优先级：显式参数 > 请求级 A/B 覆盖（set_prompt_versions）>
settings.prompt_version_overrides > 默认 v1。
"""

from __future__ import annotations

import json
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from backend.config import settings

if TYPE_CHECKING:
    # 仅用于类型注解，运行时不导入，避免与 agent_service.router 形成循环导入
    from agent_service.agents.state import AgentResult
    from agent_service.router.models import Candidate, RouterInput

# prompts 包根目录，用于定位 registry.yml 和 md/ 子目录
_PROMPTS_DIR = Path(__file__).resolve().parent
_REGISTRY_PATH = _PROMPTS_DIR / "registry.yml"

# 无 versions 字段的 prompt 的默认版本标签
_DEFAULT_VERSION = "v1"

# 请求级 A/B 版本覆盖：{prompt_name: version}，由实验框架按用户变体设置
_active_versions: ContextVar[dict[str, str]] = ContextVar("prompt_active_versions", default={})


def _load_registry() -> dict[str, dict[str, dict[str, Any]]]:
    """读取 registry.yml 并返回结构化索引。"""
    with _REGISTRY_PATH.open("r", encoding="utf-8") as fp:
        data = yaml.safe_load(fp) or {}
    return {
        "system_prompts": data.get("system_prompts") or {},
        "user_templates": data.get("user_templates") or {},
    }


def _read_md(file_relative: str) -> str:
    """读取 md 文件内容，去掉首尾空白。"""
    md_path = _PROMPTS_DIR / file_relative
    return md_path.read_text(encoding="utf-8").strip()


def _collect_versions(meta: dict[str, Any]) -> dict[str, str]:
    """把 prompt 元信息展开为 {version: text}；无 versions 字段时按单版本 v1 处理。"""
    versions = meta.get("versions") or {}
    if versions:
        return {str(label): _read_md(str(file)) for label, file in versions.items()}
    return {_DEFAULT_VERSION: _read_md(str(meta.get("file") or ""))}


@lru_cache(maxsize=1)
def _cache() -> dict[str, dict[str, dict[str, str]]]:
    """启动时一次性加载所有 prompt 版本到内存缓存，运行时零 IO。

    缓存结构：{"system_prompts": {key: {version: text}}, "user_templates": {key: {version: text}}}
    """
    registry = _load_registry()
    return {
        "system_prompts": {key: _collect_versions(meta) for key, meta in registry["system_prompts"].items()},
        "user_templates": {key: _collect_versions(meta) for key, meta in registry["user_templates"].items()},
    }


def list_prompt_versions(name: str, *, kind: str = "system_prompts") -> list[str]:
    """返回某 prompt 已注册的全部版本标签（便于实验配置与测试）。"""
    pool = _cache().get(kind, {})
    if name not in pool:
        raise KeyError(f"未注册的 prompt: {name}")
    return list(pool[name].keys())


def _resolve_version(name: str, kind: str, version: str | None) -> str:
    """按优先级解析实际生效的版本：显式参数 > 请求级 A/B 覆盖 > 设置覆盖 > 默认 v1。"""
    pool = _cache().get(kind, {})
    if name not in pool:
        raise KeyError(f"未注册的 prompt: {name}")
    available = pool[name]

    if version is not None:
        if version not in available:
            raise KeyError(f"prompt {name} 不存在版本 {version}，可选: {sorted(available)}")
        return version

    overrides = _active_versions.get()
    if overrides.get(name) in available:
        return overrides[name]

    cfg_override = (settings.prompt_version_overrides or {}).get(name)
    if cfg_override in available:
        return cfg_override

    if _DEFAULT_VERSION in available:
        return _DEFAULT_VERSION
    return next(iter(available))


def get_prompt(name: str, version: str | None = None) -> str:
    """按 key 取 system prompt 原文；version 缺省按 A/B 覆盖/配置/默认 v1 解析。"""
    resolved = _resolve_version(name, "system_prompts", version)
    return _cache()["system_prompts"][name][resolved]


def format_prompt(name: str, *, version: str | None = None, **kwargs: Any) -> str:
    """按 key 取 user 模板并用 kwargs 填充命名占位符；version 解析同上。"""
    resolved = _resolve_version(name, "user_templates", version)
    return _cache()["user_templates"][name][resolved].format(**kwargs)


# ---- 请求级 A/B 版本覆盖：由实验框架按用户变体设置，请求结束恢复 ----
def set_prompt_versions(mapping: dict[str, str]) -> Any:
    """为当前请求绑定 prompt→version 覆盖，返回用于恢复的 Token。"""
    return _active_versions.set(dict(mapping))


def reset_prompt_versions(token: Any) -> None:
    """解除请求级版本覆盖。"""
    _active_versions.reset(token)


def get_active_prompt_versions() -> dict[str, str]:
    """返回当前请求生效的版本覆盖（无则空 dict）。"""
    return dict(_active_versions.get())


def build_user_prompt(router_input: "RouterInput", candidates: list["Candidate"]) -> str:
    """将用户输入、记忆、文件和规则候选注入 Router 用户提示词。"""
    payload: dict[str, Any] = {
        "user_query": router_input.user_query,
        "history_summary": router_input.history_summary or "无（首轮对话）",
        "legal_memory": router_input.legal_memory.model_dump(mode="json") if router_input.legal_memory else None,
        "uploaded_files": router_input.uploaded_files,
        "available_kbs": router_input.available_kbs,
        "route_hint_candidates": [candidate.model_dump() for candidate in candidates],
    }
    return "请根据以下上下文输出 RouterDecision JSON：\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def build_supervisor_user_prompt(
    *,
    query: str,
    entry_hint: str,
    agent_history: list[dict[str, Any]],
    candidates: list["Candidate"],
    round_num: int,
    max_rounds: int,
) -> str:
    """构造 Supervisor 决策的用户提示词。

    只把 agent_history 的摘要传给 LLM，不传完整 chunks/context，避免 token 膨胀。
    """
    payload: dict[str, Any] = {
        "user_query": query,
        "entry_hint": entry_hint or "无",
        "agent_history": agent_history or [],
        "rule_candidates": [candidate.model_dump() for candidate in candidates],
        "current_round": round_num,
        "max_rounds": max_rounds,
    }
    return "请根据以下上下文输出 SupervisorDecision JSON：\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def build_synthesizer_user_prompt(
    *,
    query: str,
    agent_results: list["AgentResult"],
    merged_citations: list[dict[str, Any]],
    renumber_map: dict[str, dict[int, int]],
    context_max_tokens: int = 8000,
) -> str:
    """构造 Synthesizer 合成答案的用户提示词。

    把各 Agent 的局部答案（按 renumber_map 重写引用编号）、截断后的 context 摘要、
    合并后的全局引用列表传给 LLM，约束其只能使用已有引用编号。

    context_max_tokens：每个 Agent 的 context_text 按 token 截断后传入，
    修复 doc 19 D6 的 prompt 膨胀问题（多轮 context 累计导致 token 浪费）。
    """
    from agent_service.agents.citation_merge import renumber_answer_text
    from backend.utils.tokenizer import truncate_to_tokens

    # 重写每个 Agent 答案里的局部 [n] 为全局编号，context_text 按预算截断
    agent_sections: list[dict[str, Any]] = []
    for result in agent_results:
        agent_key = result.get("agent", "")
        context_text = str(result.get("context_text", "") or "")
        agent_sections.append({
            "agent": agent_key,
            "input": result.get("input", ""),
            "answer": renumber_answer_text(result.get("answer", ""), agent_key, renumber_map),
            "context_text": truncate_to_tokens(context_text, context_max_tokens),
            "output_summary": result.get("output_summary", ""),
        })
    # 引用里的 full_text 是给前端弹窗展示的网页正文，体积大，不应进 LLM 提示词。
    slim_citations = [{k: v for k, v in c.items() if k != "full_text"} for c in merged_citations]
    citation_policy = (
        "只允许使用 merged_citations 中实际存在的 index；禁止生成其他 [n] 编号。"
        if slim_citations
        else (
            "当前没有可核验的知识库引用；禁止输出任何 [n] 形式的数字引用，也不得把未检索到的法条写成正式依据。"
            "如确需提示检索状态，只能使用面向用户的表述“当前未取得可核验的知识库法条引用，建议稍后重试”，"
            "不得提及 Agent、内部产出、编排、降级或其他系统实现细节。"
        )
    )
    payload: dict[str, Any] = {
        "user_query": query,
        "agent_sections": agent_sections,
        "merged_citations": slim_citations,
        "citation_policy": citation_policy,
    }
    return "请基于以下多 Agent 产出，重写一份连贯的最终答案：\n" + json.dumps(payload, ensure_ascii=False, indent=2)
