# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> 本仓库详细的分阶段现状与编码规范见同目录 `AGENTS.md`（Claude 会一并读取）。本文档补充**需要跨文件阅读才能理解的系统级架构**与**开发命令速查**，避免与 AGENTS.md 重复。代码注释、`doc/` 设计文档均为中文，标识符与配置项为英文。

## 项目概览

LawAgent（又名 LawRAG）：中文法律 AI 助手平台。Vue 3 前端 + **单一 FastAPI 后端**，集成了混合检索 RAG、多 Agent 编排、合同审查。开发阶段见 `doc/12-项目路线图.md`，当前已完成基础工程 / 知识库入库 / Embedding与检索，正在演进 AI 问答与 Agent 能力。

**演进原则：先灰度后落地。** 新链路默认关闭，通过 `backend/config.py` 中的布尔开关灰度；关闭时自动回退旧链路（如 `multiagent_v2_enabled=false` 走 Supervisor V1，Milvus 不可用降级 BM25）。

## 常用命令

依赖用 uv 管理；测试用 **unittest**（非 pytest，虽然 pytest 也可运行这些类）。

```bash
uv sync                                       # 安装/同步 Python 依赖
uv run uvicorn backend.main:app --reload --port 8000   # 启动后端（Swagger: http://localhost:8000/docs）
uv run python -m compileall backend rag_service embedding_service tests   # 语法检查
uv run python -m unittest tests.test_retrieval_core -v   # 运行单个测试模块
uv run python -m unittest discover -s tests -v           # 运行全部测试
```

前端（Vite，端口 5173，dev 代理 `/api` → `http://localhost:8000`，见 `frontend/vite.config.ts`）：

```bash
cd frontend
npm run dev      # 开发服务器
npm run build    # vue-tsc 类型检查 + vite build
npm run lint     # eslint --fix
```

基础设施（Milvus + etcd + MinIO，`docker/docker-compose.yml`）；MySQL 与 Redis 默认连本机 3306 / 6379：

```bash
docker compose -f docker/docker-compose.yml up -d
```

独立 Worker（生产用；开发环境默认 `inline_workers=true`，后端进程已内嵌四个 Worker，无需手动启动）：

```bash
uv run python -m backend.worker.parser              # 文档解析
uv run python -m embedding_service.worker.embedding # 向量化
uv run python -m backend.worker.contract_review     # 合同规则审查
uv run python -m backend.worker.evaluator           # 离线 LLM 评估（消费 evaluation 流）
```

运行配置全部来自 `.env`（`backend/config.py` 的 `Settings`）。`sql/migrations/` 放增量迁移；`sql/init.sql` 与 `doc/` 是基础设计资产，除非任务明确要求否则不要改动。

## 架构总览

后端是**一个 FastAPI 应用**，聚合三处路由：`backend/routers/`（业务）、`agent_service/routers/agent.py`（`/api/agent`，真正的对话引擎，SSE）、`rag_service/routers/retrieval.py`（`/api/retrieve`，检索实验室）。聚合逻辑在 `backend/routers/__init__.py`；入口与全部依赖初始化在 `backend/main.py` 的 `lifespan` 中（BM25、Milvus、Tokenizer、RouterAgent、AgentManager、MCP 客户端、EmbeddingCache、内嵌 Worker 等全部挂 `app.state`）。

数据流分层：

- `backend/`：路由 / 服务 / ORM 模型 / Worker / OSS 存储。职责：鉴权、知识库与文档、上传→解析→分块→入队。
- `rag_service/retrieval/`：混合检索管线。`HybridRetriever.retrieve()` = 查询改写 → QueryRouter（给出 RRF 权重）→ 并行 BM25 + Milvus → RRF 合并 → **MySQL 回填** → 重排 → Citation → Context。**Milvus 只当索引/存过滤用标量字段，MySQL 是权威数据源，检索后必须批量回查补齐。**
- `embedding_service/`：上下文增强（只生成 Embedding 文本，**不**改 `knowledge_chunk.text`）→ 缓存（key = SHA256，含 tenant/provider/model/dimension）→ Milvus upsert → 回写 `vector_id` → BM25 增量更新。
- `agent_service/`：多 Agent 系统（见下）。
- `frontend/`：Vue 3 + Element Plus + UnoCSS。对话页**纯 SSE 驱动、无轮询**（`src/api/agent.ts` 用 `fetch` + ReadableStream 手工解析 `data:` 帧）。

## 多 Agent 系统（agent_service/）

两代编排**驱动同一批业务 Agent 与 `SharedState`**，且发出相同的 SSE 事件名（`node_start/node_end/token/citation/final/done`；v2 另发 `v2_plan/agent_start/agent_end`），前端无感切换：

- **Supervisor V1**（`agents/supervisor.py`，默认路径：`supervisor_enabled=true`）：手写决策循环（有意不用 LangGraph `astream`，以便自定义 SSE 事件），逐轮让 LLM 输出 `SupervisorDecision`（call_agent / synthesize / finish），有 max_rounds / max_agent_calls 守卫。业务 Agent 是 `agents/base.py` 里的 LangGraph `StateGraph`（intent→retrieve→tool→reason→citation→validate）；`invoke_for_supervisor()` 是其非流式结构化调用入口。
- **多 Agent v2**（`agent_service/orchestrator/`，`multiagent_v2_enabled=false` 灰度）：五层管线 `pipeline.py`——查询改写→意图→规划（PlanDAG）→执行（slot 表 + 拓扑并行）→审查（L1 确定性 + L2 LLM 抽样）→合成。**聊天中上传了合同文件会强制走 v2**（`agent_service/routers/agent.py:129-133`）。规划受 `AgentCardRegistry`（`agents/registry.py` + `agents/cards/*.yaml`）约束：这是 Agent 白名单与 `validate_plan` 守卫（环检测、步数上限、必须含 synthesize 步）的单一事实来源。

业务 Agent：`law_qa`、`article_locate`、`case_analysis`、`contract_review`，加 `agents/contract/` 下 5 个合同子 Agent（clause / rule / rag / elements / risk_report）。合同审查走固定 workflow 模板（`orchestrator/workflow.py`）绕开 LLM 规划。

- **Router Agent**（`agent_service/router/`）：纯决策层，不检索不回答。规则出候选 → LLM 确认 → guardrails → fallback（confidence<0.6 落到 law_qa）。
- **LLM 为 BYOK、按用户隔离**：`llm/dependencies.py` 的 `get_llm()` 按用户读取其保存的 provider/model/key（`user_llm_config` 表，密钥 Fernet 加密），失败回退全局 `.env`。所有 LLM JSON 解析统一走 `parse_json_object`（json_repair 兜底）；provider 特有参数只在 provider 层处理（如 DeepSeek 关闭思考模式）。
- **关键不变量**：跨 Agent 最终答案的 `[n]` 引用必须基于全局合并后的 citation 列表重编号（`agents/citation_merge.py`）。**一切优雅降级**：LLM 失败→规则兜底，工具失败→`available=false`，合成失败→最后回答兜底并重编号。

### Harness 治理层（doc 21 已实现 Phase 1+2+3）

复用 v2 编排不重写，只在边界补可观测 / 护栏 / 评估 / A/B，**所有埋点与落库 best-effort（失败只 warning，绝不阻断在线请求）**：

- **可观测**：`pipeline.run()` 用 try/finally 包裹整个 body，`orchestrator/trace_recorder.py` 的 `finalize_run` 落 `agent_run_trace`（run/step trace + `experiment_variant`）；`orchestrator/hooks.py` 的 HookBus 提供 `before/after_pipeline/plan/step/review/synthesize` 边界事件，`metrics/` 注册 Prometheus 指标（Agent/Pipeline/LLM/降级/护栏）与 `GET /metrics`、`GET /api/harness/metrics/rag`；`llm/usage.py` 的 UsageCollector 按请求采集 token/成本（provider 非流式读真实 `usage`、流式 tiktoken 估算），冲刷 `llm_usage`。
- **护栏**：`guard/run_input_guard` 在 `/api/agent/chat`、`/contract/review`、`/route` 端点开头执行（输入合法性 / 提示注入 / 敏感词 / 越权 fail-close / 预算 429 / 并发），拦截抛 HTTPException 由 `exception.py` 转 `ApiResponse`。
- **评估**：`evaluator/online.py` 每请求算 citation_score/coverage 落 `evaluation_result`（online）；`evaluator/judge.py` 离线 LLM-as-Judge（grounded/hallucination），由 `backend/worker/evaluator.py` 按 `evaluation_sample_rate`（默认 5%）抽样消费 `lawrag:stream:evaluation`，走 BYOK 不回退全局 key。
- **A/B**：`experiment/ab.py` 按 user_id 哈希稳定分流；`prompts/loader.py` 支持 prompt 版本（缓存按 `(name, version)` 键 + 请求级 `set_prompt_versions` 覆盖 + `settings.prompt_version_overrides`），`synthesizer` 运行时解析 prompt 版本；变体写入 `agent_run_trace.experiment_variant`。

## 合同审查链路（最新功能）

`POST /api/agent/upload`（`backend/routers/chat_upload.py`）→ 临时文件落 `chat_upload` 表（24h TTL，不写知识库）→ 解析（MinerU / OCR / 降级链，见 `backend/services/parser.py`、`ocr.py`、`ocr_aliyun.py`）。随后：

1. 前端在聊天请求里带 `uploaded_files`，`/api/agent/chat` 检测到合同上传即强制 v2 编排，把条款注入 `plan_slots.clauses`。
2. 合同子 Agent 产出条款理解 / 规则检测 / 法条检索 / 要素提取 / 风险报告；`_persist_contract_analysis` 写回 `chat_upload.analysis_*` 字段。
3. 前端 `ContractResultCard` 展示结构化要素 + 风险清单；`GET /api/agent/upload/{id}/report` 经 `backend/services/report_exporter.py`（python-docx）导出 .docx 报告。

另有独立 Worker 链路：`backend/worker/contract_review.py`（Redis Stream `lawrag:stream:contract_review`）对上传或知识库合同做**确定性规则检测**（`agent_service/tools/contract.py` 的 `ContractRiskRuleTool`），写 `contract_risk` 表并算 risk_score；LLM 深度报告由 `/api/agent/contract/review` SSE 单独生成。

## 任务队列

四个 Redis Stream（`backend/worker/task_queue.py`）：`lawrag:stream:document_parse`、`lawrag:stream:chunk_embedding`、`lawrag:stream:contract_review`、`lawrag:stream:evaluation`（离线 LLM 评估）。Worker 按组消费，`XAUTOCLAIM` 回收陈旧消息；单条消息必须 try/finally ACK，坏消息不能拖垮 Worker。

## 关键约定（细节见 AGENTS.md）

- 包目录用下划线：`rag_service`、`embedding_service`，**不要**用连字符的包路径。
- 每个文件头部用中文注释说明作用，关键处加中文注释；docstring 中文，标识符 / Agent key / 配置项英文。
- `rag_service` 与 `embedding_service` 不得互相 import 对方内部实现（会循环依赖）；通用 token 计数/截断在 `backend/utils/tokenizer.py`。
- 接口统一 `ApiResponse[T]`；数据库访问用 AsyncSession，避免同步阻塞。
- Milvus 只存检索过滤所需的精简标量字段；完整 metadata 以 MySQL 为权威。
- Harness 治理层已实现（doc 21 Phase 1+2+3）：新增表 `agent_run_trace` / `llm_usage` / `evaluation_result`（`sql/migrations/007_agent_harness.sql`，已并入 `sql/init.sql`）；模块在 `agent_service/` 下（`guard/`、`evaluator/`、`metrics/`、`experiment/`、`llm/usage.py`、`orchestrator/hooks.py`、`orchestrator/trace_recorder.py`）。`sql/init.sql` 含 `DROP TABLE` 全量重建语义，手动跑会清空现有数据。

## 测试

`tests/` 按模块命名，用 unittest 风格 + 桩（FakeLLM 等），覆盖检索核心（`test_retrieval_core.py`）、多 Agent（`test_agents.py`、`test_supervisor.py`、`test_orchestrator.py`）、Router（`test_router.py`）、合同（`test_contract_analysis.py`）、查询改写（`test_query_rewrite.py`）、Harness 治理层（`test_harness_models.py`、`test_hooks.py`、`test_trace_recorder.py`、`test_llm_usage.py`、`test_guard.py`、`test_evaluator.py`、`test_evaluator_offline.py`、`test_prompt_versioning.py`、`test_ab.py`、`test_rag_aggregation.py`）、MCP、LLM 等。运行命令见上文；新测试应避免依赖真实 MySQL/Redis/OSS/Milvus。
