"""本文件实现 Agent Card 注册表：以 YAML 卡片为规划器/校验器的唯一事实来源。

doc 19 §5.1：Agent Card 替代 manager._agent_classes 的裸 dict，提供
list/get/validate_plan，白名单从卡片派生，根治 ALLOWED_AGENTS 漏登记问题。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from backend.utils.logger import get_logger

logger = get_logger(__name__)

CARDS_DIR = Path(__file__).resolve().parent / "cards"


@dataclass(frozen=True)
class AgentCard:
    """单个业务 Agent 的描述卡片，规划 Prompt 据此选择 agent。"""

    key: str
    name: str = ""
    description: str = ""
    when_to_use: list[str] = field(default_factory=list)
    when_not_to_use: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    retrieval: bool = True
    top_k: int = 15
    rerank_top_k: int = 8
    temperature: float = 0.3
    parallel_ok: bool = True
    model_tier: str = "default"
    needs_web: bool = False
    workflow: str | None = None

    def to_prompt_block(self) -> str:
        """生成给规划 LLM 看的紧凑描述块，只给选择依据不给冗余字段。"""
        lines = [f"- {self.key}（{self.name}）: {self.description}"]
        if self.when_to_use:
            lines.append(f"  适用: {'；'.join(self.when_to_use[:3])}")
        if self.when_not_to_use:
            lines.append(f"  不适用: {'；'.join(self.when_not_to_use[:2])}")
        return "\n".join(lines)


class AgentCardRegistry:
    """从 cards/ 目录加载全部 Agent Card，提供 list/get/validate_plan。"""

    def __init__(self, cards: dict[str, AgentCard] | None = None) -> None:
        """初始化注册表；未传时从磁盘加载卡片目录。"""
        self._cards = cards if cards is not None else _load_cards()

    def list(self) -> list[AgentCard]:
        """返回全部卡片，按 key 排序。"""
        return sorted(self._cards.values(), key=lambda card: card.key)

    def get(self, key: str) -> AgentCard | None:
        """按 key 取卡片，不存在返回 None。"""
        return self._cards.get(key)

    def keys(self) -> list[str]:
        """返回全部已注册 agent key。"""
        return sorted(self._cards)

    def allowed_agents(self) -> set[str]:
        """从卡片派生白名单，根治漏登记问题。"""
        return set(self._cards)

    def agent_blocks(self) -> str:
        """返回全部卡片的紧凑描述，供规划/意图 LLM 参考。"""
        return "\n".join(card.to_prompt_block() for card in self.list())

    def validate_plan(self, steps: list[dict[str, Any]], max_steps: int) -> list[str]:
        """纯代码守卫（不靠 LLM）：校验 agent 白名单、步数上限、依赖无环、合成步骤存在。

        Returns:
            错误信息列表；为空表示校验通过。
        """
        errors: list[str] = []
        if len(steps) > max_steps:
            errors.append(f"计划步数 {len(steps)} 超过上限 {max_steps}")
        ids: set[str] = set()
        deps: dict[str, set[str]] = {}
        for step in steps:
            step_id = str(step.get("step_id") or "")
            agent = str(step.get("agent") or "")
            if step_id in ids:
                errors.append(f"step_id 重复: {step_id}")
            ids.add(step_id)
            # synthesize 是编排器保留步骤，不在 Agent Card 注册表内
            if agent not in self._cards and agent not in {"synthesize"}:
                errors.append(f"agent {agent} 未在 Agent Card 注册表")
            if step_id:
                deps[step_id] = {str(item) for item in (step.get("deps") or [])}

        # 拓扑无环校验（DFS 三色标记）
        visiting: set[str] = set()
        visited: set[str] = set()

        def _visit(node: str) -> bool:
            if node in visiting:
                return False
            if node in visited or node not in deps:
                visited.add(node)
                return True
            visiting.add(node)
            for dep in deps[node]:
                if not _visit(dep):
                    return False
            visiting.discard(node)
            visited.add(node)
            return True

        for step_id in ids:
            if not _visit(step_id):
                errors.append("计划存在循环依赖")
                break

        # 至少存在一个合成步骤，否则无法产出最终答案
        if not any(str(step.get("agent") or "") == "synthesize" for step in steps):
            errors.append("计划缺少 synthesize 合成步骤")
        return errors


def _load_cards() -> dict[str, AgentCard]:
    """扫描 cards/ 目录并解析全部 *.yaml 卡片。"""
    cards: dict[str, AgentCard] = {}
    if not CARDS_DIR.is_dir():
        logger.warning("Agent cards 目录不存在: %s", CARDS_DIR)
        return cards
    for path in sorted(CARDS_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            meta = data.get("agent_card") or data
            key = str(meta.get("key") or path.stem)
            cards[key] = AgentCard(key=key, **{k: v for k, v in meta.items() if k != "key"})
        except Exception as exc:  # noqa: BLE001
            logger.warning("Agent card 加载失败 %s: %s", path.name, exc.__class__.__name__)
    if cards:
        logger.info("Agent Card 注册表加载完成，共 %d 张卡片", len(cards))
    return cards


@lru_cache(maxsize=1)
def get_registry() -> AgentCardRegistry:
    """进程级单例注册表，卡片文件变更后重启生效。"""
    return AgentCardRegistry()
