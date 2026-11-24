"""A/B 分流实现：实验定义 + 按 user_id 哈希稳定分流 + 应用到请求级 prompt 版本覆盖。

实验名 → 变体 → {prompt_name: version} 映射；同一 user_id 在同一实验内结果恒定。
实验配置当前内置于本模块，后续可迁移到 settings/数据库。
"""

from __future__ import annotations

import hashlib
from typing import Any, Literal

from agent_service.prompts import set_prompt_versions
from backend.config import settings
from backend.utils.logger import get_logger

logger = get_logger(__name__)

Variant = Literal["A", "B"]

# 实验名
SYNTHESIZER_AB = "synthesizer_ab"

# 实验定义：experiment_name → {variant: {prompt_name: version}}
_EXPERIMENTS: dict[str, dict[str, dict[str, str]]] = {
    SYNTHESIZER_AB: {
        "A": {"synthesizer_system": "v1"},
        "B": {"synthesizer_system": "v2"},
    },
}


def _hash_user(user_id: int) -> int:
    """把 user_id 稳定映射到整数（跨请求一致）。"""
    return int(hashlib.md5(str(user_id).encode("utf-8")).hexdigest(), 16)


def assign_variant(user_id: int, experiment_name: str = SYNTHESIZER_AB) -> Variant:
    """按 user_id 哈希把用户稳定分到 A/B 两组。"""
    return "A" if _hash_user(user_id) % 2 == 0 else "B"


def apply_experiment(user_id: int) -> tuple[str, Any | None]:
    """为当前请求应用实验：按用户变体设置 prompt 版本覆盖。

    Returns:
        (variant_label, reset_token)：variant_label 如 "synthesizer_ab:B"，未启用为 "none"；
        reset_token 为 None 表示未设置覆盖，否则请求结束需 reset_prompt_versions(token)。
    """
    if not settings.experiment_enabled:
        return "none", None
    experiment = _EXPERIMENTS.get(SYNTHESIZER_AB)
    if not experiment:
        return "none", None

    variant = assign_variant(user_id, SYNTHESIZER_AB)
    token = set_prompt_versions(experiment[variant])
    logger.info("[Experiment] user_id=%s 分流 %s:%s", user_id, SYNTHESIZER_AB, variant)
    return f"{SYNTHESIZER_AB}:{variant}", token
