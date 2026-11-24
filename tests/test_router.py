"""本文件测试阶段四 Router Agent 的规则候选、LLM 确认、兜底与状态映射。"""

from __future__ import annotations

import unittest

from agent_service.router import LegalMemory, RouterAgent, RouterDecision, RouterInput, build_initial_state
from agent_service.router.rules import generate_candidates


class StaticLLM:
    """返回固定 JSON 的测试 LLM。"""

    def __init__(self, payload):
        """保存待返回的 payload。"""
        self.payload = payload

    async def chat_json(self, *_args, **_kwargs):
        """模拟 Router LLM JSON 输出。"""
        return self.payload


class FailingLLM:
    """始终失败的测试 LLM。"""

    async def chat_json(self, *_args, **_kwargs):
        """模拟 LLM 超时或网络异常。"""
        raise TimeoutError("timeout")


def router_input(query: str, **kwargs) -> RouterInput:
    """构造测试用 RouterInput。"""
    payload = {
        "user_query": query,
        "conversation_id": "1",
        "user_id": "1",
        "tenant_id": "1",
    }
    payload.update(kwargs)
    return RouterInput(**payload)


def decision_payload(**overrides):
    """构造合法 RouterDecision JSON。"""
    payload = {
        "task_type": "legal_question",
        "agent": "law_qa",
        "confidence": 0.82,
        "need_retrieval": True,
        "retrieval_scope": {"domain": "civil", "category": "contract", "keywords": ["租赁"]},
        "need_file": False,
        "file_requirement": None,
        "legal_context": {"law_name": "民法典", "article_no": None, "cause_of_action": "租赁合同纠纷"},
        "sub_questions": ["承租人如何维权"],
        "time_context": {"type": "latest", "year": None},
        "execution_mode": "rag",
        "risk_level": "low",
        "route_reason": "普通法律咨询",
    }
    payload.update(overrides)
    return payload


class RouterAgentTests(unittest.IsolatedAsyncioTestCase):
    """覆盖 Router 设计文档要求的核心路由场景。"""

    async def test_single_turn_law_qa(self) -> None:
        """单轮普通法律咨询应路由到 law_qa。"""
        decision = await RouterAgent(llm=StaticLLM(decision_payload())).route(
            router_input("租房漏水房东不修怎么办")
        )
        self.assertEqual(decision.agent, "law_qa")
        self.assertEqual(decision.task_type, "legal_question")
        self.assertFalse(decision.fallback)

    async def test_article_locate_rule(self) -> None:
        """法条编号+法律名命中 article_locate 候选，LLM 缺失时由兜底接管。"""
        decision = await RouterAgent().route(router_input("民法典第585条是什么"))
        self.assertEqual(decision.agent, "article_locate")
        self.assertEqual(decision.task_type, "article_lookup")
        self.assertTrue(decision.fallback)

    async def test_contract_review_with_file(self) -> None:
        """已上传合同文件应生成合同审查候选。"""
        decision = await RouterAgent().route(
            router_input(
                "帮我看看有没有风险",
                uploaded_files=[{"document_id": "d1", "file_name": "contract.pdf", "doc_type": "contract"}],
            )
        )
        self.assertEqual(decision.agent, "contract_review")
        self.assertTrue(decision.need_file)
        self.assertIsNotNone(decision.file_requirement)

    async def test_contract_review_without_file(self) -> None:
        """用户明确要求审查合同时，即使未上传文件也应提示需要文件。"""
        decision = await RouterAgent().route(router_input("帮我审查合同有没有问题"))
        self.assertEqual(decision.agent, "contract_review")
        self.assertEqual(decision.execution_mode, "document_analysis")
        self.assertTrue(decision.need_file)

    async def test_case_analysis_overrules_article_candidate(self) -> None:
        """含法条编号但核心问案例时，LLM 可推翻 article_locate 候选走 case_analysis。"""
        payload = decision_payload(
            task_type="case_search",
            agent="case_analysis",
            confidence=0.85,
            retrieval_scope={"domain": "civil", "category": "contract", "keywords": ["违约金", "裁判规则"]},
            legal_context={"law_name": "民法典", "article_no": "第585条", "cause_of_action": "合同纠纷"},
            sub_questions=["违约金调整的裁判规则"],
            execution_mode="multi_step",
            risk_level="medium",
            route_reason="含法条编号但核心诉求是案例检索",
        )
        decision = await RouterAgent(llm=StaticLLM(payload)).route(
            router_input("民法典第585条关于违约金，实际案件怎么判")
        )
        candidates = generate_candidates(router_input("民法典第585条关于违约金，实际案件怎么判"))
        self.assertIn("article_locate", {item.agent for item in candidates})
        self.assertEqual(decision.agent, "case_analysis")
        self.assertFalse(decision.fallback)

    async def test_multi_turn_continuation(self) -> None:
        """多轮追问应把 legal_memory 注入 Router 并允许延续 law_qa。"""
        memory = LegalMemory(
            current_case={"domain": "租赁纠纷", "facts": ["漏水", "房东不修"]},
            current_law={"laws": ["民法典"], "articles": ["第712条"]},
        )
        decision = await RouterAgent(llm=StaticLLM(decision_payload(route_reason="延续租赁纠纷咨询"))).route(
            router_input("那如果我要自己修呢", history_summary="用户为房屋承租人", legal_memory=memory)
        )
        self.assertEqual(decision.agent, "law_qa")
        self.assertTrue(generate_candidates(router_input("那如果我要自己修呢", legal_memory=memory)))

    async def test_high_risk_criminal(self) -> None:
        """刑事或暴力风险问题必须标记 high 并触发人工审核。"""
        decision = await RouterAgent().route(router_input("别人打了我，我能还手吗"))
        self.assertEqual(decision.risk_level, "high")
        self.assertTrue(decision.needs_human_review)

    async def test_document_generation_fallback(self) -> None:
        """文书生成使用 law_qa 检索，但必须保留 document_generation 意图。"""
        decision = await RouterAgent().route(router_input("帮我写一份律师函"))
        self.assertEqual(decision.task_type, "document_generation")
        self.assertEqual(decision.agent, "law_qa")

    async def test_contract_template_is_document_generation(self) -> None:
        decision = await RouterAgent().route(
            router_input("请给我一份房屋租赁合同模板，包含押金和维修责任")
        )
        self.assertEqual(decision.task_type, "document_generation")
        self.assertEqual(decision.agent, "law_qa")

    async def test_civil_complaint_typo_is_document_generation(self) -> None:
        """“起讼状”常见错别字仍应识别为正式文书生成。"""
        decision = await RouterAgent().route(
            router_input("请给我一份拖欠贷款的民事起讼状模板")
        )
        self.assertEqual(decision.task_type, "document_generation")
        self.assertEqual(decision.agent, "law_qa")

    async def test_low_confidence_fallback(self) -> None:
        """LLM 输出低置信度时应强制降级 law_qa。"""
        decision = await RouterAgent(llm=StaticLLM(decision_payload(agent="case_analysis", confidence=0.4))).route(
            router_input("这个事情你怎么看")
        )
        self.assertEqual(decision.agent, "law_qa")
        self.assertTrue(decision.fallback)

    async def test_llm_failure_fallback(self) -> None:
        """LLM 调用失败时应按最高分规则候选兜底。"""
        decision = await RouterAgent(llm=FailingLLM(), retry=0, timeout=1).route(
            router_input("民法典第585条是什么")
        )
        self.assertEqual(decision.agent, "article_locate")
        self.assertTrue(decision.fallback)

    async def test_json_parse_failure(self) -> None:
        """LLM 输出非法 JSON 时应回退到规则候选或 law_qa。"""
        decision = await RouterAgent(llm=StaticLLM("not-json"), retry=0).route(
            router_input("民法典第585条是什么")
        )
        self.assertEqual(decision.agent, "article_locate")
        self.assertTrue(decision.fallback)

    async def test_historical_time_context(self) -> None:
        """历史版本问题应识别 historical time_context。"""
        decision = await RouterAgent().route(router_input("2020年当时借钱不还怎么办"))
        self.assertEqual(decision.time_context.type, "historical")
        self.assertEqual(decision.time_context.year, 2020)

    async def test_state_mapper(self) -> None:
        """RouterDecision 应能映射为业务 Agent 初始 State。"""
        input_data = router_input("租房漏水房东不修怎么办")
        decision = RouterDecision.model_validate(decision_payload())
        state = build_initial_state(decision, input_data)
        self.assertEqual(state["query"], input_data.user_query)
        self.assertEqual(state["intent"], "legal_question")
        self.assertEqual(state["legal_domain"], "contract")


class ConfidenceClampTests(unittest.IsolatedAsyncioTestCase):
    """覆盖 P0 修复：confidence 上限校验，避免 LLM 判定被丢弃。"""

    async def _run_with_confidence(self, confidence: float):
        payload = decision_payload(confidence=confidence)
        return await RouterAgent(llm=StaticLLM(payload)).route(router_input("租房漏水怎么办"))

    async def test_confidence_above_max_clamped_not_dropped(self) -> None:
        """LLM 输出 0.96 应被 clamp 到 0.95，保留 agent 判定，不走兜底。"""
        decision = await self._run_with_confidence(0.96)
        self.assertEqual(decision.agent, "law_qa")
        self.assertAlmostEqual(decision.confidence, 0.95)
        self.assertFalse(decision.fallback)

    async def test_confidence_boundary_threshold_not_fallback(self) -> None:
        """confidence=0.6 正好等于阈值，不应降级。"""
        decision = await self._run_with_confidence(0.6)
        self.assertEqual(decision.agent, "law_qa")
        self.assertFalse(decision.fallback)

    async def test_confidence_below_threshold_forced_fallback(self) -> None:
        """confidence=0.59 低于阈值，强制降级到 law_qa 并标记 fallback。"""
        decision = await self._run_with_confidence(0.59)
        self.assertEqual(decision.agent, "law_qa")
        self.assertTrue(decision.fallback)
        self.assertLessEqual(decision.confidence, 0.5)

    async def test_confidence_zero_treated_as_low(self) -> None:
        """confidence=0 极端低值，应触发降级。"""
        decision = await self._run_with_confidence(0.0)
        self.assertTrue(decision.fallback)


class RuleCandidateTests(unittest.TestCase):
    """覆盖 P1-1 修复：规则候选生成与多规则同时命中。"""

    def test_law_and_topic_hits_article_locate_candidate(self) -> None:
        """法律名+主题查询（无具体条号）应命中 article_locate 低分候选。"""
        for query in ("劳动合同法关于加班的规定", "民法典关于违约金的规定", "刑法关于正当防卫的适用"):
            candidates = generate_candidates(router_input(query))
            agents = {c.agent for c in candidates}
            self.assertIn("article_locate", agents, f"未命中候选: {query}")

    def test_article_and_law_higher_score_than_topic_only(self) -> None:
        """同时含条号+法律名+主题词时，应有两条 article_locate 候选（0.8 > 0.6）。"""
        candidates = generate_candidates(router_input("民法典第585条关于违约金的规定"))
        article_scores = [c.score for c in candidates if c.agent == "article_locate"]
        self.assertIn(0.8, article_scores)
        self.assertIn(0.6, article_scores)

    def test_article_plus_case_produces_multiple_candidates(self) -> None:
        """法条编号+案例关键词应同时命中 article_locate 和 case_analysis 候选。"""
        candidates = generate_candidates(router_input("民法典第585条关于违约金，实际案件怎么判"))
        agents = {c.agent for c in candidates}
        self.assertIn("article_locate", agents)
        self.assertIn("case_analysis", agents)

    def test_contract_file_plus_intent_produces_two_contract_candidates(self) -> None:
        """已上传合同+明确审查意图应同时命中两条 contract_review 候选。"""
        candidates = generate_candidates(router_input(
            "帮我看看有没有风险",
            uploaded_files=[{"document_id": "d1", "file_name": "c.pdf", "doc_type": "contract"}],
        ))
        contract_scores = [c.score for c in candidates if c.agent == "contract_review"]
        self.assertEqual(len(contract_scores), 2)
        self.assertIn(0.85, contract_scores)
        self.assertIn(0.75, contract_scores)

    def test_candidates_sorted_by_score_desc(self) -> None:
        """候选列表应按 score 降序排列。"""
        candidates = generate_candidates(router_input(
            "民法典第585条关于违约金，实际案件怎么判，帮我写一份律师函",
        ))
        scores = [c.score for c in candidates]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_no_rule_match_returns_empty(self) -> None:
        """无任何规则命中时应返回空候选列表。"""
        candidates = generate_candidates(router_input("你好"))
        self.assertEqual(candidates, [])


class GuardrailTests(unittest.TestCase):
    """覆盖 apply_guardrails 字段一致性校验。"""

    def _apply(self, decision: RouterDecision, query: str = "租房漏水怎么办") -> RouterDecision:
        from agent_service.router.fallback import apply_guardrails
        return apply_guardrails(
            decision,
            router_input(query),
            confidence_threshold=0.6,
            confidence_max=0.95,
        )

    def test_sub_questions_cleared_for_article_locate(self) -> None:
        """article_locate 的 sub_questions 应被强制清空。"""
        decision = RouterDecision.model_validate(decision_payload(
            agent="article_locate", task_type="article_lookup", sub_questions=["应被清空"],
        ))
        result = self._apply(decision)
        self.assertEqual(result.sub_questions, [])

    def test_sub_questions_cleared_for_contract_review(self) -> None:
        """contract_review 的 sub_questions 应被强制清空。"""
        decision = RouterDecision.model_validate(decision_payload(
            agent="contract_review", task_type="contract_review",
            execution_mode="document_analysis", need_file=True, sub_questions=["应被清空"],
        ))
        result = self._apply(decision)
        self.assertEqual(result.sub_questions, [])

    def test_sub_questions_kept_for_law_qa(self) -> None:
        """law_qa 应保留 sub_questions 用于多路检索。"""
        decision = RouterDecision.model_validate(decision_payload(sub_questions=["保留"]))
        result = self._apply(decision)
        self.assertEqual(result.sub_questions, ["保留"])

    def test_need_file_true_but_requirement_none_filled_default(self) -> None:
        """need_file=true 但 file_requirement=None 应补默认值。"""
        decision = RouterDecision.model_validate(decision_payload(
            agent="contract_review", task_type="contract_review",
            execution_mode="document_analysis", need_file=True, file_requirement=None,
        ))
        result = self._apply(decision)
        self.assertIsNotNone(result.file_requirement)
        self.assertEqual(result.file_requirement.type, "contract")

    def test_need_file_false_but_requirement_set_cleared(self) -> None:
        """need_file=false 时 file_requirement 应被清空为 None。"""
        decision = RouterDecision.model_validate(decision_payload(
            need_file=False,
            file_requirement={"type": "contract", "hint": "x"},
        ))
        result = self._apply(decision)
        self.assertIsNone(result.file_requirement)

    def test_historical_without_year_downgraded_to_current(self) -> None:
        """time_context.type=historical 但 year 缺失应降级为 current。"""
        decision = RouterDecision.model_validate(decision_payload(
            time_context={"type": "historical", "year": None},
        ))
        result = self._apply(decision)
        self.assertEqual(result.time_context.type, "current")
        self.assertIsNone(result.time_context.year)

    def test_invalid_time_type_fallback_to_latest(self) -> None:
        """time_context.type 不在枚举内应降级为 latest。"""
        decision = RouterDecision.model_validate(decision_payload(
            time_context={"type": "invalid", "year": None},
        ))
        result = self._apply(decision)
        self.assertEqual(result.time_context.type, "latest")

    def test_invalid_domain_downgraded_to_civil(self) -> None:
        """retrieval_scope.domain 不在枚举内应降级为 civil。"""
        decision = RouterDecision.model_validate(decision_payload(
            retrieval_scope={"domain": "invalid", "category": "contract", "keywords": []},
        ))
        result = self._apply(decision)
        self.assertEqual(result.retrieval_scope.domain, "civil")

    def test_high_risk_query_forces_needs_human_review(self) -> None:
        """高风险 query 应强制 needs_human_review=True。"""
        decision = RouterDecision.model_validate(decision_payload(risk_level="low"))
        result = self._apply(decision, query="别人打了我，我能还手吗")
        self.assertEqual(result.risk_level, "high")
        self.assertTrue(result.needs_human_review)

    def test_high_risk_overrides_llm_low_risk(self) -> None:
        """LLM 输出 low 但 query 含暴力关键词，应被覆盖为 high。"""
        decision = RouterDecision.model_validate(decision_payload(risk_level="low"))
        result = self._apply(decision, query="未成年人校园暴力")
        self.assertEqual(result.risk_level, "high")

    def test_agent_task_type_alignment(self) -> None:
        """contract_review Agent 应自动对齐 task_type=contract_review、execution_mode=document_analysis。"""
        decision = RouterDecision.model_validate(decision_payload(
            agent="contract_review", task_type="legal_question", execution_mode="rag",
        ))
        result = self._apply(decision)
        self.assertEqual(result.task_type, "contract_review")
        self.assertEqual(result.execution_mode, "document_analysis")

    def test_confidence_above_1_rejected_by_pydantic(self) -> None:
        """confidence > 1.0 仍应被 Pydantic 拒绝（异常值）。"""
        with self.assertRaises(Exception):
            RouterDecision.model_validate(decision_payload(confidence=1.5))


class FallbackTests(unittest.IsolatedAsyncioTestCase):
    """覆盖 fallback_from_candidates 和 low_confidence_fallback。"""

    async def test_no_candidate_no_llm_defaults_to_law_qa(self) -> None:
        """无候选且无 LLM 时应兜底到 law_qa。"""
        decision = await RouterAgent().route(router_input("你好"))
        self.assertEqual(decision.agent, "law_qa")
        self.assertTrue(decision.fallback)
        self.assertEqual(decision.confidence, 0.5)

    async def test_llm_returns_invalid_agent_falls_back(self) -> None:
        """LLM 输出非法 agent 时应走兜底。"""
        payload = decision_payload(agent="invalid_agent", confidence=0.9)
        decision = await RouterAgent(llm=StaticLLM(payload)).route(router_input("租房漏水"))
        self.assertTrue(decision.fallback)

    async def test_llm_timeout_uses_best_candidate(self) -> None:
        """LLM 超时应按最高分候选兜底。"""
        decision = await RouterAgent(llm=FailingLLM(), retry=0, timeout=1).route(
            router_input("民法典第585条是什么")
        )
        self.assertEqual(decision.agent, "article_locate")
        self.assertTrue(decision.fallback)

    async def test_memory_continuation_candidate_has_none_agent(self) -> None:
        """多轮延续候选 agent=None，不应被选为兜底 agent。"""
        memory = LegalMemory(current_case={"domain": "租赁纠纷"})
        candidates = generate_candidates(router_input("那我自己修呢", legal_memory=memory))
        continuation = [c for c in candidates if c.agent is None]
        self.assertTrue(continuation, "应存在多轮延续候选")
        from agent_service.router.fallback import _best_actionable_candidate
        best = _best_actionable_candidate(candidates)
        # agent=None 的延续候选应被跳过；无其他候选时返回 None
        self.assertIsNone(best)


class LlmAdapterTests(unittest.IsolatedAsyncioTestCase):
    """覆盖 _call_llm 对不同 LLM 接口的适配。"""

    async def test_llm_ainvoke_interface(self) -> None:
        """LLM 暴露 ainvoke 方法时应被正确调用。"""
        payload = decision_payload()

        class AInvokeLLM:
            async def ainvoke(self, messages, **_kwargs):
                return payload

        decision = await RouterAgent(llm=AInvokeLLM()).route(router_input("租房漏水"))
        self.assertEqual(decision.agent, "law_qa")
        self.assertFalse(decision.fallback)

    async def test_llm_callable_interface(self) -> None:
        """LLM 是可调用对象时应被正确调用。"""
        payload = decision_payload()

        async def llm(system, user, **_kwargs):
            return payload

        decision = await RouterAgent(llm=llm).route(router_input("租房漏水"))
        self.assertEqual(decision.agent, "law_qa")

    async def test_llm_dict_output_accepted(self) -> None:
        """LLM 返回 dict 应被直接接受，无需 JSON 解析。"""
        payload = decision_payload()
        decision = await RouterAgent(llm=StaticLLM(payload)).route(router_input("租房漏水"))
        self.assertEqual(decision.agent, "law_qa")

    async def test_llm_string_json_output_accepted(self) -> None:
        """LLM 返回 JSON 字符串应被正确解析。"""
        import json
        payload_str = json.dumps(decision_payload(), ensure_ascii=False)

        class StringLLM:
            async def chat_json(self, *a, **k):
                return payload_str

        decision = await RouterAgent(llm=StringLLM()).route(router_input("租房漏水"))
        self.assertEqual(decision.agent, "law_qa")

    async def test_llm_unsupported_interface_raises(self) -> None:
        """LLM 无任何已知接口时应触发兜底。"""
        decision = await RouterAgent(llm=object()).route(router_input("租房漏水"))
        self.assertTrue(decision.fallback)


class InferenceTests(unittest.TestCase):
    """覆盖 fallback 模块中的领域/案由/时间推断逻辑。"""

    def test_infer_domain_criminal(self) -> None:
        from agent_service.router.fallback import infer_retrieval_scope
        for q in ("刑法故意伤害", "毒品案件", "正当防卫", "赌博"):
            scope = infer_retrieval_scope(q)
            self.assertEqual(scope.domain, "criminal", f"应为 criminal: {q}")

    def test_infer_domain_administrative(self) -> None:
        from agent_service.router.fallback import infer_retrieval_scope
        for q in ("行政处罚", "行政复议", "行政许可"):
            scope = infer_retrieval_scope(q)
            self.assertEqual(scope.domain, "administrative", f"应为 administrative: {q}")

    def test_infer_domain_commercial(self) -> None:
        from agent_service.router.fallback import infer_retrieval_scope
        scope = infer_retrieval_scope("公司股权转让")
        self.assertEqual(scope.domain, "commercial")

    def test_infer_category_mapping(self) -> None:
        from agent_service.router.fallback import infer_retrieval_scope
        cases = {
            "合同违约": "contract",
            "侵权赔偿": "tort",
            "离婚抚养": "marriage",
            "加班工资": "labor",
            "公司股权": "company",
            "起诉仲裁": "procedure",
        }
        for q, expected in cases.items():
            scope = infer_retrieval_scope(q)
            self.assertEqual(scope.category, expected, f"应为 {expected}: {q}")

    def test_infer_legal_context_with_article(self) -> None:
        from agent_service.router.fallback import infer_legal_context
        ctx = infer_legal_context("民法典第585条关于违约金", "contract")
        self.assertEqual(ctx.law_name, "民法典")
        self.assertEqual(ctx.article_no, "第585条")
        self.assertEqual(ctx.cause_of_action, "合同纠纷")

    def test_infer_time_context_historical(self) -> None:
        from agent_service.router.fallback import infer_time_context
        ctx = infer_time_context("2020年当时的规定")
        self.assertEqual(ctx.type, "historical")
        self.assertEqual(ctx.year, 2020)

    def test_infer_time_context_current(self) -> None:
        from agent_service.router.fallback import infer_time_context
        ctx = infer_time_context("现行有效规定")
        self.assertEqual(ctx.type, "current")

    def test_infer_time_context_latest_default(self) -> None:
        from agent_service.router.fallback import infer_time_context
        ctx = infer_time_context("租房漏水")
        self.assertEqual(ctx.type, "latest")

    def test_infer_sub_questions_case_analysis(self) -> None:
        from agent_service.router.fallback import infer_sub_questions
        subs = infer_sub_questions("违约金调整", "case_analysis")
        self.assertEqual(len(subs), 2)
        self.assertIn("裁判规则", subs[0])

    def test_infer_sub_questions_article_locate_empty(self) -> None:
        from agent_service.router.fallback import infer_sub_questions
        subs = infer_sub_questions("民法典第585条", "article_locate")
        self.assertEqual(subs, [])


class StateMapperEdgeTests(unittest.TestCase):
    """覆盖 build_initial_state 的字段映射完整性。"""

    def test_state_includes_all_decision_fields(self) -> None:
        decision = RouterDecision.model_validate(decision_payload(
            agent="contract_review", task_type="contract_review",
            execution_mode="document_analysis", need_file=True,
            risk_level="medium", needs_human_review=False,
        ))
        state = build_initial_state(decision, router_input("审查合同"))
        self.assertEqual(state["execution_mode"], "document_analysis")
        self.assertEqual(state["risk_level"], "medium")
        self.assertEqual(state["intent"], "contract_review")
        self.assertEqual(state["legal_domain"], "contract")
        self.assertEqual(state["messages"], [])
        self.assertEqual(state["trace_id"], "")

    def test_state_sub_questions_passed_through(self) -> None:
        decision = RouterDecision.model_validate(decision_payload(
            sub_questions=["子问题1", "子问题2"],
        ))
        state = build_initial_state(decision, router_input("咨询"))
        self.assertEqual(state["sub_questions"], ["子问题1", "子问题2"])

    def test_state_retrieval_scope_serialized(self) -> None:
        decision = RouterDecision.model_validate(decision_payload())
        state = build_initial_state(decision, router_input("咨询"))
        self.assertIsInstance(state["retrieval_scope"], dict)
        self.assertIn("domain", state["retrieval_scope"])
        self.assertIn("keywords", state["retrieval_scope"])


if __name__ == "__main__":
    unittest.main()

