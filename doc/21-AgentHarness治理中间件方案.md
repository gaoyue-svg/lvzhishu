# LawAgent Harness 治理中间件方案（补全设计）

> 版本：v1.0 · 状态：设计草案 · 关联文档：[19-多Agent编排与治理方案](19-多Agent编排与治理方案.md)、[17-Router Agent 设计方案](17-Router%20Agent%20设计方案.md)、[18-运营监控中心](18-运营监控中心.md)

## 0. 文档定位

本文档是对"在 LawAgent 现有 v2 编排链路上**补全 Harness 治理层**"的工程方案，不是"从零搭建 Harness"。

核心立场：**执行层（Runtime / Retry / Review / Trace）坚决复用，不重写**；只在缺口处补 Input Guard + Evaluator + Metrics + run/step trace 落库 + Hook 注册点。

---

## 1. 现状对照（决定哪些不做）

对照用户原始 Harness 方案与当前代码现状，明确每一块的处置策略：

| Harness 模块 | 现状实现 | 处置 |
|---|---|---|
| Runtime（生命周期/上下文/事件广播） | `MultiAgentPipeline` + `PlanExecutor`（slot 表 + 拓扑 + 并行组） + `MultiAgentRun` | **复用，不重写** |
| Retry（异常恢复/重试/重规划） | `executor.step_retry` 指数退避 + `rerun_step` + `pipeline.replan_max` 闭环 | **复用，不重写** |
| Post Review（引用/落地校验） | `Reviewer`（L1 确定性 + L2 抽样） + `CitationValidator` + `needs_human_review` | **复用，不重写** |
| Trace（链路追踪） | `rag_trace` 表 + `RagTraceRouterRecorder` + `StepTrace`（仅内存） + `trace_id` 全链路透传 | **部分复用**：补 run/step trace 落库 |
| Hook 机制 | `executor.on_event` / `synthesizer.on_token` 回调 | **扩展**：补细粒度 hook 注册点 |
| Input Guard（输入安全/预算/越权） | 无 | **新增** |
| Evaluation（量化质量评分） | 仅 Reviewer 引用校验，无 citation/grounded/coverage/hallucination 量化分 | **新增**（离线优先） |
| Metrics / Prometheus / Grafana | 仅 structlog 日志 | **新增** |
| Fallback（工具级降级） | `router/fallback.py`（Router 级） + query_rewrite 降级 | **补**：工具级（Milvus→BM25、WebSearch 超时降级） |

---

## 2. 原始方案的硬伤与修订

原始 Harness 方案方向正确，但按"从零搭建"撰写，与现有代码脱节。本方案做以下修订：

### 2.1 目录命名修订

原方案用 `app/harness/`。本项目是 `backend/` + `agent_service/` + `rag_service/` + `embedding_service/` 四包结构，`AGENTS.md` 明确禁止再起新包路径。

**修订**：Harness 并入 `agent_service/`，不新开 `app/`。

```
agent_service/
    guard/          # 新增：Input Guard
    evaluator/      # 新增：离线量化评分
    metrics/        # 新增：Prometheus 指标导出
    orchestrator/   # 已有：补 hook 注册 + run/step trace 落库
```

### 2.2 数据库表数量修订

原方案 7 张新表，过半与现状重复。对照：

| 原方案表 | 现状 | 处置 |
|---|---|---|
| `agent_step` | `StepTrace`（仅内存） | 不建表，落库到 `agent_run_trace.step_traces` JSON 字段 |
| `retry_record` | `executor` 重试日志 + `StepTrace.error` | 不建表，并入 `agent_run_trace` |
| `guardrail_log` | `Reviewer.issues` + `citation_validation` | 不建表，并入 `agent_run_trace` |
| `agent_trace` | `rag_trace` | 不建表，扩展 `rag_trace` 或用 `trace_id` 关联 |
| `llm_usage` | 无 | **新建**（轻量，挂 message_id） |
| `evaluation_result` | 无 | **新建**（离线评分） |
| `user_feedback` | 无 | **新建**（点赞/点踩） |

**修订**：实际新建 4 张表（含 `agent_run_trace`），通过 `sql/migrations/002_agent_harness.sql` 落地。`sql/init.sql` 不动（遵循 `AGENTS.md` 约束）。

### 2.3 在线评估成本修订

原方案对每条请求跑 Evaluation（LLM-as-a-Judge）。项目 WebSearch 已要求用户 BYOK，成本敏感；Reviewer L2 抽查已在调 LLM。

**修订**：Evaluation 一律走**离线/抽样**：
- 在线只做确定性指标（citation_score、coverage 等可代码计算的）
- LLM-as-a-Judge 走异步队列，按抽样率（如 5%）触发
- 不阻断用户请求

### 2.4 Hook 侵入点修订

原方案称"不用改 Agent"，但 `before_rag` / `after_rag` / `before_llm` / `after_llm` 都在 `BaseAgent` 的 node 方法内部，要支持 hook 必须改每个 node。

**修订**：承认改动面，分两步：
- Phase 1：只在 `executor` / `reviewer` / `synthesizer` 的 `on_event` 边界加 hook 注册点（不动 node）
- Phase 2：才考虑 node 内部细粒度 hook（需改 `base.py` 的 `retrieve_node` / `reason_node` 等）

### 2.5 Phase 3 前置依赖修订

原方案 Phase 3 含 A/B Test + Prompt 版本管理，但当前 `prompts/loader.py` 无版本化机制，A/B 无意义。

**修订**：顺序调整为 **Prompt 版本管理 → Evaluator → A/B Test**，不可颠倒。

---

## 3. 目标架构

在现有 v2 pipeline 外侧补 Harness 层，不替换核心链路：

```text
                        ┌──────────────────┐
                        │      User        │
                        └────────┬─────────┘
                                 │
                       FastAPI Chat API
                                 │
                                 ▼
═══════════════════════════════════════════════════
              Harness 治理层（本方案补全）
═══════════════════════════════════════════════════

   ┌─────────────┐                      ┌──────────────┐
   │ Input Guard │ ──(放行)──┐    ┌──(拦截)── │ Output Guard │
   └─────────────┘          │    │          └──────────────┘
                            ▼    │
        ┌──────────────────────────────────────────┐
        │  现有 v2 Pipeline（复用，不重写）          │
        │  QueryRewrite → Intent → Planner          │
        │       → Executor(slot+拓扑+并行)          │
        │       → Reviewer(L1+L2)                   │
        │       → Synthesizer                       │
        └──────────────────────────────────────────┘
                            │
                            ▼
                   ┌────────────────┐
                   │  Hook Bus      │  ← before/after_*
                   │  (注册点)      │
                   └────────────────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
        ┌──────────┐  ┌──────────┐  ┌──────────┐
        │ Trace    │  │ Metrics  │  │ Evaluator│
        │ 落库     │  │ Prometheus│  │ 离线抽样 │
        └──────────┘  └──────────┘  └──────────┘
                            │
                            ▼
                   MySQL + Grafana
                            │
                            ▼
                          User
```

---

## 4. 模块设计

### 4.1 Input Guard（`agent_service/guard/`）

**职责**：请求进入 pipeline 前的安全与预算闸门。

**检查项**：
- 输入合法性：长度、字符集、结构化字段校验（Pydantic）
- Prompt Injection：规则 + 轻量模型检测（可选，BYOK）
- 越权访问：知识库归属、文档归属校验（复用现有 `kb` / `document` 服务）
- 敏感词：法律场景敏感词表（非通用，需业务方提供）
- 预算检查：单用户 token 配额、单请求 token 上限、并发数

**接入点**：FastAPI 中间件，挂在 `/api/agent/chat` 路由前。

**输出**：通过则放行；拦截则直接返回 4xx，不进入 pipeline。

**降级**：Guard 自身异常**不阻断**请求（fail-open），仅记录 warning。安全类检查（越权）异常才 fail-close。

### 4.2 Evaluator（`agent_service/evaluator/`）

**职责**：对 Agent 产出做量化质量评分，**离线/抽样**执行。

**指标**：
| 指标 | 计算方式 | 在线/离线 |
|---|---|---|
| `citation_score` | 引用编号是否都在 citations 列表 | 在线（确定性） |
| `coverage` | 检索命中的法条/条款覆盖度 | 在线（确定性） |
| `grounded_score` | 答案论断是否被引用原文支撑 | 离线（LLM-as-Judge） |
| `hallucination` | 答案中无引用支撑的论断比例 | 离线（LLM-as-Judge） |
| `overall` | 加权汇总 | 离线 |

**触发**：
- 在线确定性指标：每条请求都算，写入 `evaluation_result`（`mode='online'`）
- 离线 LLM 指标：按抽样率（默认 5%）入队，异步 Worker 消费，写入 `evaluation_result`（`mode='offline'`）

**不阻断**：Evaluator 任何失败只记录，不影响用户响应。

### 4.3 Metrics（`agent_service/metrics/`）

**职责**：Prometheus 指标导出，供 Grafana 可视化。

**指标分组**：

- **Agent 指标**：调用次数、成功率、失败率、平均耗时、P95、P99
- **Tool 指标**：WebSearch 成功率、OCR 成功率、Milvus 耗时、Embedding 耗时、Rerank 耗时
- **LLM 指标**：Prompt Token、Completion Token、Cost、TPS、QPS
- **RAG 指标**：Recall、Precision、Rerank Accuracy、Chunk 命中率、引用率
- **用户指标**：满意/不满意、重新提问率、继续追问率

**接入点**：
- Agent/Tool 指标：Hook Bus 回调采集
- LLM 指标：`BaseLLM` 包装层采集（`llm/` 下加 decorator）
- RAG 指标：复用 `rag_trace` 数据，定时聚合

**导出**：`/metrics` 端点（FastAPI 路由），Prometheus pull 模式。

### 4.4 Hook Bus（`agent_service/orchestrator/hooks.py`，新增）

**职责**：统一 hook 注册与触发，避免散落各处。

**Hook 点（Phase 1，边界级，不动 node 内部）**：
- `before_pipeline` / `after_pipeline`
- `before_plan` / `after_plan`
- `before_step` / `after_step`（在 `executor._run_step` 前后）
- `before_review` / `after_review`
- `before_synthesize` / `after_synthesize`

**Hook 点（Phase 2，node 级，需改 `base.py`）**：
- `before_retrieve` / `after_retrieve`
- `before_tool_exec` / `after_tool_exec`
- `before_llm` / `after_llm`

**接口**：
```
HookBus.register(event: str, handler: Callable)
HookBus.emit(event: str, ctx: dict) -> None  # 异步触发，失败只 warning
```

**约束**：
- Hook 失败**不阻断**主流程
- Hook 顺序执行，禁止互相依赖
- 同一 event 可注册多个 handler

### 4.5 Trace 落库（`agent_service/orchestrator/trace_recorder.py`，新增）

**职责**：把 `MultiAgentRun` + `StepTrace` 持久化到 `agent_run_trace` 表，与 `rag_trace` 通过 `trace_id` 关联。

**接入点**：`pipeline.run()` 结束时调用（`finally` 块，确保失败也落库）。

**复用**：`RagTraceRouterRecorder` 已有的 `trace_id` 生成与 `rag_trace` 写入逻辑不变。

---

## 5. 数据库设计

新增 4 张表，通过 `sql/migrations/002_agent_harness.sql` 落地。`sql/init.sql` 不动。

### 5.1 `agent_run_trace`（run 级全链路）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | BIGINT PK | |
| `trace_id` | VARCHAR(50) | 关联 `rag_trace.trace_id` |
| `plan_id` | VARCHAR(50) | |
| `conversation_id` | BIGINT | |
| `user_id` | BIGINT | |
| `query` | TEXT | 改写后 query |
| `intent` | JSON | 意图识别结果 |
| `plan` | JSON | Plan DAG 快照 |
| `step_traces` | JSON | `StepTrace[]` 序列化 |
| `agent_results_summary` | JSON | 各 Agent 产出摘要（不含全文） |
| `review` | JSON | Reviewer 结论 |
| `final_answer` | MEDIUMTEXT | 最终答案 |
| `final_citations` | JSON | 最终引用 |
| `needs_human_review` | TINYINT | |
| `total_latency_ms` | INT | |
| `status` | VARCHAR(20) | success/failed/hitl |
| `error` | TEXT | |
| `created_at` | DATETIME | |

索引：`trace_id`（唯一）、`conversation_id`、`user_id`、`created_at`。

### 5.2 `llm_usage`（LLM 调用计费）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | BIGINT PK | |
| `trace_id` | VARCHAR(50) | 关联 |
| `message_id` | BIGINT | 关联 `chat_message` |
| `user_id` | BIGINT | |
| `provider` | VARCHAR(30) | |
| `model` | VARCHAR(60) | |
| `prompt_tokens` | INT | |
| `completion_tokens` | INT | |
| `total_tokens` | INT | |
| `latency_ms` | INT | |
| `cost` | DECIMAL(10,6) | 估算成本 |
| `purpose` | VARCHAR(30) | router/agent/synthesize/review |
| `created_at` | DATETIME | |

索引：`trace_id`、`user_id`、`created_at`。

### 5.3 `evaluation_result`（质量评分）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | BIGINT PK | |
| `trace_id` | VARCHAR(50) | 关联 |
| `mode` | VARCHAR(10) | online/offline |
| `citation_score` | FLOAT | |
| `coverage` | FLOAT | |
| `grounded_score` | FLOAT | 离线 |
| `hallucination` | FLOAT | 离线 |
| `overall` | FLOAT | |
| `detail` | JSON | 失败论断、未覆盖法条等明细 |
| `created_at` | DATETIME | |

索引：`trace_id`、`mode`、`created_at`。

### 5.4 `user_feedback`（用户反馈）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | BIGINT PK | |
| `message_id` | BIGINT | 关联 `chat_message` |
| `trace_id` | VARCHAR(50) | |
| `user_id` | BIGINT | |
| `rating` | TINYINT | 1=赞 / 0=踩 |
| `reason` | VARCHAR(200) | 可选 |
| `created_at` | DATETIME | |

索引：`message_id`、`user_id`。

---

## 6. 技术栈选型

| 模块 | 技术 | 说明 |
|---|---|---|
| 生命周期 | 现有 FastAPI + asyncio | 不引入新框架 |
| 事件总线 | 进程内 `asyncio.Queue` + Hook Bus | 不引入 Redis Stream（跨进程暂不需要） |
| 链路追踪 | 现有 `rag_trace` + 新增 `agent_run_trace` | 暂不引入 OpenTelemetry（YAGNI） |
| 指标采集 | `prometheus-client` | 轻量，Python 原生 |
| 可视化 | Grafana | 复用运维栈 |
| 日志 | 现有 structlog | 不动 |
| 质量评估 | 自研 Evaluator + LLM-as-Judge（离线） | 复用 Reviewer L2 思路 |
| 安全护栏 | Pydantic + 规则引擎 | 不引入第三方 guardrail 库 |
| 熔断重试 | 现有 `executor` 重试 + 新增工具级 fallback | 不引入 Tenacity（YAGNI） |

**原则**：能用现有依赖解决的，不引入新库。OpenTelemetry / Tenacity 等留到 Phase 2 评估后再定。

---

## 7. 分阶段实施路线

### Phase 1：可观测性（低风险，高 ROI）

**目标**：让每一次 run 可追踪、可统计。

**任务**：
1. 新增 `sql/migrations/002_agent_harness.sql`，建 `agent_run_trace` + `llm_usage` 表
2. 新增 `agent_service/orchestrator/trace_recorder.py`，`pipeline.run()` 结束时落库
3. 新增 `agent_service/orchestrator/hooks.py`，实现边界级 Hook Bus
4. 新增 `agent_service/metrics/`，Prometheus 指标导出 + `/metrics` 路由
5. `BaseLLM` 包装层加 token/cost 采集，写入 `llm_usage`

**验证**：
- 一条 chat 请求结束后，`agent_run_trace` 有完整记录，`step_traces` 含每步耗时
- `/metrics` 端点可被 Prometheus 抓取
- Hook Bus 注册一个打印 hook，能在 step 前后触发

**不动**：pipeline / executor / reviewer / agent 内部逻辑。

### Phase 2：可靠性（中风险）

**目标**：补齐安全闸门与降级能力。

**任务**：
1. 新增 `agent_service/guard/`，Input Guard 中间件
2. 工具级 Fallback：Milvus 异常→BM25、WebSearch 超时→跳过
3. 预算控制：单用户 token 配额（基于 `llm_usage` 聚合）
4. `agent_service/evaluator/` 在线确定性指标（citation_score / coverage）
5. 新增 `evaluation_result` + `user_feedback` 表与接口

**验证**：
- 越权访问知识库被 Guard 拦截返回 4xx
- Milvus 故障时请求仍能返回（降级 BM25）
- 用户点踩后 `user_feedback` 有记录

**不动**：Phase 1 已落地的 trace/metrics 逻辑。

### Phase 3：质量与迭代（较高风险）

**目标**：建立量化评估与 A/B 能力。

**前置**：先做 Prompt 版本管理（`prompts/loader.py` 扩展版本字段）。

**任务**：
1. `prompts/loader.py` 支持 Prompt 版本与切换
2. Evaluator 离线 LLM-as-Judge Worker（消费 `evaluation_result` 离线队列）
3. A/B Test 框架（按 `user_id` 哈希分流，记录 prompt 版本）
4. RAG 指标聚合（Recall / Precision，基于 `rag_trace` 离线计算）

**验证**：
- 离线 Worker 按抽样率产出 `grounded_score` / `hallucination`
- 同一问题用两个 Prompt 版本跑，结果可对比

**不动**：在线请求链路仍不跑离线评估。

---

## 8. 与现有约束的兼容性

| 约束（来自 `AGENTS.md` / 项目规范） | 本方案遵守情况 |
|---|---|
| 不再起新包路径（`rag-service` 等） | Harness 并入 `agent_service/`，不新开包 |
| `sql/init.sql` 不动 | 走 `sql/migrations/002_agent_harness.sql` |
| 接口返回 `ApiResponse[T]` | Guard / feedback 接口遵循 |
| 数据库访问用 `AsyncSession` | trace_recorder / metrics 全异步 |
| 关键处中文注释 + 文件头注释 | 新增文件遵循 |
| 删除知识库顺序 chunk→document→base | Guard 越权校验复用现有服务，不触碰删除逻辑 |
| Milvus 删除 best-effort | 工具级 fallback 遵循，失败只 warning |
| OCR 用 RapidOCR | Guard 不涉及，Metrics 采集 OCR 成功率即可 |
| WebSearch BYOK | Evaluator 离线 LLM 也走 BYOK，不 fallback 全局 key |

---

## 9. 风险与对策

| 风险 | 对策 |
|---|---|
| Hook Bus 注册点侵入 node 内部改动面大 | Phase 1 只做边界级 hook，node 级 hook 推迟到 Phase 2 评估后 |
| 离线 Evaluator LLM 成本失控 | 抽样率配置化（默认 5%），可按 trace_id 哈希采样 |
| `agent_run_trace` 写入失败拖垮请求 | `finally` 块内 best-effort，失败只 warning，不抛异常 |
| Prometheus 指标基数爆炸 | Agent/Tool 指标用固定 label，不把 `trace_id` / `query` 作为 label |
| Guard 误拦正常请求 | Guard fail-open（非安全类），安全类校验单独 review 规则 |
| Prompt 版本管理推迟 Phase 3 | 明确前置依赖，Phase 3 不提前做 A/B |

---

## 10. 不做的事（YAGNI）

明确排除以下内容，避免过度设计：

- **不新建 `app/harness/` 顶级目录**：并入 `agent_service/`
- **不新建 7 张表**：实际只建 4 张，其余复用现有表或 JSON 字段
- **不引入 OpenTelemetry**：现有 `rag_trace` + `agent_run_trace` 足够，OTel 留待 Phase 2 评估
- **不引入 Tenacity**：`executor` 已有重试逻辑，工具级 fallback 用简单 try/except
- **不在在线链路跑 LLM-as-Judge**：一律离线抽样
- **不做 node 级 Hook（Phase 1）**：边界级 hook 已覆盖 80% 场景
- **不重写 pipeline / executor / reviewer**：复用现有 v2 链路

---

## 11. 后续动作

1. 本方案评审通过后，先出 **Phase 1 最小改动 PR**：
   - `sql/migrations/002_agent_harness.sql`（建表）
   - `agent_service/orchestrator/trace_recorder.py`（run/step trace 落库）
   - `agent_service/orchestrator/hooks.py`（边界级 Hook Bus）
   - `agent_service/metrics/`（Prometheus 导出）
2. Phase 1 验证通过后，再启动 Phase 2 的 Input Guard 与工具级 Fallback。
3. Phase 3 启动前，先完成 Prompt 版本管理独立改造。
