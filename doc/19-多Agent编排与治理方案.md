# LawRAG 多 Agent 编排与治理方案（重构设计）

> 版本：v1.0 · 状态：设计草案 · 关联文档：[16-Agent设计方案](16-Agent设计方案.md)、[17-Router Agent 设计方案](17-Router%20Agent%20设计方案.md)

## 1. 背景与目标

### 1.1 现状

当前已具备 8 个业务 Agent（`agent_service/agents/manager.py` 注册）：

| agent_key | 用途 |
|---|---|
| `law_qa` | 普通法律咨询 |
| `article_locate` | 法条定位 |
| `case_analysis` | 案例分析（联网类案） |
| `contract_review` | 合同审查（单 Agent 入口） |
| `contract_clause` | 合同理解（多阶段子 Agent） |
| `contract_rule` | 规则检测（多阶段子 Agent） |
| `contract_rag` | 法律检索（多阶段子 Agent） |
| `contract_risk_report` | 风险报告（多阶段子 Agent） |

编排层为单一 `Supervisor`（`agent_service/agents/supervisor.py`），采用**逐轮决策循环**：`decide → agent_exec → synthesize`，LLM 每轮决定调用哪个 Agent、何时合成。检索复用阶段三 `HybridRetriever`，引用合并复用 `citation_merge.py`。

### 1.2 目标

1. 把"多个 Agent"升级为真正的**多 Agent 系统**：Agent 之间有一等公民的通信与数据契约。
2. 目标链路改为 **意图识别 → 规划 → 执行 → 审查 → 合成**（plan-and-execute）。
3. 补齐治理层：可观测性、评估、状态持久化、内存分层、模型分层、HITL、安全。
4. 兼容现有 Router / Supervisor / BaseAgent / 检索链路，不推倒重来。

---

## 2. 现状缺陷清单（改造的输入）

以下缺陷是本方案要解决的直接问题，均来自对现有代码的核查。

### 2.1 高危

| # | 缺陷 | 位置 | 后果 |
|---|---|---|---|
| D1 | **引用编号在兜底路径错位** | `supervisor.py:307`（`_finish`）、`supervisor.py:350-351`（L3 兜底） | 最终答案用局部 `[n]`，引用列表是全局编号，用户点开引用错误。正常合成路径（`loader.py:134` 调 `renumber_answer_text`）没问题 |
| D2 | **合同多阶段子 Agent 数据断链** | `supervisor.py:182-189` + `base.py:177-199`（`_build_sub_state` 每次重置状态、不传 `document_id`） | `contract_rule` 看不到 `contract_clause` 产出的条款，风险报告输出空。`contract_*` 子 Agent 也进不了 `rules.py` 候选，LLM 无从选择 |
| D3 | **Supervisor 分支绕过 Router，Agent 上下文退化** | `agent.py:138-145`（SharedState 只有 5 个字段） | `legal_context` / `sub_questions` / `legal_memory` / `history_summary` / `uploaded_files` 全空 → 法条定位检索增强失效、案例分析多路检索退化为单路、多轮上下文丢失 |

### 2.2 中危

| # | 缺陷 | 位置 | 后果 |
|---|---|---|---|
| D4 | Supervisor 分支不写记忆 | `agent.py:157-178` 无 `memory.update` | 多轮延续规则（`rules.py:has_memory_continuation`）失效 |
| D5 | 合成最终答案不做引用校验 | 各 Agent `validate_node` 只校验局部答案 | 合成器可能写出不在引用列表里的 `[n]` |
| D6 | Synthesizer Prompt 膨胀 | `loader.py:135` 全量塞 `context_text` | 多轮 context 累计导致 token 浪费 |
| D7 | DeepSeek 专属参数硬编码 | `supervisor.py:282` `extra_body={"thinking":...}` | 换 provider 报错，模型层未分层 |

### 2.3 低危

- `contract_review` 不在 `ALLOWED_AGENTS` 白名单（`supervisor.py:30-38`）。
- `_judge_retrieval_quality` 非空即 `sufficient`，补检形同虚设（`base.py:435-439`）。
- `trace_id` 只取第一个 Agent 的（`supervisor.py:208-209`）。
- `/api/agent/chat` 请求体无 `uploaded_files`（`agent.py:51-56`）。
- `astream` 尾部引用合并兜底是死代码（`supervisor.py:220-224`）。

---

## 3. 目标架构总览

```
用户提问
  │
  ▼
┌─────────────────────────────────────────────────────────┐
│ ① 意图识别层  IntentLayer                                 │
│    规则预筛（复用 rules.py + fallback.py guardrails）        │
│    + LLM 结构化输出：{intent, risk_level, time_context,    │
│                        needs_files, needs_web, domain}     │
└─────────────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────────────┐
│ ② 规划层  Planner                                        │
│    LLM 产出 Plan DAG（steps + 数据契约 + 并行组）           │
│    → Agent Card 校验 → 步数/依赖守卫 → 兜底默认计划          │
└─────────────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────────────┐
│ ③ 执行层  PlanExecutor                                   │
│    按数据契约从 slot 读入参 → 执行 Agent → 产出落 slot       │
│    并行组 asyncio.gather；每步超时/重试/失败重规划钩子        │
│    checkpoint 持久化（LangGraph checkpointer）             │
└─────────────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────────────┐
│ ④ 审查层  Reviewer                                       │
│    确定性检查（引用完整性/非空/风险阈值）                     │
│    + 落地抽查（抽样论断核对引用 chunk，仅此处用 LLM）         │
│    通过 → ⑤ ；失败 → 重试出错步（≤N）→ 仍失败 → HITL 升级     │
└─────────────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────────────┐
│ ⑤ 合成层  Synthesizer                                    │
│    合并引用（复用 citation_merge）→ 全局重编号               │
│    → LLM 流式重写最终答案 → 引用校验（复用 CitationValidator）│
└─────────────────────────────────────────────────────────┘
  │
  ▼
  SSE 流式输出 + run 级 Trace 落库
```

**与现有 Supervisor 的关系**：保留现有 Supervisor 作为 `fallback` 链路（配置开关 `multiagent_v2_enabled`），新链路灰度替换。两套编排共享同一批 Agent 与工具，仅编排层不同。

---

## 4. 核心设计

### 4.1 意图识别层（IntentLayer）

**原则：规则兜底 + LLM 增强，不纯 LLM。**

- 复用现有 `rules.py` 候选与 `fallback.py` 的 `infer_retrieval_scope` / `infer_legal_context` / `infer_time_context` / `_is_high_risk`，先跑一轮**确定性预筛**。
- 规则命中率高（如明确法条定位、合同审查）时直接产出 intent，不调 LLM。
- 规则不确定时，LLM 一次结构化输出，**与规划合并为一次调用**（见 4.2），避免两次 LLM 往返。
- **必须注入**：`query + history_summary + legal_memory + uploaded_files + available_kbs`（修复 D3/D4）。

```json
{
  "intent": {
    "domain": "civil",
    "category": "general",
    "risk_level": "low",
    "time_context": {"type": "latest", "year": null},
    "needs_files": false,
    "needs_web": false,
    "legal_context": {"law_name": "刑法", "article_no": "第20条", "cause_of_action": null},
    "retrieval_scope": {"keywords": ["正当防卫", "第20条"]}
  }
}
```

### 4.2 规划层（Planner）

**核心产出：带数据契约的 Plan DAG**（修复 D2 的关键）。

```json
{
  "plan_id": "pl_xxxx",
  "query": "如何认定正当防卫？",
  "steps": [
    {
      "step_id": "s1",
      "agent": "article_locate",
      "goal": "定位正当防卫相关条文",
      "inputs": {"query": "$user", "legal_context": "$intent.legal_context"},
      "outputs": {"chunks": "slot.law_chunks", "citations": "slot.law_cites"},
      "parallel_group": "g1",
      "deps": []
    },
    {
      "step_id": "s2",
      "agent": "case_analysis",
      "goal": "检索正当防卫类似案例",
      "inputs": {"query": "$user"},
      "outputs": {"chunks": "slot.case_chunks", "citations": "slot.case_cites"},
      "parallel_group": "g1",
      "deps": []
    },
    {
      "step_id": "s3",
      "agent": "synthesize",
      "goal": "汇总条文与案例，重写最终答案",
      "inputs": {"citations": ["slot.law_cites", "slot.case_cites"]},
      "outputs": {},
      "deps": ["s1", "s2"]
    }
  ]
}
```

**关键约束**：

1. **数据契约必须闭合**：每个 step 的 `inputs` 必须能从 `$user` / `$intent` / 其他 step 的 `outputs` 解析；`outputs` 落 slot。执行器按此喂数，**杜绝"每个 Agent 独立跑一遍、结果互不相见"**（对应 `base.py:177-199` 的重置问题）。
2. **守卫校验（纯代码，不靠 LLM）**：
   - `agent ∈ AgentCard 注册表`（白名单校验，修复 `contract_review` 漏登记类问题）
   - 步数 ≤ `plan_max_steps`（默认 4）
   - 依赖无环（拓扑校验）
   - 存在至少一个"产出 citations"的 step 与合成 step
3. **规划默认克制**：法务问答大多数问题 1~2 步足够。规划器收到"单 Agent 即可覆盖"的 hint 时输出单步计划。
4. **已知工作流直通**：合同审查等**流程固定**任务，不走 LLM 规划，直接载入预置计划（见 4.6），避免 LLM 把固定流水线规划错。

### 4.3 执行层（PlanExecutor）

**执行模型**：

- 维护一个 **slot 表**（`slot.{name}`），是本次 run 的"工作记忆"。
- 按拓扑序执行 step；`parallel_group` 相同的独立 step 用 `asyncio.gather` 并行（修复现状严格串行问题）。
- 每个 step：
  - 从 `inputs` 解析实参 → 构建 `LegalAgentState`（复用 `base.py:_build_sub_state`，但**不再清空跨步依赖数据**，改为显式注入 slot 引用）
  - 执行 Agent（复用现有 `invoke_for_supervisor` 的图闭环）
  - 产出按 `outputs` 契约写入 slot
  - 记录该步 Trace（见 5.2）
- **超时/重试**：每步 `step_timeout`（默认 60s），失败重试 `step_retry`（默认 1 次，指数退避）；重试仍失败 → 触发**失败重规划钩子**（修复"计划是静态快照"的问题）。
- **失败重规划**：某步返回 `retrieval_quality=insufficient` 或执行异常时，允许 Planner 在**已产出的 slot 基础上**重规划后续步骤（最多 1 次）。

**状态持久化**：

- 用 LangGraph **checkpointer**（Postgres/Redis 存储），run 断点可恢复、可续跑（当前 `base.py:57-85` 编译图但未挂 checkpointer）。
- run 状态模型：`MultiAgentRun`（run_id、plan、slots、step 状态、trace_id、created/updated 时间）。

### 4.4 审查层（Reviewer）

**审查对象是 Agent 的原始产出（chunks + citations + 局部答案），不是最终答案**——避免污染源已被合成器改写。

**两级检查**：

| 级别 | 内容 | 实现 |
|---|---|---|
| L1 确定性（每步必做，纯代码） | 引用完整性（局部答案每个 `[n]` 在 `citations` 中存在）；检索非空；答案非空；`risk_level` 达阈值时置 `needs_human_review` | 复用 `CitationValidator` + `renumber_answer_text` |
| L2 落地抽查（合成前做一次，抽样） | 抽 1~3 个关键论断，验证其确实由被引用的 chunk 支撑 | LLM 只做抽样核验，不全文审（控制成本） |

**失败闭环**（修复 D5）：

```
审查不通过
  → 定位到出错 step（引用越界→重查引用来源；落地不符→回到该 step 重新检索）
  → 重试该 step（≤ review_retry_max=1）
  → 仍失败 → needs_human_review=true，进入 HITL 队列，答案标注"待人工复核"
```

**审查不做的**：不叫 LLM"整体评价答案质量"——同模型自审等于对错误加倍自信，纯浪费 token。

### 4.5 合成层（Synthesizer）

- 复用 `citation_merge.merge_citations` 做跨 Agent 去重 + 全局重编号。
- **所有落到 `final_answer` 的路径都必须先 `renumber_answer_text`**（修复 D1：`_finish`、L3 兜底、合成三处统一走一个函数）。
- 合成 Prompt 控制膨胀（修复 D6）：传给 Synthesizer 的 `context_text` 截断为 `synth_context_max_tokens`（如 3000），并带 `output_summary`。
- 合成完成后跑一次 `CitationValidator`（对最终答案 + 全局引用），失败回 4.4 闭环。

### 4.6 已知工作流（预置计划）

合同审查等固定流程，定义**预置 Plan 模板**，运行时替换占位符（document_id 等），不走 LLM 规划：

```json
{
  "workflow": "contract_review",
  "steps": [
    {"step_id": "w1", "agent": "contract_clause", "inputs": {"document_id": "$user.document_id"},
     "outputs": {"chunks": "slot.clauses"}, "deps": []},
    {"step_id": "w2", "agent": "contract_rule", "inputs": {"chunks": "slot.clauses"},
     "outputs": {"tool_calls": "slot.rule_risks"}, "deps": ["w1"]},
    {"step_id": "w3", "agent": "contract_rag", "inputs": {"chunks": "slot.clauses", "risks": "slot.rule_risks"},
     "outputs": {"chunks": "slot.law_chunks", "citations": "slot.law_cites"}, "deps": ["w2"]},
    {"step_id": "w4", "agent": "contract_risk_report",
     "inputs": {"clauses": "slot.clauses", "risks": "slot.rule_risks", "law": "slot.law_cites"},
     "outputs": {"answer": "slot.report"}, "deps": ["w3"]}
  ]
}
```

同时修复 `contract_*` 子 Agent 的 `_build_sub_state`，让 `document_id` 与上游 `chunks/tool_calls` 能注入。

---

## 5. 治理组件

### 5.1 Agent Card 注册表

规划器/校验器的唯一事实来源，替代 `manager.py:30-40` 的裸 dict。

```yaml
# agent_service/agents/cards/article_locate.yaml
agent_card:
  key: article_locate
  name: 法条定位
  description: 定位具体法条、条款树整理、条文解释
  when_to_use:
    - "query 含法条编号+法律名"
    - "query 含法律名+主题"
  when_not_to_use:
    - "无明确法律依据，纯咨询类"
  tools: ["article_tree"]
  inputs:
    query: {required: true}
    legal_context: {required: false, from: intent}
  outputs:
    chunks: slot.law_chunks
    citations: slot.law_cites
  retrieval: true
  top_k: 20
  rerank_top_k: 10
  temperature: 0.1
  parallel_ok: true
  model_tier: default
```

- 加载为 `AgentCardRegistry`，提供 `list()/get()/validate_plan()`。
- 规划 Prompt 注入所有 card 的 `description + when_to_use`，让 LLM 有依据选 agent（替代现在靠 `rules.py` 关键词猜）。
- 白名单从 card 派生，根治 `ALLOWED_AGENTS` 漏登记问题。

### 5.2 Run 级 Trace（可观测性）

扩展现有 `router/trace.py`，新增 `run` 维度：

```
run_id → intent / plan / 每 step 的(input, output, agent, tool_calls, llm_calls) /
        review 结果 / final_answer / cost / latency
```

- 落库表 `agent_run_trace`（run_id、user_id、plan JSON、step_traces JSON、review 结果、total_cost、latency_ms、created_at）。
- 前端/运营中心可回放一次完整 run（坏 case 复盘）。关联 `18-运营监控中心.md`。
- **每条 LLM 调用记录 cost**：`(provider, model, prompt_tokens, completion_tokens, latency_ms)`。

### 5.3 评估体系

多 Agent 系统改 prompt 会整体漂移，必须回归。建设：

- **Golden 数据集**：`tests/golden/` 下 YAML 样例：`query + 期望agent顺序 + 期望引用条数 + 参考答案要点`。
- **自动评测脚本** `scripts/eval_agents.py`：
  - 引用准确率：答案 `[n]` 是否都指向正确 chunk
  - 检索质量：命中期望法条数
  - 答案质量：LLM-as-judge（用**不同模型**做 judge，避免同模型自评）对要点命中打分
  - 规划正确率：plan 的 step 序列 vs 期望序列
- 接入 CI/回归：每次编排或 prompt 改动跑全量。

### 5.4 内存分层

现状 `RedisMemory` 仅每会话一个 `legal_memory` 对象。升级为三层：

| 层 | 存储 | 内容 | 写入时机 |
|---|---|---|---|
| 工作记忆 | slot 表（内存 + checkpoint） | 本次 run 各 step 产出 | 每 step 落槽 |
| 会话记忆 | Redis | 长对话**自动摘要压缩**（新增 summarizer，超阈值触发），当前 `legal_memory` | 合成后 |
| 长期记忆 | Redis/MySQL | 跨会话用户画像、历史案件、法律偏好 | 会话结束 |

规划层的 `intent` 输入必须读取会话记忆（修复 D3/D4）。

### 5.5 模型分层与成本控制

一次多 Agent 问答可能 10~20 次 LLM 调用，必须分层（修复 D7）：

| 用途 | 模型档位 | 说明 |
|---|---|---|
| 意图/规划/路由 | `cheap`（小模型） | 输出结构化 JSON，走 `chat_json` |
| 单步检索增强/工具结果处理 | `cheap` | 低温度 |
| 推理/合成 | `strong`（大模型） | 流式，高质 |
| 审查落地抽查 | `strong`（**不同 provider**） | 避免自评偏见 |

- LLM 调用统一走 `llm/factory.py` + 档位映射表，provider 专属参数（如 DeepSeek `thinking`）下沉到 provider 层封装，**业务代码不得出现 provider 专属参数**。
- 每 run 设 token 预算（`run_token_budget`，超预算强制合成）。

### 5.6 HITL（人工介入）

现状 `needs_human_review` 只是 bool。升级为：

- 审核队列：`human_review_task`（run_id、风险项、待复核答案、状态 pending/reviewed）。
- 暂停/恢复：checkpointer + 事件驱动，run 在 HITL 处挂起，人工结论回填后恢复。
- 前端入口：运营中心展示待审核任务。

### 5.7 安全与租户隔离

法律场景重点：

- **租户隔离**：每个 step 的工具调用与检索重新携带当前 `user_id/tenant_id` 鉴权，不依赖状态里的字段默认安全。
- **Prompt 注入防护**：检索 chunk、上传合同文本可能夹带对抗指令。在进入 LLM 上下文前，对文档来源内容加"数据边界"标记（如 `<doc>` 包裹 + 指令忽略），或抽样检测注入特征。
- **PII**：引用/答案落库前脱敏；敏感字段不进 Trace。

---

## 6. 目录与模块规划

```
agent_service/
├── orchestrator/                  # 新增：新编排层
│   ├── intent.py                  # 意图识别层
│   ├── planner.py                 # 规划层（Plan DAG 生成 + 守卫）
│   ├── executor.py                # 执行层（slot 表 + 并行 + 超时重试）
│   ├── reviewer.py                # 审查层（L1 确定性 + L2 抽样）
│   ├── synthesizer.py             # 合成层（封装现有 Synthesizer）
│   ├── run_state.py               # MultiAgentRun / slot / checkpoint
│   └── workflow.py                # 预置工作流模板（合同审查等）
├── agents/
│   ├── cards/                     # Agent Card（yaml 或 py）
│   ├── registry.py                # AgentCardRegistry（替代 _agent_classes dict）
│   ├── supervisor.py              # 保留，作为 V1 fallback
│   └── ...                        # 现有 Agent 不动
├── trace/                         # 扩展为 run 级
│   └── run_tracer.py
├── eval/                          # 评估
│   ├── golden.py
│   └── metrics.py
└── memory/
    ├── session_summarizer.py      # 会话摘要压缩
    └── long_term.py               # 跨会话长期记忆
```

---

## 7. 与现有代码的兼容/迁移策略

| 现有资产 | 处理方式 |
|---|---|
| `RouterAgent` / `rules.py` / `fallback.py` | **复用**：意图层的规则预筛 + guardrails 直接调用 |
| `BaseAgent` 图闭环（intent→…→validate） | **复用**：执行层仍调 `invoke_for_supervisor`，但状态注入改为 slot 驱动 |
| `citation_merge.py` / `CitationValidator` | **复用**：审查与合成层核心 |
| `router/trace.py` | **扩展**：新增 run 维度，不重写 |
| `RedisMemory` | **保留**：新增摘要与长期层，不替换 |
| `llm/factory.py` / `providers/` | **改造**：加 model_tier 映射，provider 专属参数下沉 |
| `Supervisor` | **保留**：配置 `multiagent_v2_enabled=false` 时走 V1，灰度切换 |
| `backend/routers/agent.py` `/chat` | 新增 `uploaded_files` 字段，入口按开关分流 V1/V2 |

**切换顺序**：新链路先在 `/api/agent/chat` 灰度 → 运营中心跑通 → 全量切换 → Supervisor 降级为只读 fallback。

---

## 8. 分期实施路线图

### P0：地基（先做，解决 D1/D2/D3 的架构根因）

- [ ] Agent Card 注册表 + 白名单派生
- [ ] Plan DAG 数据契约定义 + 守卫校验
- [ ] PlanExecutor：slot 表 + 拓扑执行 + `_build_sub_state` 改造（注入 document_id / 上游产出）
- [ ] 合同审查预置工作流模板
- [ ] 引用兜底路径统一 `renumber_answer_text`（修 D1）

### P1：链路闭环

- [ ] 意图识别层（规则预筛 + LLM 融合，注入记忆）
- [ ] 审查层（L1 确定性检查 + L2 抽样 + 重试/升级闭环）
- [ ] 合成层 Prompt 膨胀治理（修 D6）
- [ ] 失败重规划钩子

### P2：工程化

- [ ] LangGraph checkpointer（Postgres/Redis）接入
- [ ] Run 级 Trace 落库 + 运营中心回放
- [ ] 并行 step 执行（asyncio.gather）+ 每步超时/取消
- [ ] 模型分层 + cost 记录 + token 预算（修 D7）
- [ ] `/chat` 补 `uploaded_files` 与 V1/V2 开关

### P3：上线与治理

- [ ] Golden 数据集 + 自动评测 + CI 回归
- [ ] 会话摘要压缩 + 长期记忆
- [ ] HITL 审核队列 + 暂停/恢复
- [ ] 租户隔离强化 + Prompt 注入防护 + PII 脱敏

---

## 9. 风险与权衡

| 风险 | 缓解 |
|---|---|
| 规划 + 审查新增 LLM 调用，成本上升 | 意图/规划用 cheap 模型；单步即可覆盖的问题走默认单步计划；审查 L2 抽样控制 |
| 多 Agent 链路延迟变长 | 并行组；每步超时；简单问题 fast-path（意图层直接判定单 Agent） |
| LLM 规划不稳定（步数/顺序漂移） | 守卫校验 + 预置工作流 + 默认计划兜底 |
| 迁移期双链路维护成本 | Supervisor 只读保留，新链路灰度，验证稳定后冻结 V1 |
| 评估 LLM-as-judge 自评偏见 | judge 用不同 provider/模型；指标以引用准确率等确定性指标为主 |

---

## 10. 开放问题

1. Agent 间通信是否需要"Agent 作为工具被调用"的模式（层级嵌套），还是统一走扁平 Plan DAG？（当前方案倾向后者）
2. 规划结果是否需要支持用户手动确认/修改？（HITL 的规划层形态）
3. 长期记忆写入是否需用户授权？（法务 PII 合规）
4. `contract_review` 单 Agent 入口与合同多阶段工作流如何合并为一条路径？
