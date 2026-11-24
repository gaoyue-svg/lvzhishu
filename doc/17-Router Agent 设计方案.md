# 任务：LawRAG 阶段四 — Router Agent 开发（编排层路由，非 LangGraph）

## 项目背景

LawRAG 法律 RAG 平台，阶段四开发 Agent 闭环。本方案是 [doc/16-Agent设计方案.md](file:///g:/agent-project/LawRAG/doc/16-Agent设计方案.md) 「关键设计八：Router Agent」的细化实施版，作为独立开发提示词，指导 Router Agent 的实现。

Router Agent 是 4 个业务 Agent（law_qa / article_locate / contract_review / case_analysis）执行前的**编排层决策器**，负责理解用户请求 → 选择处理 Agent → 提取检索前置参数 → 调度执行。

> **本文档不涉及业务 Agent 内部实现**（Intent/Retrieve/Reason/Cite/Validate 状态图），业务 Agent 见 16 号文档。本文档只定义 Router 的输入、输出、内部流程、Prompt、兜底、注入映射。

---

## 核心设计原则

1. **Router 是纯决策层**：只输出 `RouterDecision` JSON，不检索、不生成答案、不执行工具、不写库
2. **不放 LangGraph**：Router 只做一次决策，单节点状态图是过度设计，FastAPI 直接调用 RouterService 即可
3. **规则产生候选，LLM 最终确认**：规则不直接覆盖返回，避免"民法典第585条...怎么判"被规则误判为 article_locate
4. **多轮场景必注入 Memory**：用户第 2 轮说"那我可以直接换锁吗"，单看 query 任何 LLM 都判不准意图
5. **不绑定具体 kb_id**：`retrieval_scope` 只给 domain/category/keywords 建议，由 Retriever 决定具体库
6. **永远留兜底余地**：`confidence` 上限 0.95，`< 0.6` 强制降级到 law_qa

---

## 1. 职责边界

### Router Agent 做什么

- 理解用户请求（含多轮上下文）
- 判断任务类型（`task_type`）
- 选择执行 Agent（`agent`）
- 提取检索前置参数（`retrieval_scope` / `legal_context` / `time_context` / `sub_questions`）
- 评估风险等级（`risk_level`）
- 输出结构化 `RouterDecision` JSON

### Router Agent 不做什么

- ❌ 不调用 HybridRetriever（检索由 Agent 的 Retrieve 节点负责）
- ❌ 不调用 LLM 生成回答（Router 只输出路由决策 JSON）
- ❌ 不调用工具（工具由 Agent 的 Tool 节点负责）
- ❌ 不写数据库（只读 Memory，不修改）
- ❌ 不绑定具体 kb_id（只给检索建议，由 Retriever 决定具体库）
- ❌ 不放进 LangGraph 状态图

---

## 2. 系统位置与处理链

```text
                  User Query
                      |
                      v
              +-----------------+
              |  Router Agent   |   ← 编排层（非 LangGraph，本方案）
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
 law_qa  article_locate contract_review case_analysis   ← 业务 Agent（LangGraph，16号文档）
    |         |         |         |
    +---------+---------+---------+
              |
       Retrieval Layer
              |
         QueryRouter          ← 阶段三检索层（规则版，给检索器配权重）
              |
       HybridRetriever
              |
            LLM
```

### 与阶段三 QueryRouter 的职责分工

| 维度 | Router Agent（本方案） | QueryRouter（阶段三已有） |
|------|----------------------|------------------------|
| 层级 | 编排层（Agent 之前） | 检索层（HybridRetriever 内部） |
| 输入 | user_query + memory + files | legal_query（已重写） |
| 输出 | agent_type + 检索参数建议 | RRF 权重 + filter_expr |
| 职责 | 决定走哪个 Agent | 决定检索器内部 BM25/Milvus 配比 |
| 是否感知 Agent | 是（核心输出） | 否（不感知 Agent 存在） |

**衔接方式**：Router 的 `task_type` 透传给 HybridRetriever，QueryRouter 根据 task_type 选对应 RRF 权重。两者不冲突。

---

## 3. RouterInput 输入规范

```python
class RouterInput:
    user_query: str                          # 用户原始输入
    conversation_id: str                     # 会话 ID
    user_id: str
    tenant_id: str
    history_summary: str | None             # 多轮压缩摘要（来自 Memory，单轮为空）
    legal_memory: LegalMemory | None        # 结构化法律记忆（见 §9）
    uploaded_files: list[dict]               # 本次会话已上传文件
                                            # [{document_id, file_name, doc_type}]
                                            # doc_type: contract / case_doc / evidence / ...
    available_kbs: list[dict]                # 当前租户可用知识库
                                            # [{kb_id, name, type, domain}]
```

> **关键约束**：`history_summary` 和 `legal_memory` 必须注入。单轮首句场景可为空，但多轮场景缺失必误判。

---

## 4. RouterDecision 输出 Schema（定稿）

```python
class RouterDecision:
    # ===== 核心路由 =====
    task_type: str          # 任务类型（见 §4.1 枚举）
    agent: str              # 执行 Agent（law_qa / article_locate / contract_review / case_analysis）
    confidence: float       # 路由决策可靠程度 0~1（≠ LLM 自评分，含规则/兜底综合判定，上限 0.95）

    # ===== 检索建议（不绑定具体 kb_id，由 Retriever 决定）=====
    need_retrieval: bool
    retrieval_scope: dict   # {
                            #   "domain": "civil",           # 民事/刑事/行政/商事
                            #   "category": "contract",       # 合同/侵权/婚姻/公司/劳动...
                            #   "keywords": ["违约金","合同解除"]
                            # }

    # ===== 文件需求 =====
    need_file: bool
    file_requirement: dict | None  # {"type":"contract","hint":"请上传合同 PDF"}

    # ===== 法律上下文（传给 Agent，影响检索过滤）=====
    legal_context: dict     # {
                            #   "law_name": "民法典",
                            #   "article_no": null,
                            #   "cause_of_action": "合同纠纷"
                            # }

    # ===== 子问题分解（仅 law_qa / case_analysis 产出）=====
    sub_questions: list[str]

    # ===== 时间上下文（影响阶段三 QueryRouter 的 is_latest 过滤）=====
    time_context: dict      # {"type":"latest", "year":null}
                            # type: latest / current / historical
                            # historical 时 year 必填，放开 is_latest 过滤

    # ===== 执行模式（影响 Agent 编排）=====
    execution_mode: str     # rag / multi_step / document_analysis
                            # law_qa→rag, case_analysis→multi_step, contract_review→document_analysis

    # ===== 风险等级（法律场景特有）=====
    risk_level: str         # low / medium / high
                            # high → 强制免责声明 + 触发 needs_human_review
                            # 刑事/自残/暴力/敏感类问题 → high

    # ===== 可观测性 =====
    route_reason: str       # 一句话说明为什么这么路由
    fallback: bool          # 是否走了兜底（低置信度降级到 law_qa）
```

### 4.1 task_type 枚举

```text
legal_question       日常法律问题咨询
article_lookup       精确查找法条
contract_review      合同审查
case_search          案例分析
document_generation  文书生成（阶段五，阶段四不支持 → 降级 law_qa）
```

### 4.2 execution_mode 枚举

```text
rag                 单轮检索问答（law_qa / article_locate）
multi_step          多步推理（case_analysis：联网搜索+本地检索+综合分析）
document_analysis   文件解析+审查（contract_review：OCR+条款切分+规则引擎+LLM审查）
```

### 4.3 risk_level 枚举

```text
low     普通咨询（民事、行政程序性咨询）
medium  合同审查、案例分析（涉及具体法律后果）
high    刑事案件、自残自杀、暴力、未成年人保护、敏感政治问题
        → 强制免责声明 + needs_human_review=True + 前端显著风险提示
```

### 4.4 字段与 4 个 Agent 的对应关系

| 字段 | law_qa | article_locate | contract_review | case_analysis |
|------|--------|----------------|------------------|---------------|
| `task_type` | legal_question | article_lookup | contract_review | case_search |
| `execution_mode` | rag | rag | document_analysis | multi_step |
| `need_retrieval` | True | True | True（按风险条款检索法条） | True+联网搜索 |
| `retrieval_scope.domain` | 按领域 | 按法律 | civil | 按案由 |
| `need_file` | False | False | True（需合同文件） | False |
| `sub_questions` | 产出 | 不产出 | 不产出 | 产出 |
| `risk_level` | low/medium | low | medium | medium |

---

## 5. Router 内部流程（4 步）

```text
输入: user_query + memory + uploaded_files + available_kbs
  ↓
┌─ Step 1: Memory 上下文恢复 ─┐
│  - 读取 history_summary + legal_memory
│  - 判断是否多轮延续（current_case/current_law 非空 → 候选加延续分）
└──────────┬──────────────┘
           ↓
┌─ Step 2: 规则候选生成（不直接返回）─┐
│  每条规则命中产生 candidate:
│    {agent, score, reason}
│  多条规则可同时命中（如"民法典第585条...怎么判"
│    → article_locate(score=0.8) + case_analysis(score=0.7) 同时候选）
│  候选列表作为 route_hint 传给 LLM
│  Memory 延续判定 → candidate=None + score=0.5（表示延续上一轮 agent）
└──────────┬──────────────────────────────┘
           ↓
┌─ Step 3: LLM 深度判别 ───────────────────┐
│  注入: query + memory + files + route_hint(候选列表)
│  LLM 在候选基础上做最终决策，可推翻候选
│  function calling 强制 JSON 输出
│  temperature=0.1
│  超时 8s
└──────────┬───────────────────────────────┘
           ↓
┌─ Step 4: 兜底与校验 ──────────────────────┐
│  confidence < 0.6 → fallback=True, agent=law_qa
│  LLM 调用失败/超时 → 用候选列表中 score 最高的兜底；无候选则 law_qa
│  risk_level=high → 强制 needs_human_review=True
│  字段一致性校验（need_file=true 但 file_requirement=None → 补默认值）
│  time_context.type=historical 但 year 缺失 → 降级为 current
└──────────┬────────────────────────────────┘
           ↓
输出: RouterDecision
```

### 5.1 为什么规则不直接返回

**反面案例**：

```text
query: "民法典第585条关于合同违约金，如果实际案件中怎么判？"

规则匹配:
  - "第585条" + "民法典" → article_locate (score=0.95)   ← 规则直接返回会误判
  - "怎么判" → case_analysis (score=0.7)

正确判定: case_analysis（用户问的是"实际案件怎么判"，不是查法条原文）
```

**正确做法**：规则产出候选列表 `[{article_locate, 0.8}, {case_analysis, 0.7}]`，LLM 结合上下文最终判定 `agent=case_analysis`。

---

## 6. 规则候选生成

### 6.1 规则定义

每条规则是一个 `(条件函数, agent, score, reason)` 元组。条件命中即产生一个候选，多条规则可同时命中产生多个候选。

```python
ROUTER_RULES = [
    # (条件函数, agent, score, reason)
    # 多条规则可同时命中，产生多个候选

    (lambda q, ctx: re.search(r"第[一二三四五六七八九十百千万零〇0-9]+条", q)
                    and any(kw in q for kw in ["民法典","刑法","劳动合同法","公司法","行政法"]),
     "article_locate", 0.8, "query 含法条编号+法律名"),

    (lambda q, ctx: ctx.uploaded_files
                    and any(f["doc_type"] == "contract" for f in ctx.uploaded_files),
     "contract_review", 0.85, "已上传合同文件"),

    (lambda q, ctx: any(kw in q for kw in ["审查","风险","条款问题"]),
     "contract_review", 0.6, "审查关键词"),

    (lambda q, ctx: any(kw in q for kw in ["类似案例","判例","怎么判","判决书"]),
     "case_analysis", 0.7, "案例检索关键词"),

    (lambda q, ctx: any(kw in q for kw in ["生成律师函","法律意见书","起草合同"]),
     "law_qa", 0.85, "文书生成暂不支持，降级 law_qa"),

    # Memory 延续判定（candidate=None 表示延续上一轮 agent）
    (lambda q, ctx: ctx.legal_memory and ctx.legal_memory.current_case,
     None, 0.5, "多轮延续（延续上一轮 agent）"),
]
```

### 6.2 规则候选示例

```text
query: "民法典第585条关于违约金，实际案件怎么判？"

candidates = [
  {agent:"article_locate", score:0.8, reason:"query含法条编号"},
  {agent:"case_analysis",  score:0.7, reason:"案例检索关键词"}
]

→ 候选列表作为 route_hint 注入 LLM Prompt
→ LLM 最终判定 agent=case_analysis（因用户问"实际案件怎么判"）
```

### 6.3 规则扩展原则

- 新增规则只需在 `ROUTER_RULES` 列表追加元组，不改主流程
- 每条规则的 `score` 是候选权重，不是最终 confidence
- 规则的 `reason` 会透传到 `route_reason` 字段，便于 debug
- 规则只产生候选，不直接决定最终 agent（LLM 才是决策者）

---

## 7. LLM Prompt 设计（核心）

### 7.1 System Prompt（完整版）

```text
你是法律 RAG 系统的路由器。你的职责是：理解用户请求 → 选择处理 Agent → 提取检索前置参数。

【重要约束】
1. 你不负责检索、不负责生成答案，只输出路由决策 JSON
2. 必须严格按 JSON Schema 输出，不要输出任何解释性文字
3. 法律场景必须保守：confidence 永远不超过 0.95
4. 用户明确指令优先级最高（"帮我审查合同"即使没上传文件也走 contract_review，need_file=true）
5. 多轮对话优先看 legal_memory.current_case / current_law，延续上一轮 agent

【可用 Agent】
- law_qa: 日常法律问题咨询（"租房漏水怎么办""违约金怎么算"）
- article_locate: 精确查找法条（"民法典第585条""劳动合同法关于加班的规定"）
- contract_review: 合同审查（用户上传合同 + 要求审查风险）
- case_analysis: 案例分析（描述案情寻求类似判例，联网搜索）

【task_type 枚举】
- legal_question: 日常法律问题咨询
- article_lookup: 精确查找法条
- contract_review: 合同审查
- case_search: 案例分析
- document_generation: 文书生成（暂不支持，降级为 legal_question + agent=law_qa）

【execution_mode 枚举】
- rag: 单轮检索问答（law_qa / article_locate）
- multi_step: 多步推理（case_analysis：联网搜索 + 本地检索 + 综合分析）
- document_analysis: 文件解析+审查（contract_review：OCR + 条款切分 + 规则引擎 + LLM审查）

【risk_level 枚举】
- low: 普通民事咨询、行政程序性咨询
- medium: 合同审查、案例分析（涉及具体法律后果）
- high: 刑事案件、自残自杀、暴力、未成年人保护、敏感政治问题
  （high → 强制 needs_human_review=true，前端展示免责声明）

【输出 JSON Schema】
{
  "task_type": "legal_question | article_lookup | contract_review | case_search | document_generation",
  "agent": "law_qa | article_locate | contract_review | case_analysis",
  "confidence": 0.0~0.95,
  "need_retrieval": bool,
  "retrieval_scope": {
    "domain": "civil | criminal | administrative | commercial",
    "category": "contract | tort | marriage | company | labor | ...",
    "keywords": ["关键词1", "关键词2"]
  },
  "need_file": bool,
  "file_requirement": {"type":"contract|case_doc|evidence|null", "hint":"给用户的提示"} | null,
  "legal_context": {
    "law_name": "法律名 或 null",
    "article_no": "第X条 或 null",
    "cause_of_action": "案由 或 null"
  },
  "sub_questions": ["子问题1", "子问题2"],
  "time_context": {"type":"latest|current|historical", "year": null | 2024},
  "execution_mode": "rag | multi_step | document_analysis",
  "risk_level": "low | medium | high",
  "route_reason": "一句话说明为什么这么路由"
}

【字段填写规则】
1. sub_questions: 仅 law_qa / case_analysis 产出（用于多路检索）；article_locate / contract_review 必须为空数组 []
2. file_requirement: 仅 need_file=true 时非空；need_file=false 时必须为 null
3. time_context.type=historical 时 year 必填（如用户问"2020年当时的规定"）
4. retrieval_scope.keywords: 从 query 中抽取的法律关键词，用于检索增强
5. legal_context: 抽取的法律实体，影响检索过滤和 Agent 推理约束
6. confidence: 综合判定，不是 LLM 自评分；规则候选高 + LLM 确认 → 0.85~0.95；纯 LLM 判定 → 0.6~0.85

【判断优先级】（从高到低）
1. 用户明确指令（"帮我审查合同"→ contract_review，无论其他条件）
2. 多轮延续（legal_memory.current_case 非空 → 延续上一轮 agent，confidence +0.1）
3. 已上传文件类型（contract 文件 + 审查意图 → contract_review）
4. query 含明确法条编号 + 法律名 → article_locate
5. query 含案例检索关键词 → case_analysis
6. 默认兜底 → law_qa（confidence < 0.6 时强制降级）

【风险等级判定规则】
- high: 含"杀人""伤害""自杀""自残""毒品""赌博""未成年""学生""校园"等关键词
- medium: contract_review / case_analysis 默认 medium
- low: 程序性咨询、法条查询、普通民事咨询

【规则候选】（参考，可推翻）
{candidates}
```

### 7.2 User Prompt 模板

```text
【用户输入】
{user_query}

【对话上下文】
history_summary: {history_summary or "无（首轮对话）"}

【法律记忆】
legal_memory.current_case: {legal_memory.current_case or "无"}
legal_memory.current_law: {legal_memory.current_law or "无"}
legal_memory.user_role: {legal_memory.user_role or "未知"}

【已上传文件】
{uploaded_files or "无"}

【可用知识库】
{available_kbs}
```

### 7.3 Few-Shot 示例（注入 System Prompt 末尾）

> 法律场景加 few-shot 显著提升准确率，特别是多轮和模糊 query。

```text
【示例 1: 单轮法条查询】
用户: 民法典第585条是什么
输出:
{
  "task_type": "article_lookup",
  "agent": "article_locate",
  "confidence": 0.92,
  "need_retrieval": true,
  "retrieval_scope": {"domain":"civil","category":"contract","keywords":["违约金","赔偿"]},
  "need_file": false,
  "file_requirement": null,
  "legal_context": {"law_name":"民法典","article_no":"第585条","cause_of_action":null},
  "sub_questions": [],
  "time_context": {"type":"latest","year":null},
  "execution_mode": "rag",
  "risk_level": "low",
  "route_reason": "query 明确指定法条编号+法律名"
}

【示例 2: 多轮延续】
用户: 那如果我要自己修呢
history_summary: 用户为房屋承租人，讨论出租人维修义务（民法典第712条）
legal_memory.current_case: {"domain":"租赁纠纷","party_role":"承租人","facts":["漏水","房东不修"]}
legal_memory.current_law: {"laws":["民法典"],"articles":["第712条"],"topic":"出租人维修义务"}
输出:
{
  "task_type": "legal_question",
  "agent": "law_qa",
  "confidence": 0.88,
  "need_retrieval": true,
  "retrieval_scope": {"domain":"civil","category":"contract","keywords":["自行维修","费用追偿"]},
  "need_file": false,
  "file_requirement": null,
  "legal_context": {"law_name":"民法典","article_no":null,"cause_of_action":"租赁合同纠纷"},
  "sub_questions": ["承租人自行维修的费用如何追偿","民法典第713条适用条件"],
  "time_context": {"type":"latest","year":null},
  "execution_mode": "rag",
  "risk_level": "low",
  "route_reason": "多轮延续 law_qa，结合 current_case 判定为租赁纠纷续问"
}

【示例 3: 合同审查（已上传文件）】
用户: 帮我看看这份合同有没有问题
uploaded_files: [{"document_id":"c001","file_name":"租赁合同.pdf","doc_type":"contract"}]
输出:
{
  "task_type": "contract_review",
  "agent": "contract_review",
  "confidence": 0.95,
  "need_retrieval": true,
  "retrieval_scope": {"domain":"civil","category":"contract","keywords":["租赁合同","风险审查"]},
  "need_file": true,
  "file_requirement": {"type":"contract","hint":"合同文件已上传，开始审查"},
  "legal_context": {"law_name":null,"article_no":null,"cause_of_action":null},
  "sub_questions": [],
  "time_context": {"type":"latest","year":null},
  "execution_mode": "document_analysis",
  "risk_level": "medium",
  "route_reason": "已上传 contract 文件 + 审查意图"
}

【示例 4: 合同审查（未上传文件）】
用户: 帮我审查一份租赁合同
uploaded_files: []
输出:
{
  "task_type": "contract_review",
  "agent": "contract_review",
  "confidence": 0.82,
  "need_retrieval": false,
  "need_file": true,
  "file_requirement": {"type":"contract","hint":"请上传需要审查的合同 PDF 或图片"},
  "execution_mode": "document_analysis",
  "risk_level": "medium",
  "route_reason": "用户明确指令审查合同，但未上传文件，路由到 contract_review 由其提示用户上传"
}

【示例 5: 案例分析（含法条编号但实际要案例）】
用户: 民法典第585条关于违约金，实际案件怎么判
规则候选: [{article_locate,0.8}, {case_analysis,0.7}]
输出:
{
  "task_type": "case_search",
  "agent": "case_analysis",
  "confidence": 0.85,
  "need_retrieval": true,
  "retrieval_scope": {"domain":"civil","category":"contract","keywords":["违约金","裁判规则"]},
  "need_file": false,
  "file_requirement": null,
  "legal_context": {"law_name":"民法典","article_no":"第585条","cause_of_action":"合同纠纷"},
  "sub_questions": ["违约金调整的裁判规则","法院对违约金过高的认定标准"],
  "time_context": {"type":"latest","year":null},
  "execution_mode": "multi_step",
  "risk_level": "medium",
  "route_reason": "含法条编号但核心诉求是案例检索，推翻规则候选走 case_analysis"
}

【示例 6: 高风险（刑事）】
用户: 别人打了我，我能还手吗
输出:
{
  "task_type": "legal_question",
  "agent": "law_qa",
  "confidence": 0.78,
  "need_retrieval": true,
  "retrieval_scope": {"domain":"criminal","category":"tort","keywords":["正当防卫","故意伤害"]},
  "need_file": false,
  "file_requirement": null,
  "legal_context": {"law_name":"刑法","article_no":null,"cause_of_action":"正当防卫"},
  "sub_questions": ["正当防卫的认定条件","防卫过当的界限"],
  "time_context": {"type":"latest","year":null},
  "execution_mode": "rag",
  "risk_level": "high",
  "route_reason": "涉及刑事问题（暴力），标记 high 风险，强制人工审核"
}

【示例 7: 文书生成（暂不支持，降级）】
用户: 帮我写一份律师函
输出:
{
  "task_type": "document_generation",
  "agent": "law_qa",
  "confidence": 0.85,
  "need_retrieval": true,
  "retrieval_scope": {"domain":"civil","category":"procedure","keywords":["律师函","法律程序"]},
  "need_file": false,
  "file_requirement": null,
  "execution_mode": "rag",
  "risk_level": "low",
  "route_reason": "文书生成暂不支持，降级为 law_qa 咨询"
}
```

### 7.4 LLM 调用约束

| 参数 | 值 | 理由 |
|------|-----|------|
| `temperature` | 0.1 | 路由要稳，不要创造性 |
| `max_tokens` | 800 | JSON 输出不需要长 token |
| `timeout` | 8s | 路由不能拖慢整个请求 |
| `response_format` | json_object（function calling） | 强制 JSON 输出，避免解析失败 |
| `retry` | 2 次，指数退避 1s/2s | 网络抖动重试，仍失败走兜底 |

---

## 8. 兜底策略

| 场景 | 兜底动作 |
|------|---------|
| `confidence < 0.6` | `fallback=True`, `agent=law_qa`（最通用） |
| LLM 调用失败/超时 | 用候选列表中 score 最高的兜底；无候选则 law_qa（confidence=0.5, fallback=True） |
| `agent=contract_review` 但无上传文件 | 仍路由到 contract_review，由该 Agent 提示用户上传 |
| `risk_level=high` | 强制 `needs_human_review=True`，前端展示免责声明 |
| `time_context.type=historical` 但 year 缺失 | 降级为 current |
| `need_file=true` 但 `file_requirement=None` | 补默认值 `{"type":"contract","hint":"请上传相关文件"}` |
| `sub_questions` 在 article_locate/contract_review 非空 | 强制清空为 `[]` |
| `retrieval_scope.domain` 不在枚举内 | 降级为 `civil`（最常见） |
| LLM 输出 JSON 解析失败 | 走规则候选兜底；无候选则 law_qa（confidence=0.5, fallback=True） |

---

## 9. 多轮场景处理与 Memory 结构

### 9.1 LegalMemory 结构（与 16 号文档一致）

```python
class LegalMemory:
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

> **设计原则**：`current_case` 和 `current_law` 分离。有些轮次只讨论法条不涉及案情（如"民法典第585条是什么"），有些轮次只讨论案情不引用法条（如"那我可以直接换锁吗"）。Router 据此判断是延续 law_qa 还是 case_analysis。

### 9.2 跨轮次路由示例

```text
第1轮: 用户"租房漏水房东不修"
  Router:
    history_summary: 无
    legal_memory: 无
    → LLM 判别: agent=law_qa, legal_domain="民事-合同-租赁"
    → 调度 law_qa Agent 执行
  Agent 结束后 Memory 更新:
    current_case = {"domain":"租赁纠纷","party_role":"承租人","facts":["漏水","房东不修"]}
    current_law  = {"laws":["民法典"],"articles":["第712条"],"topic":"出租人维修义务"}

第2轮: 用户"那如果我要自己修呢"（口语化，省略主语背景）
  Router:
    history_summary: "用户为房屋承租人，讨论出租人维修义务（民法典712条）"
    legal_memory: {current_case:{...}, current_law:{...}}
    → 规则候选: [{None, 0.5, "多轮延续"}]
    → LLM 结合上下文判别: agent=law_qa（延续上一轮），sub_questions=["承租人自行维修的费用如何追偿"]
    → 调度 law_qa Agent，sub_questions 传给 Retrieve 节点做多路检索
  Memory 更新:
    current_law.articles = ["第713条"]
    current_case.facts.append("用户想自行维修")

第3轮: 用户"我修了花了5000块，怎么要回来？"
  Router:
    仍延续 law_qa（current_case 仍是租赁纠纷）
    → sub_questions=["维修费用追偿程序","民法典第713条适用条件"]
  Memory 更新:
    current_case.facts.append("已维修","花费5000元")

第4轮: 用户"帮我看看这份合同有没有问题"（同时上传了 contract.pdf）
  Router:
    uploaded_files: [{doc_type:"contract"}]
    → 规则候选: [{contract_review, 0.85, "已上传合同文件"}]
    → LLM 判定: agent=contract_review（用户切换了任务，不再延续 law_qa）
    → 调度 contract_review Agent
  Memory 更新:
    current_case 重置为合同审查上下文
    current_law 清空（合同审查不预先绑定法条）
```

---

## 10. RouterDecision → Agent State 注入映射

> **关键设计**：RouterDecision 不直接作为 State，而是字段映射到 LegalAgentState，由各 Agent 节点消费。

```python
def build_initial_state(decision: RouterDecision, input: RouterInput) -> LegalAgentState:
    """Router 输出 → Agent 初始 State 映射。"""
    return LegalAgentState(
        query=input.user_query,
        conversation_id=input.conversation_id,
        user_id=input.user_id,
        tenant_id=input.tenant_id,
        kb_ids=input.available_kbs,             # kb_id 列表（Router 不绑定具体库，由 Retriever 按 retrieval_scope 过滤）

        intent=decision.task_type,              # task_type → state.intent
        legal_domain=decision.retrieval_scope.get("category", ""),
        sub_questions=decision.sub_questions,

        time_context=decision.time_context,     # 传给 HybridRetriever 影响 is_latest 过滤
        legal_context=decision.legal_context,   # law_name/article_no 传给 Retrieve 节点

        execution_mode=decision.execution_mode, # 影响 Agent 节点编排
        risk_level=decision.risk_level,         # 影响 Validate 节点是否强制 needs_human_review

        legal_memory=input.legal_memory,        # 结构化记忆直接注入
        messages=[],                            # 由 Memory 节点从 Redis 加载
        trace_id="",
    )
```

### 各 Agent 节点消费 RouterDecision 字段

| Agent 节点 | 消费的 RouterDecision 字段 | 用途 |
|-----------|--------------------------|------|
| `Retrieve` | `retrieval_scope` | 构造 filter_expr（domain/category 过滤） |
| `Retrieve` | `time_context` | 控制 `is_latest` 过滤（historical 时放开） |
| `Retrieve` | `sub_questions` | 多路检索（每个子问题独立检索后合并） |
| `Retrieve` | `legal_context.law_name` | 限定检索范围到特定法律 |
| `Tool Decide` | `execution_mode` | 判断是否需要工具（multi_step/document_analysis → 大概率需要） |
| `Validate` | `risk_level` | `high` 时强制 `needs_human_review=True` |
| `Reason` | `legal_context` | 作为推理约束（已识别 law_name=民法典，避免 LLM 跑偏到其他法律） |
| `Reason` | `legal_memory.current_case` | 结合案情背景生成更贴合的回答 |

---

## 11. 可观测性

每次路由决策写入 `router_trace`（复用 `rag_trace` 表或独立表）：

```json
{
  "trace_id": "uuid",
  "user_query": "租房漏水房东不修怎么办",
  "conversation_id": "conv-xxx",
  "history_summary_hash": "abc123",
  "legal_memory_snapshot": {
    "current_case": {...},
    "current_law": {...}
  },
  "rule_candidates": [
    {"agent":"article_locate","score":0.8,"reason":"query含法条编号"},
    {"agent":"case_analysis","score":0.7,"reason":"案例检索关键词"}
  ],
  "llm_called": true,
  "llm_raw_output": "{...}",
  "llm_latency_ms": 480,
  "final_decision": {
    "agent": "case_analysis",
    "task_type": "case_search",
    "confidence": 0.85,
    "fallback": false,
    "route_reason": "含法条编号但核心诉求是案例检索"
  },
  "total_latency_ms": 510
}
```

### 用途

- **统计 Router 准确率**：人工标注 vs 自动路由，计算准确率/召回率
- **发现 Bad Case**：`fallback=true` 频繁 → LLM Prompt 需调优；规则候选命中率低 → 规则覆盖不足
- **延迟分析**：`llm_latency_ms` 占比过高 → 考虑缩短 Prompt 或用更快的 model
- **多轮延续判定**：`legal_memory_snapshot` 用于复盘多轮路由是否正确延续

---

## 12. 文件结构

```text
agent_service/
├── router/                              # ★ Router Agent（编排层路由，非 LangGraph）
│   ├── __init__.py                      # 模块导出
│   ├── router.py                        # RouterAgent 主类（route() 入口）
│   ├── rules.py                         # 规则候选生成（ROUTER_RULES + 候选评估）
│   ├── prompt.py                        # LLM Prompt 模板（System + User + Few-Shot）
│   ├── models.py                        # RouterInput / RouterDecision / Candidate 数据结构
│   ├── fallback.py                      # 兜底策略（LLM 失败时退化到候选 score 最高）
│   └── state_mapper.py                  # build_initial_state()（RouterDecision → LegalAgentState）
```

> **文件命名**：使用下划线 `agent_service/router/`，不要创建带连字符的 `agent-service`。

### 模块职责

| 文件 | 职责 | 不做什么 |
|------|------|---------|
| `router.py` | `RouterAgent.route(input)` 主入口，编排 4 步流程 | 不实现具体规则、不实现 Prompt |
| `rules.py` | 规则定义 + 候选生成函数 | 不做最终决策 |
| `prompt.py` | System/User/Few-Shot 模板 + 变量注入 | 不调用 LLM |
| `models.py` | 数据结构定义 | 不含业务逻辑 |
| `fallback.py` | LLM 失败/低置信度兜底 | 不影响主流程 |
| `state_mapper.py` | RouterDecision → LegalAgentState 字段映射 | 不修改 RouterDecision |

---

## 13. lifespan 集成

```python
# backend/main.py startup 新增:
from agent_service.router import RouterAgent
from agent_service.memory import RedisMemory

app.state.memory = RedisMemory(redis)

# Router Agent（编排层，非 LangGraph）
app.state.router_agent = RouterAgent(
    llm=app.state.llm,                    # 复用 LLMFactory 创建的 LLM 实例
    memory=app.state.memory,
    available_kbs_loader=load_tenant_kbs, # 注入租户知识库加载器
)
```

### SSE 请求处理链

```python
# agent_service/routers/agent.py
@router.post("/chat")
async def chat(body: AgentChatRequest, current_user = Depends(get_current_user),
              router_agent = Depends(get_router_agent),
              agent_manager = Depends(get_agent_manager),
              memory = Depends(get_memory)):
    async def event_stream():
        # Step 1: 加载记忆
        legal_memory = await memory.load(body.conversation_id)
        history_summary = await memory.load_summary(body.conversation_id)
        uploaded_files = await memory.load_files(body.conversation_id)

        # Step 2: Router 决策（编排层，非 LangGraph）
        router_input = RouterInput(
            user_query=body.query,
            conversation_id=body.conversation_id,
            user_id=current_user.id,
            tenant_id=current_user.tenant_id,
            history_summary=history_summary,
            legal_memory=legal_memory,
            uploaded_files=uploaded_files,
            available_kbs=body.kb_ids or [],
        )
        decision = await router_agent.route(router_input)

        # SSE: 推送路由决策（前端展示"识别为：法律咨询"等）
        yield sse_event("router", decision.dict())

        # Step 3: 调度到对应 Agent
        agent = agent_manager.get_agent(decision.agent)
        state = build_initial_state(decision, router_input)

        # Step 4: LangGraph 流式执行
        async for event in agent.astream(state):
            yield event    # token / tool_start / tool_end / citation / done

        # Step 5: 更新 Memory（current_case/current_law）
        await memory.update(body.conversation_id, state.legal_memory)

    return EventSourceResponse(event_stream())
```

---

## 14. 配置项（backend/config.py 新增）

```python
# ========== Router Agent 配置 ==========
router_llm_temperature: float = 0.1        # 路由 LLM 温度（要稳）
router_llm_max_tokens: int = 800           # JSON 输出不需要长 token
router_llm_timeout: int = 8                # 路由超时（秒）
router_llm_retry: int = 2                  # 重试次数
router_confidence_threshold: float = 0.6   # 低于此值强制兜底到 law_qa
router_confidence_max: float = 0.95        # confidence 上限

# ========== Memory 配置 ==========
agent_memory_ttl: int = 86400              # 短期记忆 TTL（秒，默认 24h）
agent_memory_max_turns: int = 6            # 超过则触发压缩
```

---

## 15. 验证方式

```bash
# 1. 语法检查
uv run python -m compileall agent_service tests

# 2. 导入检查
uv run python -c "from agent_service.router import RouterAgent; print('import ok')"

# 3. 单元测试（建议覆盖场景）
uv run python -m unittest tests.test_router -v
# 测试用例:
# - test_single_turn_law_qa: 单轮法律咨询
# - test_article_locate_rule: 规则命中法条定位
# - test_contract_review_with_file: 已上传合同 → contract_review
# - test_contract_review_without_file: 未上传但用户要求审查 → contract_review + need_file=true
# - test_case_analysis_overrule_rule: 法条编号+案例关键词 → LLM 推翻规则走 case_analysis
# - test_multi_turn_continuation: 多轮延续（"那我自己修呢"）
# - test_high_risk_criminal: 刑事问题 → risk_level=high
# - test_document_generation_fallback: 文书生成 → 降级 law_qa
# - test_low_confidence_fallback: confidence<0.6 → fallback law_qa
# - test_llm_failure_fallback: LLM 超时 → 规则候选兜底
# - test_json_parse_failure: LLM 输出非法 JSON → 走兜底
# - test_historical_time_context: "2020年当时的规定" → time_context.historical

# 4. 启动服务测试
uv run uvicorn backend.main:app --reload --port 8000

# 5. 端到端 SSE 测试
curl -N -X POST http://localhost:8000/api/agent/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "",
    "query": "租房漏水房东不修怎么办",
    "kb_ids": ["civil_code"]
  }'
# 预期:
# data: {"event":"router","task_type":"legal_question","agent":"law_qa","confidence":0.88,...}
# data: {"event":"token","content":"根据"}
# ...
# data: {"event":"done","message_id":123}
```

---

## 16. 目标边界

### 必须完成

| # | 模块 | 说明 |
|---|------|------|
| 1 | RouterAgent 主类 | `route()` 入口，编排 4 步流程 |
| 2 | 规则候选生成 | `ROUTER_RULES` + 候选评估（不直接返回） |
| 3 | LLM Prompt 模板 | System + User + Few-Shot（7 个示例） |
| 4 | 兜底策略 | LLM 失败/低置信度/JSON 解析失败 |
| 5 | State Mapper | `build_initial_state()` RouterDecision → LegalAgentState |
| 6 | Memory 集成 | 读取 `legal_memory` + `history_summary` + `uploaded_files` |
| 7 | 可观测性 | `router_trace` 写入 + 延迟统计 |
| 8 | 单元测试 | 覆盖 12 个核心场景（见 §15） |

### 暂不强制（预留）

| # | 模块 | 阶段 |
|---|------|------|
| 1 | Router 准确率在线评估 | 阶段五（Eval Service） |
| 2 | Router Prompt A/B 测试 | 阶段五（agent_config 表配置化） |
| 3 | 多 Router 投票机制 | 阶段五（高精度场景） |
| 4 | Router 缓存（相同 query 命中缓存） | 阶段五（性能优化） |

---

## 17. 禁止事项

- **禁止 Router 调用 HybridRetriever** — Router 只决策不检索，检索由 Agent 的 Retrieve 节点负责
- **禁止 Router 调用 LLM 生成回答** — Router 只输出 RouterDecision JSON，不产生答案文本
- **禁止 Router 跳过 Memory** — 多轮场景必误判（"那我可以直接换锁吗"单看 query 无法识别意图）
- **禁止 Router 把规则预判作为最终决策** — 规则只产生候选列表（candidates），LLM 最终决策可推翻候选
- **禁止 confidence > 0.95** — 法律场景永远留兜底余地，上限 0.95
- **禁止 Router 修改数据库** — 只读 Memory，不写
- **禁止 Router 绑定具体 kb_id** — `retrieval_scope` 只给 domain/category/keywords 建议，由 Retriever 决定具体库
- **禁止 Router 放进 LangGraph 状态图** — Router 是入口控制器，单节点状态图是过度设计
- **禁止 LLM 输出非 JSON 内容** — 必须用 function calling / response_format=json_object 强制 JSON
- **禁止 sub_questions 在 article_locate/contract_review 非空** — 这两个 Agent 不做多路检索
- **禁止 risk_level=high 时不触发 needs_human_review** — 高风险必须人工审核
- **禁止 Router 调用工具** — 工具调用由 Agent 的 Tool 节点负责，Router 不感知工具存在
- **禁止修改阶段三的 `rag_service` / `embedding_service` 既有代码** — Router 通过依赖注入调用 Memory，不改检索源码
- **禁止修改 `sql/init.sql`** — 新表走 `sql/migrations/002_phase4_agent.sql` 迁移
- **不要创建带连字符的 `agent-service` 包路径** — 使用下划线 `agent_service`
