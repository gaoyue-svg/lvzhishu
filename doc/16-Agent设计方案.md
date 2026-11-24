# 任务：LawRAG 阶段四 — Agent 开发（LangGraph 编排 + 多 Agent 闭环）

## 项目背景

LawRAG 法律 RAG 平台，已完成：

- ✅ 阶段一：FastAPI 后端骨架（用户注册/登录/JWT鉴权）
- ✅ 阶段二：知识库与文档入库（OSS 上传 → Parser Worker 异步解析 → Chunk 切分 + Metadata 抽取 → `knowledge_chunk` 表）
- ✅ 阶段三：Embedding 与检索核心闭环（`rag_service` 混合检索 + `embedding_service` 向量化，已具备 HybridRetriever / RuleLegalReranker / CitationBuilder / ContextBuilder / RAG Lab 调试接口）
- ✅ 阶段四（前置）：Router Agent 编排层路由已完成（`agent_service/router/`，规则候选 + LLM 确认 + 兜底 + guardrails + trace，已通过 13 个单元测试，详见 [doc/17-Router Agent 设计方案.md](file:///g:/agent-project/LawRAG/doc/17-Router%20Agent%20设计方案.md)）

本阶段继续开发 **阶段四：业务 Agent**。Router 已就绪并产出 `RouterDecision`，本阶段把"可检索的 RAG 引擎"升级为"可对话、可推理、可引用、可追溯的法律智能体"，核心是 4 个业务 Agent（law_qa / article_locate / contract_review / case_analysis）消费 Router 输出并完成 LangGraph 闭环。

---

## 已确认的关键决策（与用户对齐）

| # | 决策点 | 选定方案 | 理由 |
|---|--------|----------|------|
| 1 | Agent 编排框架 | **LangGraph** | 契合法律多步骤状态流（路由→检索→推理→引用→校验），支持条件分支与人工介入 |
| 2 | 首期 Agent 范围 | law_qa + article_locate + contract_review + case_analysis（4 个） | 覆盖 P0 闭环 + 案例分析（联网版） |
| 3 | LLM 接入 | **多 provider 抽象 + SSE 流式 + BYOK 按用户注入** | 与 EmbeddingFactory 同款注册表模式；用户 LLM 配置存 `user_llm_config`（API Key 加密），Router 和业务 Agent 共用同一套 BYOK，`.env` 仅作兜底 |
| 4 | 工具调用 | **内部 Python 函数工具**，接口预留 MCP | 同进程零网络开销，可行性最高，未来可平滑迁移 MCP |
| 5 | 案例分析数据源 | **不走本地案例库，改 Tavily 联网搜索** | 案例库未建，联网搜索覆盖更广 |
| 6 | 联网结果引用 | **纳入引用体系**（独立"网络来源"类别） | 与法条引用并列，可追溯 |
| 7 | 合同审查解析 | **走 OCR**（MinerU 优先 + PaddleOCR 兜底） | 合同多为扫描件，需 OCR 才能拿到文本 |

---

## 核心理念：复用阶段三，不重造轮子

### 不要做的事

- **不要重写检索链路** — 阶段三 `HybridRetriever` 已闭环（Query Rewrite → BM25+Milvus → RRF → Rerank → Citation → Context），Agent 节点直接调用
- **不要在 Agent 里塞检索逻辑** — Agent 的 Retrieve 节点只调用 `HybridRetriever.retrieve()`，拿到 `RetrievalResult`（含 chunks + citations + context_text + trace）
- **不要让 LLM 直接产生法条引用** — 法条引用必须来自检索结果（CitationBuilder 产出），LLM 只负责"引用编号 + 分析推理"
- **不要做 LLM 生成法条原文** — 防幻觉红线：法条原文必须从 `knowledge_chunk.text`（MySQL 权威）取，LLM 不得凭记忆复述法条

### 正确做法

```text
用户问题
  ↓
RouterAgent（已实现，编排层路由）→ RouterDecision（agent / task_type / retrieval_scope / ...）
  ↓
AgentManager.get_agent(decision.agent) → 4 个业务 Agent 之一
  ↓
LangGraph Agent（节点编排，初始 State 由 build_initial_state 注入）
  ├── Intent 节点      → 领域细化（task_type 已由 Router 识别，不推翻）
  ├── Retrieve 节点    → 调用阶段三 HybridRetriever（不重写，按 retrieval_scope/time_context 过滤）
  ├── Reason 节点      → LLM 基于 ContextBuilder 产出物推理（引用编号 [1][2]）
  ├── Citation 节点    → 复用阶段三 CitationBuilder + 新增网络来源引用
  └── Validate 节点    → Citation Validator 校验引用真实性（防幻觉，risk_level=high 强制人工审核）
  ↓
SSE 流式返回（回答 + 引用 + 风险提示）
```

---

## 关键设计一：LLM 抽象层（多 provider + SSE 流式）

新建 `agent_service/llm/`，与 `embedding_service/embedding/embedding.py` 的 `EmbeddingFactory` 同款注册表模式。

```python
# agent_service/llm/base.py
from abc import ABC, abstractmethod
from typing import AsyncIterator

class LLMMessage(TypedDict):
    role: str           # system / user / assistant / tool
    content: str
    tool_call_id: str | None = None
    name: str | None = None

class BaseLLM(ABC):
    """LLM 抽象基类。所有 provider 实现统一接口，Agent 只依赖 BaseLLM。"""

    @abstractmethod
    async def chat(self, messages: list[LLMMessage], **kwargs) -> str:
        """非流式对话（用于意图识别、要素抽取等短输出场景）"""

    @abstractmethod
    async def stream(self, messages: list[LLMMessage], **kwargs) -> AsyncIterator[str]:
        """流式对话（用于最终回答生成，SSE 推给前端）。
        yield 文本增量片段。"""

    @abstractmethod
    async def chat_with_tools(
        self, messages: list[LLMMessage], tools: list[dict], **kwargs
    ) -> dict:
        """带工具调用的对话（function calling）。
        返回: {"content": str|None, "tool_calls": [{"id","name","args"}]}"""

    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @property
    @abstractmethod
    def supports_tool_call(self) -> bool: ...

class LLMFactory:
    """注册表模式。新增 provider 只需 register，不修改 create()。
    与 EmbeddingFactory 完全一致的扩展方式。"""
    _registry: dict[str, type[BaseLLM]] = {}

    @classmethod
    def register(cls, provider: str, llm_cls: type[BaseLLM]) -> None:
        cls._registry[provider] = llm_cls

    @classmethod
    def create(cls, provider: str, model_name: str, api_base: str | None,
               api_key: str | None, **kwargs) -> BaseLLM: ...
```

### provider 实现

```python
# agent_service/llm/providers/openai_provider.py
class OpenAIProvider(BaseLLM):
    """OpenAI / 兼容接口（DeepSeek / Qwen / Moonshot 等均兼容 OpenAI 协议）。
    通过 api_base 切换不同服务商。"""

# agent_service/llm/providers/deepseek_provider.py
class DeepSeekProvider(OpenAIProvider):
    """DeepSeek-V3 / DeepSeek-R1，法律推理能力强，成本可控。"""

# agent_service/llm/providers/qwen_provider.py
class QwenProvider(OpenAIProvider):
    """通义千问 Qwen-Max / Qwen-Plus，中文法律场景效果优秀。"""
```

要求：
- 统一用 `openai` SDK（异步 `AsyncOpenAI`），通过 `base_url` 切换 provider，避免引入多套 SDK
- `stream()` 返回 `AsyncIterator[str]`，内部把 OpenAI 的 chunk 转为纯文本增量
- `chat_with_tools()` 返回标准化结构，Agent 不感知具体 provider 的 tool_call 格式
- 失败重试 3 次，指数退避 1s/2s/4s；流式阶段重试只重发未消费部分（记录已 yield 的字符数）
- **温度分场景**：意图识别/要素抽取 `temperature=0.1`，最终回答 `temperature=0.3`，合同审查 `temperature=0.1`（要稳）

### 默认 provider 注册

```python
LLMFactory.register("openai", OpenAIProvider)
LLMFactory.register("deepseek", DeepSeekProvider)
LLMFactory.register("qwen", QwenProvider)
# 后续新增 Claude / Moonshot / GLM 只需一行 register
```

### BYOK 按用户加载（与 Router 共用）

> **关键**：Router 的 `route(router_input, llm=user_llm)` 和业务 Agent 的 LLM 都走同一套 BYOK。`agent_service/llm/byok.py` 的 `load_user_llm(user_id)` 从 `user_llm_config` 表读取该用户的 provider / model / api_base / 加密 api_key / temperature / max_tokens / timeout / retry，解密后调用 `LLMFactory.create()` 产出 `BaseLLM` 实例。可选字段为 NULL 时回退到 `.env` 全局默认值（避免 TypeError）。用户未配置且 `byok_fallback_to_global=True` 时返回全局兜底 LLM。

```python
# agent_service/llm/byok.py（待开发）
async def load_user_llm(user_id: str) -> BaseLLM:
    """按 user_id 从 user_llm_config 加载并解密，产出 BaseLLM 实例。
    - 记录不存在且 fallback 开启 → 返回全局兜底 LLM
    - 可选字段为 NULL → 回退到 settings 全局默认值
    - api_key 加密存储，加载时用 settings.byok_api_key_secret 解密
    """
```

> Router 不在构造时绑定 LLM，而是在 `route()` 调用时由 SSE 入口注入 `llm=user_llm`（见关键设计八的 SSE 调用示例）。业务 Agent 的 `AgentManager.get_agent(agent_key, llm=user_llm)` 同样运行时注入，节点内部使用传入的 llm 实例。

---

## 关键设计二：LangGraph 状态图与节点

### 状态定义

> **初始状态由 Router 产出**：`agent_service/router/state_mapper.py` 的 `build_initial_state(decision, router_input)` 把 `RouterDecision` 字段映射为 `LegalAgentState` 的初始字段（见关键设计八的对接契约）。LangGraph 节点在执行过程中继续扩展检索、引用、工具调用、输出等运行期字段。

```python
# agent_service/agents/state.py
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages

class LegalAgentState(TypedDict):
    # ===== 输入（来自请求，由 build_initial_state 注入）=====
    query: str                              # 用户原始问题 ← RouterInput.user_query
    conversation_id: str                    # 会话 ID ← RouterInput.conversation_id
    user_id: str                            # 用户 ID ← RouterInput.user_id
    tenant_id: str                          # 租户 ID ← RouterInput.tenant_id
    kb_ids: list[dict]                      # 可用知识库列表（dict 列表，Router 不绑定具体库，
                                            #   由 Retriever 按 retrieval_scope 过滤）← RouterInput.available_kbs

    # ===== Router 注入（来自 RouterDecision，详见关键设计八）=====
    intent: str                             # task_type（legal_question / article_lookup / ...）
                                            # ← RouterDecision.task_type
    legal_domain: str                       # 法律领域 ← RouterDecision.retrieval_scope.category
    retrieval_scope: dict                   # {domain, category, keywords} ← RouterDecision.retrieval_scope
                                            #   传给 Retrieve 节点构造 filter_expr
    sub_questions: list[str]                # 子问题分解（多路检索用）← RouterDecision.sub_questions
    legal_context: dict                     # {law_name, article_no, cause_of_action}
                                            # ← RouterDecision.legal_context
    time_context: dict                      # {type: latest/current/historical, year}
                                            # ← RouterDecision.time_context，传给 HybridRetriever
    execution_mode: str                     # rag / multi_step / document_analysis
                                            # ← RouterDecision.execution_mode
    risk_level: str                         # low / medium / high ← RouterDecision.risk_level
    needs_human_review: bool                # 是否需人工审核 ← RouterDecision.needs_human_review
                                            #   Router 已按 risk_level=high 强制置 True

    # ===== 检索（节点产出，复用阶段三 RetrievalResult）=====
    rewritten_query: str                     # Query Rewrite 输出（HybridRetriever 内部已做）
    retrieved_chunks: list[dict]            # Rerank 后的 Top-K
    retrieval_quality: str                  # sufficient / insufficient
    context_text: str                       # ContextBuilder 输出（带编号的引用文本）

    # ===== 对话历史与记忆 =====
    messages: Annotated[list, add_messages] # LangGraph 消息累加器（初始为 []，由 Memory 节点从 Redis 加载）
    legal_memory: LegalMemory | None        # 结构化法律记忆 ← RouterInput.legal_memory
                                            # {current_case, current_law, citation_history, user_role}
                                            # 由 Memory 节点从 Redis 注入（详见关键设计四）

    # ===== 引用（扩展网络来源）=====
    citations: list[dict]                   # 法条引用 + 网络来源引用
    citation_validation: dict               # {passed: bool, failed_ids: list, reasons: list}

    # ===== 工具调用 =====
    tool_calls: list[dict]                  # 已执行的工具调用记录

    # ===== 输出 =====
    answer: str                            # 最终回答（流式产出）
    risk_alerts: list[dict]                # 风险提醒
    trace_id: str                           # 关联 rag_trace
```

> **注意**：`LegalAgentState` 在 `agent_service/router/state_mapper.py` 中以 `TypedDict(total=False)` 声明，只覆盖 Router 注入的初始字段（上述"输入"与"Router 注入"两组）。`agent_service/agents/state.py` 在此基础上补齐检索/引用/工具/输出等运行期字段，供 LangGraph 节点读写。两者字段名必须保持一致，避免对接错位。

### 通用基础状态图（所有 Agent 共享骨架，节点可覆写）

> **注意**：下图是**业务 Agent 的内部状态图**（Intent→Retrieve→...→Validate），不含 Router。
> Router Agent 是编排层，在 LangGraph 之外（详见关键设计八），由 AgentManager 在 Router 之后调度到本图。

```text
                    START
                      ↓
              ┌─── Intent ────┐
              │ (意图+领域分类) │  ← LLM 节点（temperature=0.1）
              └──────┬─────────┘
                     ↓
              ┌── Retrieve ───┐
              │ (调用阶段三    │  ← 调用 HybridRetriever.retrieve()
              │  HybridRetriever)│    不重写检索逻辑
              └──────┬─────────┘
                     ↓
              ┌─ Retrieve Judge ┐ ← 条件边
              │ (检索质量判断)   │  (insufficient → 补充检索，最多 1 次)
              └──────┬──────────┘
                     ↓ (sufficient)
              ┌── Tool Decide ─┐  ← LLM 判断是否需要工具（如联网搜索/合同审查）
              │ (是否调用工具)   │
              └──────┬──────────┘
                     ↓ (需要)
              ┌── Tool Exec ───┐  ← 执行内部 Python 工具（ToolRegistry 分发）
              │ (工具调用)      │
              └──────┬──────────┘
                     ↓
              ┌── Reason ──────┐  ← LLM 基于 context_text + memory 推理
              │ (推理+生成)    │    流式产出 answer
              └──────┬──────────┘
                     ↓
              ┌── Citation ───┐  ← 复用阶段三 CitationBuilder + 网络来源扩展
              │ (引用构建)      │
              └──────┬──────────┘
                     ↓
              ┌─ Validate ─────┐ ← 条件边
              │ (引用校验防幻觉) │  (引用失败 → 重新生成，最多 1 次)
              └──────┬──────────┘
                     ↓ (通过)
                    END
```

### 节点实现规范

```python
# agent_service/agents/base.py
class BaseAgent:
    """所有 Agent 的基类。提供通用状态图构建骨架，子类覆写差异化节点。

    设计原则：
    - 共享节点（Intent/Retrieve/Reason/Citation/Validate）在基类实现
    - 差异化节点（如合同审查的 Parse/Classify/RiskEngine）在子类覆写
    - 子类通过覆写 build_graph() 增删节点和边，不改基类
    - 所有节点是 async 函数，接收 state 返回 state 增量
    """

    def __init__(self, llm: BaseLLM, retriever: HybridRetriever,
                 context_builder: ContextBuilder, tool_registry: ToolRegistry,
                 memory: BaseMemory, citation_validator: CitationValidator):
        ...

    def build_graph(self) -> CompiledGraph:
        """构建 LangGraph 状态图。子类可覆写以增删节点。"""
        graph = StateGraph(LegalAgentState)
        graph.add_node("intent", self.intent_node)
        graph.add_node("retrieve", self.retrieve_node)
        graph.add_node("retrieve_judge", self.retrieve_judge_node)
        graph.add_node("tool_decide", self.tool_decide_node)
        graph.add_node("tool_exec", self.tool_exec_node)
        graph.add_node("reason", self.reason_node)
        graph.add_node("citation", self.citation_node)
        graph.add_node("validate", self.validate_node)

        graph.add_edge(START, "intent")
        graph.add_edge("intent", "retrieve")
        graph.add_edge("retrieve", "retrieve_judge")
        graph.add_conditional_edges("retrieve_judge", self._retrieve_quality_router,
                                    {"retry": "retrieve", "proceed": "tool_decide"})
        graph.add_edge("tool_decide", "tool_exec")
        graph.add_edge("tool_exec", "reason")
        graph.add_edge("reason", "citation")
        graph.add_edge("citation", "validate")
        graph.add_conditional_edges("validate", self._validation_router,
                                    {"retry": "reason", "end": END})
        return graph.compile()

    async def intent_node(self, state: LegalAgentState) -> dict:
        """意图识别 + 领域分类 + 子问题分解。LLM 短输出场景。"""

    async def retrieve_node(self, state: LegalAgentState) -> dict:
        """调用阶段三 HybridRetriever.retrieve()。
        - kb_ids 从会话绑定获取
        - top_k / rerank_top_k 按 intent 调整
        - 返回 retrieved_chunks + context_text + citations + trace_id
        不重写检索逻辑，只做调用编排。"""

    async def reason_node(self, state: LegalAgentState) -> dict:
        """LLM 推理。基于 context_text（带 [1][2] 编号）+ legal_memory。
        流式产出 answer。System Prompt 由具体 Agent 定义。"""

    async def validate_node(self, state: LegalAgentState) -> dict:
        """引用校验。检查 LLM 回答中出现的 [n] 编号是否都在 citations 中，
        法条引用是否真实存在（回查 MySQL knowledge_chunk）。"""
```

### 条件边防死循环

- Retrieve Judge 重试上限 1 次：`retry_count` 字段，超过则强制 proceed
- Validate 重试上限 1 次：引用校验失败时，把失败原因塞回 state 让 LLM 重新生成，超过则保留并标记 `needs_human_review=True`

---

## 关键设计三：工具系统（内部 Python 函数 + 注册表 + 预留 MCP）

### 设计原则

```text
不写 if tool_name == "web_search": ... elif tool_name == "query_law": ...
而是 ToolRegistry 注册表分发，新增工具只需 register。
```

```python
# agent_service/tools/base.py
from abc import ABC, abstractmethod

class BaseTool(ABC):
    """工具抽象基类。每个工具是同进程的 async Python 函数。

    接口设计预留 MCP 协议化：
    - name / description / parameters_schema 与 MCP Tool 规范一致
    - 未来迁移 MCP 时，只需把 BaseTool.execute 改为 HTTP/MCP 调用，
      Agent 侧代码不变（依赖 BaseTool 接口，不感知实现）
    """

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def parameters_schema(self) -> dict:
        """JSON Schema，用于 LLM function calling"""

    @abstractmethod
    async def execute(self, **kwargs) -> dict:
        """执行工具，返回结构化结果。失败返回 {"error": "..."}，不抛异常。"""

class ToolRegistry:
    """工具注册表。Agent 通过 name 查找并执行。"""
    _registry: dict[str, BaseTool] = {}

    @classmethod
    def register(cls, tool: BaseTool) -> None:
        cls._registry[tool.name] = tool

    @classmethod
    def get(cls, name: str) -> BaseTool | None:
        return cls._registry.get(name)

    @classmethod
    def list_for_agent(cls, agent_type: str) -> list[BaseTool]:
        """按 Agent 类型返回可用工具子集（权限控制）"""
```

### 内置工具清单

```python
# 1. 法条查询工具（复用阶段三 HybridRetriever）
class LawQueryTool(BaseTool):
    """按法律名称/条号/关键词查询法条原文。
    内部调用 HybridRetriever.retrieve(intent="article_lookup")，
    返回 [{law_name, article_no, text, hierarchy_path, version}]"""

# 2. 法条版本查询工具
class LawVersionTool(BaseTool):
    """检查法条版本：生效日期、修订历史、废止状态、是否最新。
    查询 knowledge_document 的 version/effective_date/is_latest/superseded_by_document_id"""

# 3. 联网搜索工具（Tavily，案例分析专用）
class WebSearchTool(BaseTool):
    """Tavily 联网搜索。返回 [{url, title, content_snippet, published_date}]。
    结果纳入引用体系（网络来源类别）。"""

# 4. 合同条款审查工具
class ContractReviewTool(BaseTool):
    """审查单个合同条款。输入条款文本+类型，返回风险评估+法律依据。
    内部调用规则引擎 + LLM 深度审查 + 法条检索。"""

# 5. 文书生成工具（阶段四预留接口，阶段五实现）
class DocGenerateTool(BaseTool):
    """生成法律文书草稿（律师函/法律意见书）。阶段四仅预留。"""
```

### 工具与 Agent 的绑定

```python
# 每个 Agent 声明可用工具白名单
AGENT_TOOLS = {
    "law_qa": ["query_law", "check_law_version"],
    "article_locate": ["query_law", "check_law_version"],
    "contract_review": ["query_law", "check_law_version", "review_contract_clause"],
    "case_analysis": ["web_search", "query_law"],
}
```

### Tavily 联网搜索工具详细设计

```python
# agent_service/tools/web_search_tool.py
class WebSearchTool(BaseTool):
    name = "web_search"
    description = "联网搜索类似案例、法律资讯、裁判文书公开信息"
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "search_depth": {"type": "string", "enum": ["basic", "advanced"],
                              "default": "advanced", "description": "advanced 返回更详细内容"},
            "max_results": {"type": "integer", "default": 5, "minimum": 1, "maximum": 10},
            "include_answer": {"type": "boolean", "default": True}
        },
        "required": ["query"]
    }

    async def execute(self, query: str, search_depth: str = "advanced",
                      max_results: int = 5, include_answer: bool = True) -> dict:
        """调用 Tavily API。
        返回: {
            "results": [
                {"url": "...", "title": "...", "content": "原文片段",
                 "published_date": "2024-01-01", "score": 0.95}
            ],
            "answer": "Tavily 生成的摘要答案"
        }
        结果会由 Citation 节点转换为网络来源引用。"""
```

要求：
- Tavily API Key 通过 `settings.tavily_api_key` 注入
- 单次搜索默认 5 条，最多 10 条（控制 token 消耗）
- 搜索失败返回 `{"error": "..."}`，不阻塞 Agent（Agent 降级为无网络来源回答）
- `published_date` 字段用于引用时效性标注

---

## 关键设计四：Memory 法律上下文记忆

### 分层存储

```text
短期记忆（活跃会话）    → Redis  key: lawrag:memory:{conversation_id}
                         TTL: 24h（会话闲置 24h 后清理）
                         存: 最近 N 轮 messages + legal_memory 压缩态

长期记忆（历史持久化）  → MySQL conversation / message 表
                         存: 完整对话历史 + 每轮 citations
                         会话列表、检索、导出均读 MySQL
```

### 法律特化记忆结构（结构化版本）

```python
# agent_service/memory/legal_memory.py
class LegalMemory:
    """法律对话上下文记忆。结构化为 current_case / current_law 两块，
    方便 Router Agent 和业务 Agent 共享上下文。"""

    # 当前讨论的案例/纠纷上下文（案情相关）
    current_case: dict | None       # {
                                    #   "domain": "租赁纠纷",
                                    #   "party_role": "出租人",          # 出租人/承租人/买方/卖方/原告/被告
                                    #   "facts": ["租客欠租", "合同已签"],
                                    #   "dispute_focus": "能否直接换锁"   # 争议焦点
                                    # }

    # 当前讨论的法律上下文（法条相关）
    current_law: dict | None        # {
                                    #   "laws": ["民法典"],              # 对话中提到的法律
                                    #   "articles": ["第712条"],         # 当前引用的法条
                                    #   "topic": "出租人维修义务"         # 当前讨论主题
                                    # }

    # 历史引用追踪（保证跨轮次引用一致性）
    citation_history: list[dict]    # [{"turn":1,"citations":["民法典第712条"]}, ...]

    # 用户角色与偏好
    user_role: str | None           # 律师 / 当事人 / 法务 / 公众
```

> **设计原则**：`current_case` 和 `current_law` 分离，因为有些轮次只讨论法条不涉及案情（如"民法典第585条是什么"），有些轮次只讨论案情不引用法条（如"那我可以直接换锁吗"）。Router Agent 据此判断是延续 law_qa 还是 case_analysis。

### 跨轮次引用一致性示例

```text
第1轮: 用户"租房漏水房东不修"
  → Agent 引用民法典第712条
  Memory 更新:
    current_case = {"domain":"租赁纠纷","party_role":"承租人","facts":["漏水","房东不修"]}
    current_law  = {"laws":["民法典"],"articles":["第712条"],"topic":"出租人维修义务"}

第2轮: 用户"那如果我要自己修呢"（口语化，省略主语背景）
  Router 注入 current_case + current_law → 判定延续 law_qa
  → Agent 关联第712条→第713条
  Memory 更新:
    current_law.articles = ["第713条"]
    current_case.facts.append("用户想自行维修")

第3轮: 用户"我修了花了5000块，怎么要回来？"
  Router 仍延续 law_qa（current_case 仍是租赁纠纷）
  → Agent 引用第713条 + 补充费用追偿程序
  Memory 更新:
    current_case.facts.append("已维修","花费5000元")
```

### 记忆压缩策略

长对话（超过 `max_memory_turns`，默认 6 轮）触发压缩：

```text
原始: [msg1, msg2, ..., msg20]  ← 可能超 LLM 上下文窗口
压缩后: summary="用户为房屋承租人，漏水问题。第1轮确认出租人维修义务(712条)；
                第2轮讨论自行维修费用追偿(713条)；当前问题:诉讼流程。"
        key_facts={"role":"承租人","contract_type":"房屋租赁",
                   "issue":"漏水+维修","repair_cost":5000}
```

> **压缩用 LLM 完成**（与阶段三 ParentChunkBuilder 用规则模板不同 —— Agent 阶段已引入 LLM，压缩是 LLM 的合理职责）。

### Memory 注入与更新时机

```text
Agent 启动节点:
  1. 从 Redis 读取 legal_memory + 最近 N 轮 messages
  2. 注入 state.legal_memory 和 state.messages

Agent 结束节点:
  1. 更新 legal_memory（current_law/article 等由 LLM 从本轮回答提取）
  2. 写回 Redis（短期）+ MySQL message 表（长期）
  3. 触发压缩检查（轮次超阈值则压缩）
```

---

## 关键设计五：Citation 体系扩展 + Validator 防幻觉

### 引用类型扩展

阶段三 CitationBuilder 只产法条引用（来源 `knowledge_chunk`）。阶段四扩展两类：

```python
# 引用来源类型
CitationSource = Literal["law", "judicial", "case", "web"]

# 法条/司法解释引用（复用阶段三 CitationBuilder）
{
    "source_type": "law",
    "chunk_id": "LAW_000000246",
    "law_name": "中华人民共和国民法典",
    "article_no": "第二百四十六条",
    "hierarchy_path": "第二编 物权 > 第五章 > ...",
    "text": "矿藏、水流、海域属于国家所有……",
    "version": "2025",
    "effective_date": 1609430400,
    "is_latest": True,
    "page_start": 32, "page_end": 32,
    "source_uri": "documents/civil_code/civil_code_2025.pdf"
}

# 网络来源引用（阶段四新增，来自 Tavily）
{
    "source_type": "web",
    "url": "https://wenshu.court.gov.cn/...",
    "title": "（2023）闽01民终3456号 民事判决书",
    "content_snippet": "法院认为，买受人怠于通知...",
    "published_date": "2023-06-15",
    "retrieved_at": 1785637932,      # 检索时间戳
    "search_query": "买卖合同 质量异议 付款义务"  # 触发该结果的搜索词
}
```

### Citation Validator（防幻觉核心）

```python
# agent_service/citation/validator.py
class CitationValidator:
    """引用校验器。法律场景防幻觉的关键防线。

    校验项：
    1. 编号一致性: LLM 回答中出现的 [n] 编号必须都在 citations 列表中
    2. 法条真实性: 回答中提到的法条（如"民法典第585条"）必须能在 citations 找到对应项
    3. 法条原文匹配: 引用的法条 text 必须与 MySQL knowledge_chunk.text 一致
    4. 杜撰检测: LLM 若引用了未在 context_text 中出现的法条 → 标记为幻觉
    """

    async def validate(self, answer: str, citations: list[dict],
                       context_text: str, db: AsyncSession) -> dict:
        """返回:
        {
            "passed": bool,
            "failed_ids": [1, 3],          # 校验失败的引用编号
            "reasons": [{"id":1,"reason":"法条编号不在citations中"}],
            "hallucinated_laws": ["民法典第999条"]  # 杜撰的法条
        }
        """

    async def _check_law_exists(self, law_name: str, article_no: str,
                                 db: AsyncSession) -> bool:
        """回查 MySQL knowledge_chunk 验证法条真实存在"""
```

### 校验失败处理

```text
Validate 节点条件边:
  passed=True → END
  passed=False:
    retry_count < 1 → 回到 Reason 节点，把失败原因塞入 state 让 LLM 重新生成
    retry_count >= 1 → 标记 needs_human_review=True，保留回答但前端展示"引用校验未通过"提示
```

---

## 关键设计六：SSE 流式输出

### 流式架构

```text
前端 POST /api/agent/chat (SSE)
  ↓
AgentRouter 接收请求
  ↓
调用 agent.astream(initial_state)  ← LangGraph 异步流式
  ↓
LangGraph 节点事件流转
  ├── 节点开始/结束事件 → SSE: {"event":"node","node":"reason","status":"start"}
  ├── Reason 节点 LLM 流式 token → SSE: {"event":"token","content":"根据"}
  ├── 工具调用事件 → SSE: {"event":"tool","name":"web_search","status":"start"}
  └── 完成事件 → SSE: {"event":"done","citations":[...],"trace_id":"..."}
  ↓
前端按事件类型渲染（token 流式拼接，citations 完成后展示引用卡片）
```

### SSE 事件协议

```python
# 统一的事件类型
SSEEvent = {
    "node_start":   {"event":"node_start","node":"reason","timestamp":...},
    "node_end":     {"event":"node_end","node":"reason","duration_ms":...,"output_keys":[...]},
    "token":        {"event":"token","content":"增量文本"},
    "tool_start":   {"event":"tool_start","name":"web_search","args":{...}},
    "tool_end":     {"event":"tool_end","name":"web_search","result_summary":"找到5条"},
    "citation":     {"event":"citation","citations":[...]},   # 引用列表（完成时一次性发）
    "risk_alert":   {"event":"risk_alert","alerts":[...]},
    "done":         {"event":"done","message_id":...,"trace_id":...,"needs_human_review":false},
    "error":        {"event":"error","code":"...","message":"..."}
}
```

要求：
- Reason 节点的 LLM `stream()` 产出 token → 立即 yield 为 SSE `token` 事件
- 工具调用前/后发 `tool_start`/`tool_end`，让前端展示"正在搜索..."
- 引用列表在 `done` 前发一次 `citation` 事件
- 错误不中断流，发 `error` 事件后正常关闭 SSE

---

## 各 Agent 详细设计

### 1. 法律咨询 Agent (law_qa)

**场景**：日常法律问题问答，返回法规依据 + 分析过程 + 风险提示 + 引用。

```text
节点: Intent → Retrieve → RetrieveJudge → Reason → Citation → Validate
覆写: 无工具调用（tool_decide 直接 proceed）
检索: intent=law_qa, kb_ids=会话绑定的法律库, top_k=8
```

**System Prompt 要点**：
- 角色：资深法律顾问
- 必须基于 context_text 中的法条回答，引用用 `[n]` 编号
- 输出结构：问题归类 / 法律依据 / 分析过程 / 风险提示 / 引用来源 / 免责声明
- 禁止凭记忆复述法条原文，法条必须来自引用

**输出规范**（必须覆盖）：
```text
✅ 问题归类      — 法律领域
✅ 法律依据      — 具体法条（引用编号 [n]）
✅ 分析过程      — 法律到事实的推理
✅ 风险提示      — 例外、限制、实务风险
✅ 引用来源      — 可追溯法条
⚠ 免责声明      — "本分析仅供参考，不构成法律意见"
```

### 2. 法条定位 Agent (article_locate)

**场景**：精确法条定位（"民法典关于违约金的条款在哪"），轻量级，侧重精准。

```text
节点: Intent → Retrieve(BM25优先) → ArticleTreeContext → Response → Citation
覆写:
  - retrieve_node: intent=article_lookup, chunk_level 限定 article, BM25 权重提高
  - 新增 article_tree_node: 通过 parent_chunk_id 向上展开层级树
  - 跳过 Reason 节点（不需要深度推理，直接返回法条 + 上下文）
检索: top_k=3（精准而非全面）
```

**Article Tree Context 节点**：
```python
async def article_tree_node(self, state):
    """展开法条在整部法律中的位置。
    1. 取命中法条的 parent_chunk_id（section 级）
    2. SELECT * WHERE parent_chunk_id = section → 同节其他法条
    3. 向上取 chapter 级，展示同级章节
    4. 构建层级树文本供前端展示"""
```

### 3. 合同审查 Agent (contract_review) — 最复杂

**场景**：上传合同 → OCR 解析 → 条款分类 → 风险识别（规则+LLM）→ 法条检索 → 报告。

#### 3.1 OCR 与合同解析依赖（前置）

```text
合同上传（多为扫描件/图片）
  ↓
合同 OCR 解析（复用 backend/services/parser.py）
  ├── MinerU 优先（mineru_method 需支持 OCR 模式，如 "ocr" / "auto"）
  └── PaddleOCR 兜底（MinerU 不可用时，新增独立 OCR 模块）
  ↓
合同条款结构化切分（阶段四新增 contract_clause_parser）
  ├── 按"第X条" / 条款标题切分
  ├── 提取: 当事人、标的、价款、违约责任、管辖等
  └── 输出 clauses: [{id, title, text, clause_type}]
```

**OCR 依赖说明**：
- 当前 `backend/services/parser.py` 已集成 MinerU，但 `mineru_method` 需配置为 OCR 模式才能处理扫描件
- 若 MinerU 不可用（`mineru_enabled=False` 或 CLI 缺失），降级 pdfplumber **无法处理扫描件**（只能处理文本 PDF）
- **阶段四新增 `backend/services/ocr.py`**：PaddleOCR 封装，作为扫描件 OCR 兜底
- 合同解析是同步前置步骤，不放入 LangGraph 节点（上传时异步触发，审查时读取已解析结果）

#### 3.2 状态图（覆写基类）

```text
START
  ↓
ContractParse（读取已解析的条款，非节点内 OCR）
  ↓
ClauseClassifier（自动分类条款类型 + 缺失检测）
  ↓
RiskRuleEngine（Layer1: 规则引擎秒级判断）
  ↓
LLMDeepReview（Layer2: LLM 语义深度审查，逐条款）
  ↓
LegalRetrieval（为每个风险条款检索法律依据，调用 HybridRetriever）
  ↓
GenerateReport（生成审查报告）
  ↓
Citation + Validate
  ↓
END
```

#### 3.3 规则引擎（Layer1）

```python
# agent_service/agents/contract_review.py
CONTRACT_RISK_RULES = [
    {
        "rule_id": "CR-001",
        "clause_type": "liability",
        "pattern": r"日千分之|日千分之[一二三四五六七八九]",
        "risk_level": "high",
        "description": "违约金/滞纳金过高（年化超 LPR 4 倍）",
        "legal_basis": "民法典第585条",
        "suggestion": "修改为按 LPR 4 倍计算"
    },
    {
        "rule_id": "CR-004",
        "clause_type": "dispute",
        "pattern": r"(甲方|乙方)所在地.{0,10}管辖",
        "risk_level": "medium",
        "description": "单方管辖约定，对另一方不利",
        "legal_basis": "民事诉讼法第24条、第35条",
        "suggestion": "修改为被告所在地或合同签订地"
    },
    # ... 更多规则
]
```

#### 3.4 报告输出规范

```text
合同审查报告
📊 总体风险等级: 🔴 高风险
📋 风险统计: 高风险 N 项 / 中风险 N 项 / 低风险 N 项 / 缺失条款 N 项

🔴 风险详情（每项）:
  - 原文引用
  - 风险等级和类型
  - 法律依据（引用编号 [n]）
  - 修改建议（原文 → 建议文本）
  - 修改理由
⚠ 缺失条款提醒
✅ 合规检查清单
```

### 4. 案例分析 Agent (case_analysis) — Tavily 联网版

**场景**：用户描述案情 → 联网搜索类似案例 → 提取裁判观点 → 综合分析。

> **关键差异**：与 05 文档不同，**不走本地案例库检索**，改用 Tavily 联网搜索。本地案例库未建，联网覆盖更广。

```text
START
  ↓
CaseFeatureExtract（LLM 提取案例特征: 案由/事实要素/争议焦点）
  ↓
ToolDecide → 调用 WebSearchTool（Tavily）
  ↓
WebSearch（多组关键词搜索，如"买卖合同 质量异议 付款义务 判决"）
  ↓
CaseContentExtract（从搜索结果提取裁判要点）
  ↓
LegalRetrieval（为争议焦点检索适用法条，本地知识库）
  ↓
LLMSynthesis（综合分析: 相似案例摘要 + 裁判趋势 + 风险提示）
  ↓
Citation（法条引用 + 网络来源引用）
  ↓
Validate
  ↓
END
```

**多组搜索策略**：
```python
async def web_search_node(self, state):
    """根据 case_features 生成多组搜索 query 并行调用 Tavily。
    - 优先消费 Router 注入的 sub_questions（如"裁判规则"、"类似案例"子问题）作为多路检索起点
    - 再结合 CaseFeatureExtract 提取的 case_features 扩展：
      query1: 案由 + 关键事实
      query2: 争议焦点 + 法条关键词
      query3: 案由 + 裁判观点
    并行调用，去重合并 Top-N 网络来源。"""
```

> **Router 对接**：Router 在路由到 case_analysis 时已产出 `sub_questions`（`task_type=case_search`、`execution_mode=multi_step`、`risk_level=medium`），CaseFeatureExtract 与 WebSearch 节点必须读取 `state.sub_questions`，不得忽略 Router 的子问题分解重新从零生成。

**输出规范**：
```text
一、相似案例（来自网络搜索）
二、裁判观点总结
三、对当前问题的参考
四、适用法律依据（本地法条，引用 [n]）
五、风险提示
📎 引用来源: [1][2] 法条 / [3][4] 网络案例（URL）
```

---

## 关键设计七：会话与多轮对话

### 数据模型扩展（新增表）

```sql
-- 会话表
CREATE TABLE conversation (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    conversation_id VARCHAR(64) NOT NULL UNIQUE,   -- UUID
    user_id     BIGINT NOT NULL,
    tenant_id   VARCHAR(50) NOT NULL,
    title       VARCHAR(200) DEFAULT '',           -- 自动生成（首轮问题摘要）
    agent_type  VARCHAR(30) NOT NULL,              -- law_qa / contract_review / ...
    kb_ids      JSON NOT NULL,                     -- 绑定的知识库
    status      VARCHAR(20) DEFAULT 'active',      -- active / archived
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_user_tenant (user_id, tenant_id),
    INDEX idx_updated (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 消息表
CREATE TABLE message (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    conversation_id VARCHAR(64) NOT NULL,
    role            VARCHAR(20) NOT NULL,           -- user / assistant / tool
    content         MEDIUMTEXT NOT NULL,            -- 消息内容
    citations       JSON DEFAULT NULL,              -- 引用列表（assistant 消息）
    tool_calls      JSON DEFAULT NULL,             -- 工具调用记录
    trace_id        VARCHAR(64) DEFAULT NULL,       -- 关联 rag_trace
    needs_human_review TINYINT(1) DEFAULT 0,
    risk_alerts     JSON DEFAULT NULL,
    tokens_used     INT DEFAULT 0,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_conversation (conversation_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Agent 配置表（阶段四先硬编码默认值，本表预留后台配置化）
CREATE TABLE agent_config (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    agent_type      VARCHAR(30) NOT NULL,
    tenant_id       VARCHAR(50) NOT NULL DEFAULT 'default',
    name            VARCHAR(100) NOT NULL,
    system_prompt   TEXT NOT NULL,
    model_provider  VARCHAR(30) NOT NULL,
    model_name      VARCHAR(50) NOT NULL,
    temperature     DECIMAL(3,2) DEFAULT 0.30,
    max_tokens      INT DEFAULT 4096,
    kb_ids          JSON DEFAULT NULL,
    tools           JSON DEFAULT NULL,             -- ["query_law","web_search"]
    memory_config   JSON DEFAULT NULL,
    citation_config JSON DEFAULT NULL,
    version         INT DEFAULT 1,
    publish_status  VARCHAR(20) DEFAULT 'draft',   -- draft / published
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_agent_tenant_version (agent_type, tenant_id, version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 迁移脚本

新增 `sql/migrations/002_phase4_agent.sql`，包含上述 3 张表。已有数据库单独执行。

---

## 关键设计八：Router 对接契约（Router Agent 已实现）

> **Router Agent 已开发完成并通过 13 个单元测试**，代码位于 [agent_service/router/](file:///g:/agent-project/LawRAG/agent_service/router)，详细设计见 [doc/17-Router Agent 设计方案.md](file:///g:/agent-project/LawRAG/doc/17-Router%20Agent%20设计方案.md)。本节不再描述 Router 的开发任务，只定义 **Router 与业务 Agent 的对接契约**，确保 Router 产出的 `RouterDecision` 能被 4 个业务 Agent（law_qa / article_locate / contract_review / case_analysis）正确消费。业务 Agent 开发时**直接复用** Router 已实现的能力，不要重复实现路由、规则、Prompt、兜底等逻辑。

### 已实现模块（不再开发，业务 Agent 直接复用）

```text
agent_service/router/
├── __init__.py        # 导出 RouterAgent / RouterDecision / RouterInput / LegalMemory / Candidate / LegalAgentState / build_initial_state
├── router.py          # RouterAgent 主类，route() 入口（记忆恢复 → 规则候选 → LLM 判别 → guardrails → 兜底 → trace）
├── models.py          # RouterInput / RouterDecision / Candidate / LegalMemory / RetrievalScope / LegalContext / TimeContext
├── rules.py           # 规则候选生成（产出 candidates 列表，不直接决策）
├── prompt.py          # LLM Prompt 模板 + 7 个 Few-Shot 示例
├── fallback.py        # apply_guardrails（confidence clamp 到 0.95）+ fallback_from_candidates
├── state_mapper.py    # LegalAgentState + build_initial_state（RouterDecision → Agent 初始 State）
├── dependencies.py    # get_router_agent / get_memory FastAPI 依赖注入
└── trace.py           # Router 可观测性记录
```

业务 Agent 侧只需要开发 `AgentManager`（按 `decision.agent` dispatch）和 4 个 LangGraph Agent，路由决策完全交给已实现的 `RouterAgent`。

### 系统位置（已落地）

```text
                  User Query
                      |
                      v
              +-----------------+
              |  RouterAgent    |   ← 已实现（agent_service/router/，非 LangGraph）
              +-----------------+
                      |
              RouterDecision(JSON)
                      |
              +-------+-------+
              |               |
        AgentManager        Memory 更新
              |
    +---------+---------+---------+
    |         |         |         |
 law_qa  article_locate contract_review case_analysis   ← 业务 Agent（LangGraph，待开发）
    |         |         |         |
    +---------+---------+---------+
              |
       HybridRetriever（阶段三）
              |
            LLM
```

**职责分离（已实现）**：
- Router Agent：决定**走哪个 Agent**，提取检索前置参数（不检索、不生成、不执行工具、不写库）
- QueryRouter（阶段三）：决定**检索器内部权重**（BM25/Milvus 配比，不感知 Agent 存在）
- 两者不冲突，Router 的 `task_type` 透传给 HybridRetriever，QueryRouter 据此选 RRF 权重

### RouterDecision 字段契约（以 agent_service/router/models.py 为准）

业务 Agent 必须按以下字段消费 Router 输出。字段定义已固化，不要在 Agent 侧重新定义或改名。

```python
# agent_service/router/models.py（已实现，业务 Agent 只读消费）
AgentType = Literal["law_qa", "article_locate", "contract_review", "case_analysis"]
TaskType = Literal["legal_question", "article_lookup", "contract_review",
                   "case_search", "document_generation"]
ExecutionMode = Literal["rag", "multi_step", "document_analysis"]
RiskLevel = Literal["low", "medium", "high"]

class RouterDecision(BaseModel):
    task_type: TaskType                 # 任务类型
    agent: AgentType                    # 执行 Agent（AgentManager 据此 dispatch）
    confidence: float                   # 0.0~1.0（apply_guardrails 已 clamp 到 0.95 上限）
    need_retrieval: bool = True         # 是否需要检索
    retrieval_scope: RetrievalScope     # {domain, category, keywords}，不绑定 kb_id
    need_file: bool = False             # 是否需要文件
    file_requirement: FileRequirement | None  # {type, hint}
    legal_context: LegalContext         # {law_name, article_no, cause_of_action}
    sub_questions: list[str]            # 子问题分解（law_qa / case_analysis 产出）
    time_context: TimeContext           # {type: latest/current/historical, year}
    execution_mode: ExecutionMode       # rag / multi_step / document_analysis
    risk_level: RiskLevel               # low / medium / high
    route_reason: str                   # 路由理由
    fallback: bool                      # 是否走了兜底
    needs_human_review: bool            # 是否需人工审核（risk_level=high 时 Router 强制 True）
```

> **关键**：`confidence` 字段在 `models.py` 中允许到 `1.0`，由 `fallback.apply_guardrails` 统一 clamp 到 `settings.router_confidence_max`（默认 0.95）。业务 Agent 不要再对 confidence 做二次裁剪。`needs_human_review` 是 Router 已计算好的字段，Agent 侧只读，不得清零。

### RouterInput 字段契约（业务侧只构造，不实现内部逻辑）

```python
# agent_service/router/models.py（已实现）
class RouterInput(BaseModel):
    user_query: str                            # 用户原始输入（不可空，已校验）
    conversation_id: str = ""                  # 会话 ID（非空时 Router 自动补齐 memory）
    user_id: str = ""
    tenant_id: str = ""
    history_summary: str | None = None         # 留空，Router 内部 _hydrate_context 自动加载
    legal_memory: LegalMemory | None = None    # 留空，Router 内部自动加载
    uploaded_files: list[dict] = []            # 留空，Router 内部自动加载
    available_kbs: list[dict] = []             # 留空时 Router 调 available_kbs_loader 按 tenant_id 加载
```

> **多轮命脉**：`history_summary` + `legal_memory` + `uploaded_files` 由 Router 内部 `_hydrate_context` 从 Memory 自动补齐，业务侧构造 `RouterInput` 时只需传 `user_query` / `conversation_id` / `user_id` / `tenant_id` / `available_kbs`，不要手动塞 memory（除非有特殊覆盖需求）。

### 字段与 4 个 Agent 的对应关系（Router 已实现的默认值）

| 字段 | law_qa | article_locate | contract_review | case_analysis |
|------|--------|----------------|------------------|---------------|
| `task_type` | legal_question | article_lookup | contract_review | case_search |
| `execution_mode` | rag | rag | document_analysis | multi_step |
| `need_retrieval` | True | True | True（按风险条款检索法条） | True + 联网搜索 |
| `retrieval_scope.domain` | 按领域 | 按法律 | civil | 按案由 |
| `need_file` | False | False | True（需合同文件） | False |
| `sub_questions` | 产出 | 不产出 | 不产出 | 产出 |
| `risk_level` | low/medium | low | medium | medium |

> Router 规则（`rules.py`）已覆盖：法条编号+法律名、法律名+主题查询（"规定/条款/内容/关于/适用"）、已上传合同、审查关键词（"审查/风险/条款问题/看看合同/合同有没有问题/合同问题"）、案例关键词（"类似案例/判例/怎么判/判决书/裁判规则/实际案件"）、文书生成降级到 law_qa、多轮延续候选。业务 Agent **不要在内部再做意图判定**，统一信任 Router 的 `agent` 字段。

### RouterDecision → LegalAgentState 注入映射（已实现，直接调用）

`agent_service/router/state_mapper.py` 的 `build_initial_state()` 已实现映射，业务 Agent 直接调用，不要重写。

```python
# agent_service/router/state_mapper.py（已实现）
def build_initial_state(decision: RouterDecision, router_input: RouterInput) -> LegalAgentState:
    """Router 输出 → Agent 初始 State 映射。"""
    return LegalAgentState(
        query=router_input.user_query,
        conversation_id=router_input.conversation_id,
        user_id=router_input.user_id,
        tenant_id=router_input.tenant_id,
        kb_ids=router_input.available_kbs,             # dict 列表，Router 不绑定具体库
        intent=decision.task_type,                     # task_type → state.intent
        legal_domain=decision.retrieval_scope.category,
        retrieval_scope=decision.retrieval_scope.model_dump(mode="json"),
        sub_questions=decision.sub_questions,
        time_context=decision.time_context.model_dump(mode="json"),
        legal_context=decision.legal_context.model_dump(mode="json"),
        execution_mode=decision.execution_mode,
        risk_level=decision.risk_level,
        needs_human_review=decision.needs_human_review,
        legal_memory=router_input.legal_memory,
        messages=[],                                    # 由 Memory 节点从 Redis 加载
        trace_id="",
    )
```

### 业务 Agent 必须遵守的对接契约

为确保 Router 能正常进入指定 Agent，业务 Agent 开发时**必须**遵守以下契约：

1. **AgentManager 按 `decision.agent` dispatch**：`AgentManager.get_agent(decision.agent)` 必须返回 4 个 Agent 之一。agent 字段值（`law_qa` / `article_locate` / `contract_review` / `case_analysis`）与 Agent 类的注册 key **严格一致**，不要改名、不要加前缀。

2. **初始 State 来自 `build_initial_state`**：业务 Agent 入口接收的 state 必须由 `build_initial_state(decision, router_input)` 产出，不要自行构造，避免字段缺失或命名错位（`retrieval_scope` / `needs_human_review` 等字段必须由 Router 映射注入）。

3. **节点消费字段契约**（每个节点必须读取的 RouterDecision 映射字段）：

| 节点 | 必读字段 | 用途 |
|------|---------|------|
| `Intent 节点` | `intent`（=task_type） | Router 已识别任务类型，Intent 节点只做领域细化，**不推翻 task_type** |
| `Retrieve 节点` | `retrieval_scope` / `time_context` / `sub_questions` / `legal_context` | 构造 filter_expr、控制 is_latest 过滤、多路检索、法条范围约束 |
| `Tool Decide 节点` | `execution_mode` | multi_step / document_analysis → 大概率需要工具 |
| `Validate 节点` | `risk_level` / `needs_human_review` | risk_level=high 时强制 needs_human_review=True（Router 已置位，Agent 不得清零） |
| `Reason 节点` | `legal_context` | law_name/article_no 作为推理约束，避免 LLM 跑偏到其他法律 |

4. **不要在 Agent 内部重新做路由判定**：Router 已决定 agent，业务 Agent 不要再根据 query 关键词切换到其他 Agent。如确需切换（如合同审查中发现非合同文件），通过抛异常或返回 `needs_human_review` 处理，不要静默改路由。

5. **LLM 运行时注入（BYOK）**：`RouterAgent.route(router_input, llm=user_llm)` 的 `llm` 参数支持运行时注入。业务 Agent 的 LLM 也必须按同一套 BYOK 机制（从 `user_llm_config` 表按 `user_id` 动态加载、API Key 加密存储）注入，**不要使用 `.env` 全局单例**。LLM 抽象层见关键设计一，BYOK 配置见「配置项」小节。

6. **Router 不感知 Agent 内部**：Router 只输出 `RouterDecision`，不调用 HybridRetriever、不调用工具、不写库。业务 Agent **不要反向依赖 Router 的内部规则/Prompt/候选列表**，只依赖 `RouterDecision` 这一稳定输出。

### Router 调用示例（SSE 入口参考，业务 Agent 侧不复用 Router 内部逻辑）

```python
# agent_service/routers/agent.py（SSE 入口，待开发）
from agent_service.router import RouterAgent, RouterInput, build_initial_state
from agent_service.router.dependencies import get_router_agent, get_memory

@router.post("/chat")
async def chat(body: AgentChatRequest,
              current_user = Depends(get_current_user),
              router_agent: RouterAgent = Depends(get_router_agent),   # 复用已实现
              agent_manager = Depends(get_agent_manager),
              memory = Depends(get_memory),
              user_llm = Depends(get_user_llm)):                        # BYOK：按 user_id 从 user_llm_config 加载
    # 1. 构造 RouterInput（memory/history/files 由 Router 内部 _hydrate_context 补齐）
    router_input = RouterInput(
        user_query=body.query,
        conversation_id=body.conversation_id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        available_kbs=body.kb_ids or [],
    )
    # 2. Router 决策（llm 运行时注入，route() 内部已完成记忆恢复/规则候选/LLM判别/guardrails/兜底/trace）
    decision = await router_agent.route(router_input, llm=user_llm)
    yield sse_event("router", decision.model_dump(mode="json"))
    # 3. 调度到对应 Agent（agent 字段值即 AgentManager 注册 key）
    agent = agent_manager.get_agent(decision.agent)
    state = build_initial_state(decision, router_input)
    # 4. LangGraph 流式执行
    async for event in agent.astream(state):
        yield event
```

> **关键**：`router_agent.route()` 已在内部完成记忆恢复、规则候选、LLM 判别、guardrails、兜底、trace 记录，业务侧只需传入 `router_input` 和 `user_llm`，不要重复实现这些逻辑。

---

## 文件结构与新增文件

```text
agent_service/                         # 新建包，与 rag_service/embedding_service 平级
├── __init__.py
├── router/                            # ★ 已实现（Router Agent，编排层路由，非 LangGraph）—— 不再开发，业务 Agent 直接复用
│   ├── __init__.py                    # 导出 RouterAgent / RouterDecision / RouterInput / LegalMemory / Candidate / LegalAgentState / build_initial_state
│   ├── router.py                      # RouterAgent 主类（route() 入口，llm 运行时注入）
│   ├── models.py                      # RouterInput / RouterDecision / Candidate / LegalMemory / RetrievalScope / LegalContext / TimeContext
│   ├── rules.py                       # 规则候选生成（产出 candidates 列表，不直接决策）
│   ├── prompt.py                      # LLM Prompt 模板 + 7 个 Few-Shot 示例
│   ├── fallback.py                    # apply_guardrails（confidence clamp）+ fallback_from_candidates
│   ├── state_mapper.py                # LegalAgentState + build_initial_state（RouterDecision → Agent 初始 State）
│   ├── dependencies.py                # get_router_agent / get_memory FastAPI 依赖注入
│   └── trace.py                       # Router 可观测性记录
├── llm/                               # LLM 抽象层（待开发，需支持 BYOK 运行时注入）
│   ├── __init__.py
│   ├── base.py                        # BaseLLM + LLMFactory + LLMMessage
│   ├── stream.py                      # SSE 事件封装 + token 流转换
│   ├── byok.py                        # 新增：按 user_id 从 user_llm_config 加载 LLM 实例（加密 API Key 解密）
│   └── providers/
│       ├── __init__.py
│       ├── openai_provider.py         # OpenAI / 兼容接口基类
│       ├── deepseek_provider.py       # DeepSeek-V3/R1
│       └── qwen_provider.py           # 通义千问
├── memory/                            # 法律上下文记忆（待开发，需与 Router 的 _hydrate_context 对齐）
│   ├── __init__.py
│   ├── base.py                        # BaseMemory 抽象（load / load_summary / load_files / update）
│   ├── redis_memory.py                # 短期活跃会话（Redis, TTL 24h）
│   └── legal_memory.py                # LegalMemory 结构 + 压缩策略（与 router.models.LegalMemory 同构）
├── tools/                             # 内部 Python 函数工具（待开发）
│   ├── __init__.py
│   ├── base.py                        # BaseTool + ToolRegistry
│   ├── law_query_tool.py             # 法条查询（复用 HybridRetriever）
│   ├── law_version_tool.py           # 法条版本查询
│   ├── web_search_tool.py            # Tavily 联网搜索
│   ├── contract_review_tool.py       # 合同条款审查
│   └── doc_generate_tool.py          # 文书生成（阶段五预留）
├── agents/                            # LangGraph Agent 实现（待开发）
│   ├── __init__.py
│   ├── base.py                        # BaseAgent（共享状态图骨架，消费 build_initial_state 产出的 state）
│   ├── state.py                       # LegalAgentState 运行期字段扩展（与 router.state_mapper.LegalAgentState 同名兼容）
│   ├── manager.py                     # ★ AgentManager（按 decision.agent dispatch 到 4 个 Agent，key 严格匹配）
│   ├── law_qa.py                      # 法律咨询 Agent（注册 key = "law_qa"）
│   ├── article_locate.py             # 法条定位 Agent（注册 key = "article_locate"）
│   ├── contract_review.py            # 合同审查 Agent（注册 key = "contract_review"）
│   └── case_analysis.py              # 案例分析 Agent（注册 key = "case_analysis"，Tavily 联网版）
├── citation/                          # 引用扩展（待开发）
│   ├── __init__.py
│   ├── validator.py                   # Citation Validator 防幻觉
│   └── web_citation.py                # 网络来源引用构建
├── routers/
│   └── agent.py                       # /api/agent/* SSE 聊天接口（调用已实现 RouterAgent + 待开发 AgentManager）
└── schemas/
    └── agent.py                       # 请求/响应 Pydantic schema

backend/
├── services/
│   ├── ocr.py                         # 新增：PaddleOCR 封装（合同扫描件兜底）
│   └── contract_clause_parser.py      # 新增：合同条款结构化切分
├── models/
│   ├── conversation.py                # 新增：Conversation/Message ORM
│   └── user_llm_config.py             # 已存在：user_llm_config ORM（BYOK 配置，API Key 加密，级联删除）
├── routers/
│   └── conversation.py                # 新增：会话管理接口（列表/详情/删除）
└── main.py                             # lifespan 注册 agent_service（Router 已注册，新增 AgentManager）

sql/migrations/
└── 002_phase4_agent.sql               # 阶段四迁移脚本（conversation/message/agent_config 表）
```

> **包命名**：使用下划线 `agent_service`，不要创建带连字符的 `agent-service`。

### 服务边界

- `agent_service/` 只放 Agent 编排、LLM、工具、记忆、引用扩展代码
- `backend/` 保留通用骨架、会话/消息 ORM、OCR、合同解析、Parser Worker
- `rag_service/` 阶段三检索代码不改动，Agent 通过依赖注入调用 `HybridRetriever`
- `embedding_service/` 阶段三向量化代码不改动

---

## 接口设计

### SSE 聊天接口（核心）

> **agent 由 Router 决定，请求体不含 `agent_type`**。完整处理链（BYOK 加载 → Router.route → AgentManager → Agent.astream）见关键设计八的 SSE 调用示例，此处只列接口签名与协议。

```python
# agent_service/routers/agent.py
router = APIRouter(prefix="/api/agent", tags=["Agent"])

@router.post("/chat")
async def chat(
    body: AgentChatRequest,
    current_user = Depends(get_current_user),
    router_agent = Depends(get_router_agent),    # 复用已实现 Router
    agent_manager = Depends(get_agent_manager),
    memory = Depends(get_memory),
):
    """SSE 流式对话接口（agent 由 Router 自动路由）。
    请求:
        {
            "conversation_id": "uuid-xxx",     # 首次为空则创建新会话
            "query": "租房漏水房东不修怎么办",
            "kb_ids": ["civil_code"]           # 可选，默认用会话绑定
        }
    响应: text/event-stream
        data: {"event":"router","agent":"law_qa","task_type":"legal_question",...}  # 首事件：路由决策
        data: {"event":"node_start","node":"intent"}
        data: {"event":"token","content":"根据"}
        ...
        data: {"event":"done","message_id":123,"trace_id":"xxx"}
    """

@router.post("/contract/review")
async def contract_review(
    body: ContractReviewRequest,
    current_user = Depends(get_current_user),
):
    """合同审查专用入口（异步任务 + SSE）。
    请求:
        {
            "document_id": "contract_001",     # 已上传解析的合同文档
            "review_dimensions": ["legality","fairness","completeness"],
            "contract_type": "IT服务合同"       # 可选
        }
    响应: SSE 流式输出审查报告
    """
```

### 会话管理接口

```python
# backend/routers/conversation.py
@router.get("/api/conversation/list")         # 会话列表
@router.get("/api/conversation/{id}")         # 会话详情（含消息历史）
@router.delete("/api/conversation/{id}")      # 删除会话
@router.get("/api/conversation/{id}/messages") # 消息分页
@router.post("/api/conversation/{id}/message/{msg_id}/feedback")  # 点赞/点踩
```

---

## 配置项（backend/config.py 新增）

> **BYOK 优先**：LLM 配置按用户动态加载（`user_llm_config` 表，API Key 加密存储，用户删除级联清理）。下方 `.env` 配置仅作为**全局兜底 LLM**，用于未配置 BYOK 的用户或 Router 兜底场景。Router 自身的 LLM 参数（`router_llm_temperature` / `router_llm_max_tokens` / `router_llm_timeout` / `router_llm_retry` / `router_confidence_threshold` / `router_confidence_max`）已在阶段四 Router 开发时落地，不再重复列出。

```python
# ========== LLM 配置（全局兜底，BYOK 优先级更高） ==========
llm_provider: str = "deepseek"          # 兜底 provider；用户 BYOK 未配置时使用
llm_model: str = "deepseek-chat"
llm_api_base: str = "https://api.deepseek.com/v1"
llm_api_key: str = ""                   # 兜底 API Key（生产环境通过部署平台注入）
llm_temperature: float = 0.30
llm_max_tokens: int = 4096
llm_stream_timeout: int = 120            # SSE 流式超时（秒）

# ========== BYOK 配置 ==========
byok_enabled: bool = True                # 开启按用户 LLM 注入；关闭则全部走全局兜底
byok_api_key_secret: str = ""            # user_llm_config.api_key 的加密密钥（部署平台注入）
byok_fallback_to_global: bool = True     # 用户未配置时回退到全局兜底 LLM

# ========== Tavily 联网搜索 ==========
tavily_api_key: str = ""
tavily_api_base: str = "https://api.tavily.com"
tavily_max_results: int = 5
tavily_search_depth: str = "advanced"   # basic / advanced

# ========== OCR 配置（合同审查） ==========
ocr_provider: str = "paddle"             # paddle / mineru / none
paddle_ocr_lang: str = "ch"              # PaddleOCR 语言
paddle_use_gpu: bool = False

# ========== Agent 记忆 ==========
agent_memory_ttl: int = 86400            # 短期记忆 TTL（秒，默认 24h）
agent_memory_max_turns: int = 6          # 超过则触发压缩
agent_memory_max_tokens: int = 4000      # 压缩后 token 上限

# ========== LangGraph ==========
langgraph_checkpoint_enabled: bool = False  # 阶段四单次会话不持久化 checkpoint
agent_retry_max: int = 1                  # Retrieve/Validate 重试上限

# ========== 引用校验 ==========
citation_validation_enabled: bool = True  # 防幻觉开关
```

> **user_llm_config 表已存在**（见 `sql/init.sql`，含 `user_id` / `provider` / `model_name` / `api_base` / `api_key`（加密）/ `temperature` / `max_tokens` / `timeout` / `retry` 等字段，`user_id` 外键级联删除）。BYOK 加载逻辑（`agent_service/llm/byok.py`）从该表读取并解密，可选字段为 NULL 时回退到全局默认值（避免 NULL 引发 TypeError）。

---

## lifespan 集成（backend/main.py）

> **Router Agent 已注册**：`app.state.router_agent` 在阶段四 Router 开发时已挂载（见 `backend/main.py` 现有 lifespan）。本阶段只需新增 `AgentManager` 与待开发组件，**不要重复注册 Router**，也不要给 Router 注入全局 LLM（LLM 走 BYOK，每次 `route()` 运行时按 user 注入）。

```python
# startup 新增（Router 相关导入与注册已存在，此处只列待开发组件）:
from agent_service.llm import LLMFactory, register_providers   # provider 注册表
from agent_service.llm.byok import load_user_llm               # BYOK：按 user_id 从 user_llm_config 加载
from agent_service.tools import ToolRegistry
from agent_service.memory import RedisMemory
from agent_service.agents import AgentManager                   # ★ 待开发：Agent 调度器
from agent_service.citation import CitationValidator

# LLM provider 注册（仅注册类，不创建全局实例 —— LLM 按 user 动态创建）
register_providers()                                            # openai / deepseek / qwen
app.state.tool_registry = ToolRegistry()
app.state.memory = RedisMemory(redis)                           # Router 已依赖此 memory 实例
app.state.citation_validator = CitationValidator()

# Router Agent —— 已在现有 lifespan 注册（app.state.router_agent），不重复注册。
# 关键：Router 构造时不传 llm，route(router_input, llm=user_llm) 时按 user 运行时注入。
# 若需保留全局兜底 LLM（如未配置 BYOK 的用户），可传 llm=fallback_llm，但优先级低于运行时注入。

# Agent Manager（待开发：Router 后调度到具体 LangGraph Agent）
# 注意：不传全局 llm，Agent 节点的 LLM 由 BYOK 在请求链中按 user 注入
app.state.agent_manager = AgentManager(
    retriever=app.state.hybrid_retriever,    # 阶段三已初始化
    context_builder=app.state.context_builder,
    tool_registry=app.state.tool_registry,
    memory=app.state.memory,
    citation_validator=app.state.citation_validator,
)

# 挂载 router（agent_router 待开发，conversation_router 待开发）
app.include_router(agent_router)
app.include_router(conversation_router)
```

### SSE 请求处理链（Router → AgentManager → Agent）

> **关键调整**：Memory 不再在 SSE 入口手动加载 —— Router 的 `_hydrate_context` 已自动从 `app.state.memory` 补齐 `history_summary` / `legal_memory` / `uploaded_files`。LLM 走 BYOK，按 `user_id` 从 `user_llm_config` 加载后注入 `route()` 和 Agent 节点。

```python
# agent_service/routers/agent.py
@router.post("/chat")
async def chat(body: AgentChatRequest, current_user = Depends(get_current_user),
              router_agent = Depends(get_router_agent),        # 复用已实现
              agent_manager = Depends(get_agent_manager),
              memory = Depends(get_memory)):
    """SSE 流式对话接口。

    处理链：
    1. BYOK 加载用户 LLM（从 user_llm_config 按 user_id 解密）
    2. 构造 RouterInput（memory/history/files 由 Router 内部 _hydrate_context 自动补齐）
    3. RouterAgent.route(input, llm=user_llm) → RouterDecision
    4. AgentManager.get_agent(decision.agent) → 取对应 Agent 实例
    5. build_initial_state(decision, input) → Agent 初始 State
    6. Agent.astream(state) → LangGraph 异步流式执行（Agent 内部 LLM 也用 user_llm）
    7. SSE 事件流转给前端
    """
    async def event_stream():
        # Step 1: BYOK 加载用户 LLM（user_llm_config 表，API Key 加密存储）
        user_llm = await load_user_llm(current_user.id)

        # Step 2: 构造 RouterInput（不要手动塞 memory，Router 内部自动补齐）
        router_input = RouterInput(
            user_query=body.query,
            conversation_id=body.conversation_id,
            user_id=current_user.id,
            tenant_id=current_user.tenant_id,
            available_kbs=body.kb_ids or [],
        )

        # Step 3: Router 决策（llm 运行时注入；route() 内部完成记忆恢复/规则候选/LLM判别/guardrails/兜底/trace）
        decision = await router_agent.route(router_input, llm=user_llm)

        # SSE: 推送路由决策（前端展示"识别为：法律咨询"等）
        yield sse_event("router", decision.model_dump(mode="json"))

        # Step 4: 调度到对应 Agent（agent 字段值即 AgentManager 注册 key）
        agent = agent_manager.get_agent(decision.agent, llm=user_llm)   # Agent 内部 LLM 也 BYOK
        state = build_initial_state(decision, router_input)

        # Step 5: LangGraph 流式执行
        async for event in agent.astream(state):
            yield event    # token / tool_start / tool_end / citation / done

        # Step 6: 更新 Memory（current_case/current_law）
        await memory.update(body.conversation_id, state.legal_memory)

    return EventSourceResponse(event_stream())
```

---

## 依赖新增

```toml
"langgraph>=0.2.0",        # Agent 状态图编排
"openai>=1.50.0",          # LLM SDK（复用，已存在）
"httpx>=0.27.0",           # Tavily HTTP 调用（复用，已存在）
"paddleocr>=2.7.0",        # OCR 兜底（可选，按需安装）
"paddlepaddle>=2.6.0",    # PaddleOCR 依赖（可选）
```

> PaddleOCR 体积较大，作为可选依赖。若 MinerU 已能处理扫描件，可不安装 PaddleOCR。

---

## 验证方式

> **agent 由 Router 自动决定**：`/api/agent/chat` 请求体只传 `query` / `conversation_id` / `kb_ids`，**不传 `agent_type`**。Router 根据 query + memory + files 自动路由到 4 个 Agent 之一，SSE 首个事件 `router` 会回传 `RouterDecision`（含 `agent` 字段），可用于核对路由是否正确。

```bash
# 1. 语法检查
uv run python -m compileall backend agent_service tests

# 2. 导入检查
uv run python -c "import backend.main; import agent_service.agents.law_qa; print('import ok')"

# 3. Router 单元测试（已实现，回归保护）
uv run python -m unittest tests.test_router -v

# 4. 执行迁移
mysql -u root -p lawrag < sql/migrations/002_phase4_agent.sql

# 5. 启动服务
uv run uvicorn backend.main:app --reload --port 8000

# 6. 法律咨询（Router 自动路由到 law_qa）
curl -N -X POST http://localhost:8000/api/agent/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "",
    "query": "租房漏水房东不修怎么办",
    "kb_ids": ["civil_code"]
  }'
# → SSE 首事件 router.agent="law_qa" → 流式回答 + 引用民法典第712/713条

# 7. 法条定位（Router 识别"民法典关于违约金的条款"→ article_locate）
curl -N -X POST http://localhost:8000/api/agent/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "民法典关于违约金的条款",
    "kb_ids": ["civil_code"]
  }'
# → SSE 首事件 router.agent="article_locate" → 返回第585条 + 条款树

# 8. 案例分析（Router 识别案情描述 → case_analysis，联网）
curl -N -X POST http://localhost:8000/api/agent/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "甲公司向乙公司买设备，交货后甲以质量瑕疵拒付，乙起诉追款，类似案例怎么判",
    "kb_ids": ["civil_code"]
  }'
# → SSE 首事件 router.agent="case_analysis" → 联网搜索类似案例 + 本地法条引用 + 网络来源引用

# 9. 合同审查（独立入口，已上传合同文档）
curl -N -X POST http://localhost:8000/api/agent/contract/review \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "document_id": "contract_001",
    "review_dimensions": ["legality","fairness","completeness"]
  }'
# → 流式输出审查报告（风险条款 + 法条引用 + 修改建议）
```

---

## 阶段四目标边界

### 必须完成

> Router Agent 已开发完成并通过测试，**不在本阶段任务列表内**。本阶段所有任务必须遵守关键设计八的对接契约，确保 Router 产出的 `RouterDecision` 能正确驱动 4 个业务 Agent。

| # | 模块 | 说明 |
|---|------|------|
| 1 | LLM 抽象层 + BYOK | 多 provider 注册表 + SSE 流式 + 工具调用 + 按 user_id 从 `user_llm_config` 动态加载（API Key 加密） |
| 2 | LangGraph 基础状态图 | 共享骨架 + 条件边 + 重试上限防死循环；初始 State 由 `build_initial_state()` 产出 |
| 3 | 工具系统 | BaseTool + ToolRegistry 注册表，5 个内置工具 |
| 4 | **AgentManager** | **按 `decision.agent` dispatch 到 4 个 Agent，注册 key 与 agent 字段严格一致** |
| 5 | 法律咨询 Agent | 完整闭环：Intent→Retrieve→Reason→Cite→Validate（注册 key = `law_qa`） |
| 6 | 法条定位 Agent | BM25 优先 + 条款树展开（注册 key = `article_locate`） |
| 7 | 案例分析 Agent | Tavily 联网搜索 + 网络来源引用 + sub_questions 多路检索（注册 key = `case_analysis`） |
| 8 | 合同审查 Agent | OCR 依赖 + 条款切分 + 规则引擎 + LLM 审查 + 报告（注册 key = `contract_review`） |
| 9 | Memory 管理 | Redis 短期 + MySQL 长期 + 结构化 LegalMemory（与 `router.models.LegalMemory` 同构）+ 压缩；`load`/`load_summary`/`load_files` 接口供 Router `_hydrate_context` 调用 |
| 10 | Citation 体系扩展 | 法条引用 + 网络来源引用 |
| 11 | Citation Validator | 防幻觉校验（编号一致性 + 法条真实性回查） |
| 12 | SSE 流式接口 | /api/agent/chat：BYOK 加载 → Router.route(llm=user_llm) → AgentManager → Agent.astream |
| 13 | 会话管理 | conversation/message 表 + 接口 |
| 14 | OCR 兜底 | PaddleOCR 封装（MinerU 不可用时） |
| 15 | 合同条款切分 | contract_clause_parser |

### 已完成（不再列入本阶段任务）

| # | 模块 | 位置 |
|---|------|------|
| ✅ | Router Agent（编排层路由） | [agent_service/router/](file:///g:/agent-project/LawRAG/agent_service/router) + [doc/17-Router Agent 设计方案.md](file:///g:/agent-project/LawRAG/doc/17-Router%20Agent%20设计方案.md)，已通过 13 个单元测试 |
| ✅ | user_llm_config 表 | `sql/init.sql`（含外键级联删除） |

### 暂不强制（预留）

| # | 模块 | 阶段 |
|---|------|------|
| 1 | 文书生成 Agent (document_generate) | 阶段五（DocGenerateTool 已预留接口） |
| 2 | Agent Builder 后台配置化 | 阶段五（agent_config 表已预留） |
| 3 | 多 Agent 协作（Orchestrator） | 阶段五 |
| 4 | 知识图谱检索 (Neo4j) | 阶段五 |
| 5 | LangGraph Checkpoint 持久化（对话暂停恢复） | 阶段五（阶段四单次会话不持久化） |
| 6 | Eval Service 在线评估 | 阶段五 |
| 7 | MCP 协议化工具（跨进程） | 阶段六（接口已预留兼容） |
| 8 | Cross-Encoder Rerank | 阶段四可接入（阶段三已留接口） |

---

## 未来扩展（阶段五—阶段六预留）

### 阶段五：Agent 增强 + Graph Retrieval

- `LLMQueryRewriter` 替换 `RuleQueryRewriter`（阶段三已留接口）
- 文书生成 Agent 落地
- Agent Builder 后台配置化 + 版本管理
- 多 Agent 协作（Orchestrator）
- Neo4j 知识图谱接入（法条引用链、判例网）
- LangGraph Checkpoint 持久化（Postgres/Redis checkpointer）
- Eval Service 在线评估 + Bad Case 回流

### 阶段六：MCP 协议化 + Hybrid Search V2

- 工具迁移 MCP 协议（BaseTool 接口不变，实现改为 MCP 客户端）
- Elasticsearch 替换 BM25
- GraphRAG：向量库 + 图库联合检索
- 多 Agent 跨服务编排

---

## 禁止事项

> Router Agent 已实现，下列与 Router 相关的条目是**已落地的设计约束**，业务 Agent 不得违反或绕过；其余为本阶段开发的通用红线。

### 防幻觉红线

- **禁止 LLM 凭记忆复述法条原文** — 法条必须来自 `knowledge_chunk.text`（检索结果）
- **禁止在 Agent 里重写检索链路** — Retrieve 节点只调用 `HybridRetriever.retrieve()`
- **禁止杜撰法条编号** — Citation Validator 必须回查 MySQL 验证法条真实存在
- **禁止引用未在 context_text 出现的法条** — 视为幻觉，触发重新生成
- **`legal_level` 禁止通过 `law_name` 字符串推断** — 只从 metadata 字段读取（阶段三红线延续）

### Router 对接契约（已实现，不得破坏）

- **禁止业务 Agent 绕过 Router 直接调度** — 必须先 `router_agent.route()` 拿到 `RouterDecision`，再 `AgentManager.get_agent(decision.agent)`，不得跳过路由直接走某个 Agent
- **禁止 AgentManager 注册 key 与 `RouterDecision.agent` 不一致** — 4 个 key（`law_qa` / `article_locate` / `contract_review` / `case_analysis`）必须与 `agent_service/router/models.py` 的 `AgentType` 严格一致，不得改名、加前缀、大小写错误
- **禁止业务 Agent 自行构造初始 State** — 必须用 `agent_service/router/state_mapper.py` 的 `build_initial_state(decision, router_input)`，避免 `retrieval_scope` / `needs_human_review` 等字段缺失
- **禁止业务 Agent 在内部重新做路由判定** — Router 已决定 agent，Agent 不得再按 query 关键词切换到其他 Agent；如需切换走异常或 `needs_human_review`
- **禁止业务 Agent 反向依赖 Router 内部模块** — 只依赖 `RouterDecision` 这一稳定输出，不得 import `router.rules` / `router.prompt` / `router.fallback` 的内部实现
- **禁止清零 `needs_human_review`** — Router 在 `risk_level=high` 时已置 True，Agent 侧只读，Validate 节点不得覆盖为 False
- **禁止对 `confidence` 二次裁剪** — `apply_guardrails` 已 clamp 到 0.95，Agent 不得再设阈值丢弃合法决策
- **Router 已实现约束（不得违反）**：Router 不调用 HybridRetriever、不生成回答、不写库、不绑定 kb_id、不放 LangGraph、规则只产候选不直接决策 —— 这些是已落地行为，业务 Agent 不得通过修改 Router 代码来打破

### LLM 与 BYOK

- **禁止使用 `.env` 全局 LLM 单例作为唯一来源** — 必须实现 BYOK（按 `user_id` 从 `user_llm_config` 加载），`.env` 仅作兜底
- **禁止明文存储 API Key** — `user_llm_config.api_key` 必须加密存储，加载时解密
- **禁止 user_llm_config 可选字段为 NULL 时直接使用** — `temperature` / `max_tokens` / `timeout` / `retry` 为 NULL 时必须回退到全局默认值，避免 TypeError

### 阶段四技术边界

- **禁止把 LangGraph Checkpoint 强依赖进阶段四** — 单次会话用内存状态即可，持久化放阶段五
- **不要在阶段四引入 Neo4j / Elasticsearch / Kafka** — 阶段五/六再说
- **不要创建带连字符的 `agent-service` 包路径** — 使用下划线 `agent_service`
- **合同 OCR 不可用时不要静默返回空文本** — 必须明确报错并提示用户上传清晰文本
- **Tavily 失败不要阻塞 Agent** — 降级为无网络来源回答，前端标注"联网搜索不可用"
- **不要修改阶段三的 `rag_service` / `embedding_service` 既有代码** — Agent 通过依赖注入调用，不改检索源码
- **不要修改 `sql/init.sql`** — 新表走 `sql/migrations/002_phase4_agent.sql` 迁移
- **不要修改已实现的 `agent_service/router/` 代码** — Router 已通过测试，业务 Agent 通过对接契约消费其输出，不得为适配 Agent 而改动 Router
