"""本文件实现多 Agent 产出的引用合并与全局重编号，供 Supervisor 合成阶段使用。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # 仅用于类型注解，避免运行时循环导入
    from agent_service.agents.state import AgentResult


def merge_citations(
    agent_results: list[AgentResult],
) -> tuple[list[dict[str, object]], dict[str, dict[int, int]]]:
    """合并多 Agent 产出引用，做去重与全局重编号。

    Args:
        agent_results: 各 Agent 的结构化产出列表，每项含 citations（局部编号）。

    Returns:
        merged_citations: 全局重编号后的引用列表，每项额外带 from_agent 字段。
        renumber_map: {agent_key: {局部编号: 全局编号}}，用于重写局部答案里的 [n]。
    """
    merged: list[dict[str, object]] = []
    # 用 (source_type, chunk_id, url, title) 四元组去重
    seen: set[tuple[str, str, str, str]] = set()
    global_idx = 1
    renumber_map: dict[str, dict[int, int]] = {}

    for result in agent_results:
        agent_key = result.get("agent", "")
        renumber_map[agent_key] = {}
        for cite in result.get("citations") or []:
            local_idx = cite.get("index")
            key = (
                str(cite.get("source_type", "law")),
                str(cite.get("chunk_id") or ""),
                str(cite.get("url") or ""),
                str(cite.get("title") or ""),
            )
            if key in seen:
                # 已存在：找到对应全局编号，补进 renumber_map
                for existing in merged:
                    existing_key = (
                        str(existing.get("source_type", "law")),
                        str(existing.get("chunk_id") or ""),
                        str(existing.get("url") or ""),
                        str(existing.get("title") or ""),
                    )
                    if existing_key == key:
                        if local_idx is not None:
                            renumber_map[agent_key][int(local_idx)] = int(existing["index"])  # type: ignore[index]
                        break
                continue
            seen.add(key)
            new_cite = dict(cite)
            new_cite["index"] = global_idx
            new_cite["from_agent"] = agent_key
            merged.append(new_cite)
            if local_idx is not None:
                renumber_map[agent_key][int(local_idx)] = global_idx
            global_idx += 1

    return merged, renumber_map


def renumber_answer_text(
    answer: str,
    agent_key: str,
    renumber_map: dict[str, dict[int, int]],
) -> str:
    """把 Agent 局部答案里的 [n] 替换为全局编号。

    未出现在 renumber_map 里的编号保持原样，避免误伤。
    """
    local_map = renumber_map.get(agent_key, {})
    if not local_map:
        return answer

    def replace(match: re.Match[str]) -> str:
        local = int(match.group(1))
        global_idx = local_map.get(local)
        return f"[{global_idx}]" if global_idx is not None else match.group(0)

    return re.sub(r"\[(\d+)\]", replace, answer or "")


def sanitize_citation_references(answer: str, citations: list[dict[str, object]]) -> str:
    """删除答案中没有真实 citation 对应的数字引用。

    这是最终输出前的确定性防线：即使上游检索降级或 LLM 忽略提示，也不会把
    不存在的 ``[n]`` 暴露给用户。合法编号保持不变。
    """
    valid = {
        int(item["index"])
        for item in citations
        if str(item.get("index") or "").isdigit()
    }

    def replace(match: re.Match[str]) -> str:
        return match.group(0) if int(match.group(1)) in valid else ""

    cleaned = re.sub(r"\[(\d+)\]", replace, answer or "")
    # 删除引用被移除后可能留下的多余空格，但保留原有段落结构。
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()
