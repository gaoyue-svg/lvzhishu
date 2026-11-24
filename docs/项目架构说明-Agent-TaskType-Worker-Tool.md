# LawAgent 项目架构说明

> 保存于 2026-11-07。用于测试结束后结合代码阅读，避免再次生成。

可以先用一句话理解整个项目：

> `task_type` 表示“用户想完成什么任务”，Agent 表示“由哪个专业角色处理”，Tool 表示“Agent 可调用的能力”，Worker 表示“后台异步加工数据的进程”，Supervisor/Pipeline 表示“如何组织这些 Agent”。

## 1. Agent 与 task_type

二者不是一一对应关系：

- `task_type`：业务意图，说明这是什么任务。
- `agent`：执行者，说明由谁完成。
- `execution_mode`：执行方式，说明采用什么流程。

例如：

```json
{"task_type":"document_generation","agent":"law_qa","execution_mode":"rag"}
```

表示这是文书生成任务，当前复用法务问答 Agent 的知识库检索能力，但按正式文书模式输出。

| task_type | 含义 | 默认 Agent | 特点 |
|---|---|---|---|
| `legal_question` | 普通法律咨询 | `law_qa` | 检索法规并结合事实回答 |
| `article_lookup` | 法条定位 | `article_locate` | 重视法律名称、条号、章节和原文 |
| `contract_review` | 合同审查 | `contract_review`/合同 Pipeline | 分析合同条款和风险 |
| `case_search` | 案例检索 | `case_analysis` | 本地类案检索，必要时联网 |
| `document_generation` | 合同、函件等文书生成 | 当前复用 `law_qa` | 检索示范文本，只输出文书本体 |

`legal_question` 和 `document_generation` 都可以由 `law_qa` 执行，因为它们都需要法规和知识库检索，但前者输出分析，后者只输出正式文书。未来可再拆出独立的 `document_generate` Agent。

## 2. 当前 Agent

| Agent | 中文名称 | 负责什么 | 使用场景 |
|---|---|---|---|
| `law_qa` | 法务问答 | 综合咨询、法规检索、事实适用、文书起草 | 普通咨询、赔偿、量刑、模板生成 |
| `article_locate` | 法条定位 | 法律、条号、章节和原文定位 | 明确询问某部法律或某一条 |
| `case_analysis` | 案例分析 | 类案检索和裁判规则归纳 | 案例、判例、法院怎么判 |
| `contract_review` | 合同审查 | 单 Agent 合同审查入口 | 上传合同要求快速审查 |
| `contract_clause` | 条款理解 | 读取并结构化合同条款 | Pipeline V2 第一步 |
| `contract_rule` | 规则检测 | 确定性合同风险规则 | 条款结构化后 |
| `contract_elements` | 要素提取 | 提取主体、金额、期限、管辖等 | 合同结构化摘要 |
| `contract_rag` | 合同法条检索 | 针对风险条款找法律依据 | 合同审查流程 |
| `contract_risk_report` | 风险报告 | 汇总条款、规则、法规和要素 | 合同 Pipeline 报告阶段 |

每个 Agent 有 YAML 卡片，定义适用/不适用场景、输入输出槽位、工具、检索参数、温度和并行能力。代码见 `agent_service/agents/cards/`。

## 3. 当前 Worker

| Worker | 队列 | 负责什么 | 何时运行 |
|---|---|---|---|
| 文档解析 Worker | `document_parse` | 解析 PDF/DOCX/TXT、切块、构建父子 Chunk | 上传知识库文档后 |
| Embedding Worker | `chunk_embedding` | 生成向量、写 Milvus、更新 BM25 | 解析完成后 |
| 合同审查 Worker | `contract_review` | 异步执行合同规则并保存风险 | 合同异步审查任务 |
| 离线评估 Worker | `evaluation` | LLM-as-Judge 检查依据和幻觉 | 抽样质量评估 |

Worker 不直接回答用户，只负责后台加工。`TaskQueue` 是 Redis Stream 队列封装，不是 Worker。

```text
上传 PDF → 解析 Worker → Chunk → Embedding Worker → Milvus/BM25 → Agent 检索
```

## 4. 当前 Tool

| Tool | 使用者 | 作用 |
|---|---|---|
| `article_tree` | `article_locate` | 整理法律→编→章→节→条层级 |
| `web_search` | `case_analysis` | 搜索公开案例和网络资料 |
| `ocr_extract` | 合同/文档流程 | 扫描件 OCR；当前未启用时明确返回不可用 |
| `contract_clause_parser` | `contract_review` | 按条、款、章节切分合同 |
| `contract_risk_rules` | `contract_review`、`contract_rule` | 检查空白、单方解除、违约金、管辖、自动续期等风险 |

Milvus、BM25、Embedding、Reranker、Context Builder、引用校验、短期记忆和查询改写属于 Agent 基础设施，不一定显示成 Tool。

## 5. 当前 Prompt

Prompt 统一登记在 `agent_service/prompts/registry.yml`。

### System Prompt

| Prompt | 使用者 | 作用 |
|---|---|---|
| `router_system` | Router | 判断 task_type、Agent、检索范围和风险 |
| `base_agent_system` | BaseAgent | 业务 Agent 共用约束 |
| `law_qa_system` | 法务问答 | 结论、边界、数字和引用规则 |
| `article_locate_system` | 法条定位 | 原文、条号、层级和版本 |
| `case_analysis_system` | 案例分析 | 案例来源和裁判规则 |
| `contract_review_system` | 合同审查 | 合同要素、风险和修改建议 |
| `supervisor_system` | Supervisor V1 | 决定调用、继续、合成或结束 |
| `contract_supervisor_system` | 合同编排 | 约束合同审查固定步骤 |
| `synthesizer_system`/`v2` | 合成器 | 合并多个 Agent 结果和引用 |
| `intent_system` | Pipeline V2 意图层 | 输出结构化意图 |
| `planner_system` | Pipeline V2 Planner | 生成 Plan DAG |
| `reviewer_system` | Pipeline V2 Reviewer | 检查完整性和幻觉 |
| `query_rewrite_system` | 查询改写 | 纠错、口语转法律术语 |
| `evaluator_judge_system` | 离线评估 | grounded 和幻觉评分 |

### User Prompt 模板

| 模板 | 用途 |
|---|---|
| `base_reason_user` | 注入问题、记忆、检索上下文和工具结果 |
| `contract_review_user` | 注入合同原文、维度、规则风险和法规 |
| `retry_hint` | 引用校验失败后的修正提示 |

Prompt 的基本写法是：角色 + 输入说明 + 硬性要求 + 禁止事项 + 场景专项规则 + 推荐结构 + Few-shot。

房屋租赁合同模板问题会依次涉及：

```text
router_system → document_generation
supervisor_system → law_qa
law_qa_system → 正式文书专项规则
base_reason_user → 注入问题和知识库材料
synthesizer_system → 只保留合同正文
```

部分 Prompt 在进程启动时缓存，因此修改后需要重启后端。

## 6. 整体执行逻辑

### 知识库入库

```text
上传文件
  → Redis 解析任务
  → 文档解析 Worker
  → 文本提取/结构识别/Chunk/父子块
  → Embedding Worker
  → 向量写入 Milvus + 更新 BM25
  → 可供 Agent 检索
```

### 在线问答

```text
用户问题
  → Input Guard（权限/并发/安全）
  → 加载知识库、历史消息、短期记忆
  → 选择 Pipeline V2 / Supervisor V1 / 单 Agent 兜底
  → Router/Intent 识别 task_type、agent、scope、risk、mode
  → Agent 执行查询改写、混合检索、重排、工具、LLM、引用校验
  → Synthesizer 合成
  → SSE 返回前端
  → 保存消息、引用、Trace、Token 和短期记忆
```

## 7. Supervisor V1 与 Pipeline V2

### Supervisor V1

Supervisor V1 每轮动态决定：

```text
call_agent / synthesize / finish
```

一个 Agent 足够就结束，只有材料不足时才继续调用。例如普通劳动问题通常只调用 `law_qa`；具体法条加事实适用时可能先 `article_locate`，再 `law_qa`。优点是成本低、响应快，适合开放式咨询。

### Pipeline V2

Pipeline V2 是计划型、依赖型编排：

```text
意图识别 → Planner DAG → 依赖执行 Agent → Reviewer → Synthesizer
```

合同审查使用代码中固定的预置工作流，而不是让 LLM 临时决定：

```text
w1 条款理解
      ├────────┬────────┐
      ↓        ↓        ↓
w2 规则检测  w3 要素提取  w4 法条检索
      └────────┴────────┘
               ↓
          w5 风险报告
               ↓
          w6 最终合成
```

- 条款理解输出 `slot.clauses`；
- 规则检测输出 `slot.rule_risks`；
- 要素提取输出 `slot.elements`；
- 法条检索输出 `slot.law_context` 和引用；
- 风险报告依赖上述结果；
- 最终合成依赖风险报告。

步骤不会随意缺少，是因为 Plan 由代码固定，并校验 Agent 白名单、依赖、循环、步骤上限和合成节点。

Worker 不属于 V1/V2 的现场推理，它们提前准备文档和向量；Tool 由 Agent 调用；Supervisor/Pipeline 负责安排 Agent。

## 8. 最终关系

```text
task_type（任务语义）
  ↓
Supervisor V1 / Pipeline V2（执行顺序）
  ↓
Agent（业务推理）
  ↓
Tool（具体能力）
  ↓
Worker 预先准备的数据（文档、Chunk、向量、规则结果）
```

- 普通咨询追求够用即可：Supervisor V1 通常只用一个 Agent。
- 合同审查追求完整和可审计：Pipeline V2 固定执行整套流程。
- Tool 是 Agent 的能力，不是同级 Agent。
- Worker 是后台数据加工，不参与现场法律推理。
