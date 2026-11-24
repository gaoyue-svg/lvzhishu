"""本文件实现审查层（doc 19 §4.4）：L1 确定性 + L2 抽样 + 重试/升级闭环。

审查对象是 Agent 的原始产出（chunks + citations + 局部答案），不是最终答案，
避免污染源已被合成器改写。L1 每步必做（纯代码），L2 合成前抽样一次（LLM 核验）。
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from agent_service.llm.usage import usage_purpose
from agent_service.prompts import get_prompt
from backend.config import settings
from backend.utils.logger import get_logger

logger = get_logger(__name__)

REVIEWER_SYSTEM = get_prompt("reviewer_system")

_CLAIM_SPLIT = re.compile(r"[。；！？\n]")


class Reviewer:
    """审查 Agent 原始产出：L1 确定性必做，L2 抽样用 LLM 核验落地。"""

    def __init__(
        self,
        citation_validator: Any,
        llm: Any | None = None,
        *,
        l2_enabled: bool | None = None,
        sample_max: int | None = None,
    ) -> None:
        """注入引用校验器与 L2 抽查 LLM（建议使用不同 provider 避免自评偏见）。"""
        self.citation_validator = citation_validator
        self.llm = llm
        self.l2_enabled = l2_enabled if l2_enabled is not None else settings.review_l2_enabled
        self.sample_max = sample_max if sample_max is not None else settings.review_l2_sample_max

    async def review(self, run: Any, *, db: Any | None = None) -> dict[str, Any]:
        """对 run 的全部 Agent 产出执行审查，返回审查结论。

        Returns:
            {passed, failed_steps, issues, needs_human_review, l2}
        """
        results = list(run.agent_results or [])
        issues: list[dict[str, Any]] = []
        failed_steps: list[str] = []
        needs_human_review = bool(run.needs_human_review)

        for result in results:
            step_id = str(result.get("_step_id") or result.get("agent") or "")
            l1 = await self._review_step_l1(result, db=db)
            if not l1["passed"]:
                failed_steps.append(step_id)
                issues.append(
                    {
                        "step_id": step_id,
                        "agent": result.get("agent"),
                        "level": "L1",
                        "issues": l1["issues"],
                    }
                )
            if (run.intent or {}).get("risk_level") == "high":
                needs_human_review = True

        # L2 落地抽查：仅当 L1 全过且启用了 LLM 时执行，控制成本
        l2: dict[str, Any] = {"passed": True, "checked": 0, "reason": "未启用 L2 抽查"}
        if self.l2_enabled and self.llm is not None and not failed_steps and results:
            l2 = await self._l2_sample(results)
            if not l2["passed"]:
                # L2 失败不标 failed_steps，交给上层按"抽样不符"重跑出错步
                logger.warning("[Reviewer] L2 落地抽查未通过 checked=%s", l2.get("checked"))

        review = {
            "passed": not failed_steps and l2["passed"],
            "failed_steps": failed_steps,
            "issues": issues,
            "needs_human_review": needs_human_review,
            "l2": l2,
        }
        run.review = review
        return review

    async def _review_step_l1(self, result: dict[str, Any], *, db: Any | None = None) -> dict[str, Any]:
        """L1 确定性检查：引用完整性 / 答案非空 / 检索非空 / 风险阈值。"""
        answer = result.get("answer") or ""
        citations = result.get("citations") or []
        chunks = result.get("chunks") or []
        issues: list[str] = []

        if not answer.strip():
            issues.append("答案为空")

        # 引用完整性：局部答案每个 [n] 必须在 citations 中存在。
        # 中间 Agent 产出（如 contract_rag 的法条检索结果）本身无需用 [n] 标注，
        # 只校验已用编号是否真实存在，避免把"未标注引用"误判为缺陷（应由合成后最终答案统一校验）。
        if self.citation_validator is not None:
            validation = await self.citation_validator.validate(
                answer=answer, citations=citations, db=db, require_citation_use=False
            )
            if not validation.get("passed"):
                issues.extend(validation.get("reasons") or [])

        # 检索非空：有检索能力的 Agent 至少应有可引用 chunk
        if chunks and not any(str(c.get("text") or "").strip() for c in chunks):
            issues.append("检索命中无正文")

        return {"passed": not issues, "issues": issues}

    async def _l2_sample(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        """L2 落地抽查：抽样 1~N 个带引用编号的论断，核对被引 chunk 是否支撑。"""
        samples = self._pick_samples(results)
        if not samples:
            return {"passed": True, "checked": 0, "reason": "无带引用论断可抽样"}

        payload = {
            "claims": [
                {"index": idx, "claim": sample["claim"], "cited_text": sample["cited_text"][:800]}
                for idx, sample in enumerate(samples)
            ]
        }
        user_prompt = "请核验下列论断是否确实被所引用的原文支撑，输出 JSON 数组（每项含 index、supported、reason）：\n" + json.dumps(
            payload, ensure_ascii=False, indent=2
        )
        try:
            with usage_purpose("review"):
                raw = await asyncio.wait_for(
                    self.llm.chat_json(
                        REVIEWER_SYSTEM,
                        user_prompt,
                        temperature=0.0,
                        max_tokens=1024,
                    ),
                    timeout=30,
                )
            verdicts = raw.get("claims") or raw.get("results") or []
            if isinstance(verdicts, dict):
                verdicts = [verdicts]
            failed = [v for v in verdicts if not bool(v.get("supported", True))]
            return {
                "passed": not failed,
                "checked": len(verdicts),
                "failed_claims": [v.get("claim") or f"#{v.get('index')}" for v in failed],
                "reason": f"抽查 {len(verdicts)} 条，失败 {len(failed)} 条",
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Reviewer] L2 LLM 核验失败，跳过抽查: %s", exc.__class__.__name__)
            return {"passed": True, "checked": 0, "reason": f"LLM 核验不可用: {exc.__class__.__name__}"}

    def _pick_samples(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """从各 Agent 答案中抽样带引用编号的论断及其引用原文。"""
        samples: list[dict[str, Any]] = []
        for result in results:
            answer = result.get("answer") or ""
            citations = {int(c["index"]): c for c in result.get("citations") or [] if str(c.get("index") or "").isdigit()}
            for claim in _CLAIM_SPLIT.split(answer):
                claim = claim.strip()
                if not claim or len(samples) >= self.sample_max:
                    break
                numbers = [int(n) for n in re.findall(r"\[(\d+)\]", claim)]
                cited = next((citations.get(n) for n in numbers if citations.get(n)), None)
                cited_text = (cited or {}).get("text") or (cited or {}).get("title") or ""
                if cited_text and len(claim) >= 8:
                    samples.append({"claim": claim, "cited_text": cited_text})
                if len(samples) >= self.sample_max:
                    break
            if len(samples) >= self.sample_max:
                break
        return samples
