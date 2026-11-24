# 任务：LawRAG 阶段三 — Embedding 与检索（RAG 核心引擎）

## 项目背景

LawRAG 法律 RAG 平台，已完成：
- ✅ 阶段一：FastAPI 后端骨架（用户注册/登录/JWT鉴权）
- ✅ 阶段二：知识库与文档入库（OSS上传 → Parser Worker异步解析 → Chunk切分 + Metadata抽取 → knowledge_chunk 表）

现在开发 **阶段三：Embedding 与检索**。这是整个 RAG 系统的核心引擎。

---

## 核心理念：法律结构化 Chunk

### 不要做的事

- **不要用 `RecursiveCharacterTextSplitter`** — 按 token 数/字符数切分会把一条法条切成两半
- **不要让 LangChain 负责切片** — Chunk 边界应该由**法律结构**决定，不是字符数

### 正确做法

```text
PDF/Word
  ↓
MinerU（版面解析）
  ↓
Markdown
  ↓
LawParser（正则解析法律层级: 编→章→节→条）
  ↓
LawTree（建立法律树）
  ↓
ChunkGenerator（按法条边界切分，一条法条 = 一个 Chunk）
  ↓
ContextEnhancer（给每个 Chunk 补充层级上下文，增强 Embedding 效果）
  ↓
Embedding（向量化增强后的文本）
  ↓
Milvus（存入向量，metadata 保留结构化字段）
```

---

## Metadata Schema（兼容扩展）

Parser Worker 已经按以下格式生成 Chunk metadata。**阶段二已生成的 metadata 字段保持兼容，不删除、不改名；阶段三允许新增检索必需字段。**

```json
{
    "id": "LAW_000000246",
    "content": "矿藏、水流、海域属于国家所有……",
    "tenant_id": "default",
    "kb_id": "civil_code",
    "document_id": "civil_code_2025",
    "chunk_index": 246,
    "doc_type": "statute",
    "chunk_type": "law",
    "chunk_subtype": "article",
    "chunk_level": "article",
    "legal_level": "basic_law",
    "law_name": "中华人民共和国民法典",
    "law_short_name": "民法典",
    "part_no": "第二编",
    "part_title": "物权",
    "chapter_no": "第五章",
    "chapter_title": "国家所有权和集体所有权、私人所有权",
    "section_no": "第一节",
    "section_title": "国家所有权",
    "article_no": "第二百四十六条",
    "article_title": "",
    "hierarchy_path": "第二编 物权 > 第五章 国家所有权和集体所有权、私人所有权 > 第一节 国家所有权 > 第二百四十六条",
    "region": "全国",
    "version": "2025",
    "publish_date": 1590595200,
    "effective_date": 1609430400,
    "source": "中华人民共和国民法典.pdf",
    "page_start": 32,
    "page_end": 32,
    "char_start": null,
    "char_end": null,
    "keywords": ["国家所有权", "矿藏", "海域"],
    "parent_chunk_id": null,
    "is_latest": true,
    "source_uri": null,
    "extra": {}
}
```

### 阶段三新增字段说明

> **兼容原则**：阶段二已有字段不删除、不改名。以下为阶段三新增的检索必需字段。

| 字段 | 类型 | 说明 | 示例值 |
|------|------|------|--------|
| `parent_chunk_id` | string | 父级 Chunk ID，Article 指向 Section，Section 指向 Chapter，Chapter 指向 Book | `civil_code_2025:section:第二编:第五章:第一节` |
| `chunk_subtype` | string | Chunk 子类型，不改变 `chunk_type` 含义 | `article` / `case_basic_info` / `court_view` / `judgment_result` / `liability` / `payment` / `termination` / `policy_rule` |
| `is_latest` | bool | 是否最新有效版本，用于默认检索过滤 | `true` |
| `char_start` | int | PDF 页面内字符起始偏移（用于前端精确高亮），阶段二如能从 MinerU 产出则填写，否则为 `null` | `145` |
| `char_end` | int | PDF 页面内字符结束偏移，同上 | `210` |
| `source_uri` | string | 原文文件路径或 OSS key，用于前端"查看原文"链接 | `documents/civil_code/civil_code_2025.pdf` |

### 已有字段说明（阶段二产出，保持不变）

| 字段 | 类型 | 说明 | 示例值 |
|------|------|------|--------|
| `doc_type` | string | 文档类型（区别于 chunk_type 的粒度），**必填** | `statute`（法典/法律）, `regulation`（行政法规/规章）, `judicial_doc`（司法解释文件）, `case_file`（裁判文书）, `contract_doc`（合同文件）, `policy`（企业制度） |
| `legal_level` | string | 法律位阶（法律效力层级），**必填** | `constitution`, `basic_law`, `administrative_regulation`, `local_regulation`, `judicial_interpretation`, `departmental_rule` |
| `chunk_level` | string | Chunk 层级（父子 Chunk 支持），**必填** | `book`（编）, `chapter`（章）, `section`（节）, `article`（条） |
| `page_start` | int | 原文所在 PDF 起始页码，**必填** | 32 |
| `page_end` | int | 原文所在 PDF 结束页码，**必填** | 32 |

### legal_level 枚举值定义

```text
constitution              — 宪法（最高效力）
basic_law                 — 基本法律（如民法典、刑法）
administrative_regulation — 行政法规
local_regulation          — 地方性法规
judicial_interpretation   — 司法解释
departmental_rule         — 部门规章
```

> **设计原则**：`legal_level` 是 Rerank 中 `hierarchy_bonus` 的**唯一可靠来源**。禁止通过 `law_name` 字符串匹配（如 `if "中华人民共和国" in law_name`）推断法律位阶，这种规则非常脆弱。

### chunk_type / chunk_subtype / chunk_level 三字段分离

**不要让 `chunk_type` 同时表达大类和小类。** 三个字段职责明确：

```text
chunk_type:    law / judicial / case / contract / enterprise        ← 大类
chunk_subtype: article / case_basic_info / court_view / judgment_result / liability / payment / termination / policy_rule  ← 子类型
chunk_level:   book / chapter / section / article / paragraph / clause  ← 层级
```

示例：

```json
{
  "chunk_type": "case",
  "chunk_subtype": "court_view",
  "chunk_level": "paragraph"
}
```

这样 ContextEnhancer、QueryRouter、Reranker 的分发逻辑都更干净。

### 不同 chunk_type 的 Metadata 字段差异

**`chunk_type = "law"` 或 `"judicial"`**（法条/司法解释）：
- `chunk_subtype` 默认 `"article"`
- `law_name`, `law_short_name`, `part_no`, `part_title`, `chapter_no`, `chapter_title`, `section_no`, `section_title`, `article_no`, `hierarchy_path`, `version`, `effective_date`
- **新增**：`legal_level`（法律位阶）, `chunk_level`（Chunk 层级）, `page_start`, `page_end`（PDF 定位）, `parent_chunk_id`（指向父级 Section/Chapter）

**`chunk_type = "case"`**（案例）：
- `case_name`, `case_no`, `court`, `court_level`, `cause_of_action`, `judgment_date`, `judgment_type`, `dispute_focus`, `applicable_laws`
- 案例按 `chunk_subtype` 区分：`case_basic_info` / `court_view` / `judgment_result`
- **新增**：`page_start`, `page_end`（PDF 定位）

**`chunk_type = "contract"`**（合同）：
- `contract_name`, `clause_type`（party_info / liability / payment / termination / dispute 等）, `party`, `risk_type`
- **新增**：`chunk_subtype` 对应具体条款类型, `page_start`, `page_end`（PDF 定位）

**`chunk_type = "enterprise"`**（企业制度）：
- 通用字段：`title`, `category`, `department`, `keywords`
- **新增**：`chunk_subtype` 为 `policy_rule`, `page_start`, `page_end`（PDF 定位）

---

## 关键设计：父子 Chunk（Parent-Child Chunk）

### 为什么需要父子 Chunk

一条法条 = 一个 Chunk 的粒度为法条级问答（如"矿藏属于谁？"）提供了精准匹配。但法律检索中还有另一类重要查询：

> "民法典物权编关于国家所有权有哪些规定？"

这类问题需要返回的不只是第 246 条，而是整个章节的完整视图。

### 设计

通过 `chunk_level` 字段建立 Chunk 层级树。**关联关系存储在子节点**（Child → Parent），而非父节点存储 children：

```text
Chapter (parent_chunk_id="PART_02")
  ↑ parent_chunk_id
Section (parent_chunk_id="CHAPTER_005")
  ↑ parent_chunk_id
Article (parent_chunk_id="SECTION_001")
```

> **P0 设计决策：Child 存 Parent，Parent 不存 Child。**
>
> 如果 Parent 存储 `child_chunk_ids: [1,2,3,...,500]`，删除或新增一条 Article 就必须更新 Parent Chunk（含重新 Embedding）。一章 500 条 Article 时更新成本极高。
>
> 改为 Child 存储 `parent_chunk_id`，展开时用数据库查询 `WHERE parent_chunk_id = ?`。
>
> **子节点新增、删除、修改时，只重建受影响的 Parent Chain。** Parent Chunk 使用稳定 ID，可幂等 upsert。

### Parent Chunk 稳定 ID 规则

Parent Chunk ID 基于文档 + 法律层级生成，不依赖数据库自增 ID：

```text
{document_id}:book:{part_no}
{document_id}:chapter:{part_no}:{chapter_no}
{document_id}:section:{part_no}:{chapter_no}:{section_no}
{document_id}:article:{article_no}
```

例如：

```text
civil_code_2025:section:第二编:第五章:第一节
```

这样即使 Parent Chunk 被重建，ID 不变，Milvus 可以直接 upsert。

### 关键：Parent Chunk 的 content 生成策略

**Parent Chunk 的 `content` 不要直接把所有子 Chunk 全文拼接。**

原因：
- Embedding 不是越长越好。一章 40 条法条拼接后可能达 5000 token，语义严重稀释
- 长文本 Embedding 的向量表示容易发散，检索精度反而下降

正确做法：**Parent Chunk = 标题 + 规则摘要 + 子条目编号列表**

> **实现策略**：阶段三**不依赖 LLM 生成摘要**，使用规则模板生成。后续阶段四/五可引入 LLM 摘要增强。

```json
// 叶子节点 — 法条（content = 原文完整内容，parent_chunk_id 指向上级）
{
    "chunk_level": "article",
    "chunk_type": "law",
    "chunk_subtype": "article",
    "article_no": "第二百四十六条",
    "content": "矿藏、水流、海域属于国家所有……",
    "parent_chunk_id": "civil_code_2025:section:第二编:第五章:第一节"
}

// 中间节点 — 节（content = 规则摘要 + 法条编号列表，parent_chunk_id 指向上级）
{
    "chunk_level": "section",
    "chunk_type": "law",
    "chunk_subtype": null,
    "section_no": "第一节",
    "section_title": "国家所有权",
    "content": "【第一节 国家所有权】\n本节包含 12 条，主题包括：国家所有权、矿藏、水流、海域、城市土地、自然资源、国防资产。\n条文列表：第二百四十六条、第二百四十七条、第二百四十八条、第二百四十九条、第二百五十条、第二百五十一条、第二百五十二条、第二百五十三条、第二百五十四条、第二百五十五条、第二百五十六条、第二百五十七条",
    "parent_chunk_id": "civil_code_2025:chapter:第二编:第五章"
}

// 父节点 — 章（content = 标题 + 子节摘要，parent_chunk_id 指向上级）
{
    "chunk_level": "chapter",
    "chunk_type": "law",
    "chunk_subtype": null,
    "chapter_no": "第五章",
    "chapter_title": "国家所有权和集体所有权、私人所有权",
    "content": "【第五章 国家所有权和集体所有权、私人所有权】\n本章共 2 节，规定了国家所有权、集体所有权和私人所有权的范围与保护：\n第一节 国家所有权 — 矿藏、水流、海域、城市土地、森林、草原、无线电频谱、国防资产等属国家所有\n第二节 集体所有权 — 农村土地、森林、草原等属集体所有",
    "parent_chunk_id": "civil_code_2025:book:第二编"
}
```

> **注意**：Parent Chunk **不存储** `child_chunk_ids` 字段。展开子节点通过 `SELECT * WHERE parent_chunk_id = ?` 实现。

### ParentChunkBuilder — 独立的父级 Chunk 构建器（与 Parser 解耦）

Parent Chunk **不是 Parser 的职责**。Parser 只产出 Article 级 Chunk，Parent Chunk 由独立的后处理步骤生成：

```text
Parser Worker（阶段二）
  ↓
Article Chunk（chunk_level="article"）
  ↓
ParentChunkBuilder（独立后处理，阶段三）
  ↓
Section Chunk + Chapter Chunk + Book Chunk
  ↓
Embedding Worker
```

```python
class ParentChunkBuilder:
    """独立的父级 Chunk 构建器。与 Parser 解耦，负责维护 chapter/section/book 层级。

    设计原则：
    - Parser 只产出 Article（叶子节点），ParentChunkBuilder 在 Article 入 MySQL 后运行
    - 新增/删除/修改 Article 时，只重建受影响的 Parent Chain（沿 parent_chunk_id 上行）
    - Parent 不存 child_chunk_ids，子节点展开通过 SQL 查询实现
    - Parent 使用稳定 ID（基于 document_id + 层级路径），可幂等 upsert 到 MySQL 和 Milvus
    - **阶段三使用规则模板生成摘要，不依赖 LLM**
    """

    @staticmethod
    def build_parent_chunk_id(document_id: str, chunk_level: str, part_no: str = "",
                               chapter_no: str = "", section_no: str = "", article_no: str = "") -> str:
        """生成稳定的 Parent Chunk ID。
        规则: {document_id}:{chunk_level}:{part_no}:{chapter_no}:{section_no}
        示例: civil_code_2025:section:第二编:第五章:第一节
        """
        parts = [document_id, chunk_level]
        if part_no:
            parts.append(part_no)
        if chapter_no:
            parts.append(chapter_no)
        if section_no:
            parts.append(section_no)
        return ":".join(parts)

    async def build_for_document(self, db: AsyncSession, document_id: str) -> int:
        """为整份文档构建所有父级 Chunk。返回生成的 Parent Chunk 数量。
        流程:
        1. 查询该 document 所有 chunk_level="article" 的 Chunk
        2. 按 section_no 分组 → 生成 Section Parent Chunk（每个 Section 一条）
        3. 按 chapter_no 分组 → 生成 Chapter Parent Chunk（每个 Chapter 一条）
        4. 按 part_no 分组 → 生成 Book Parent Chunk（如有）
        5. 批量 INSERT INTO knowledge_chunk（parent_chunk_id 使用稳定 ID，支持 ON DUPLICATE KEY UPDATE）
        6. 将 Parent Chunk 入队 Embedding Worker
        """

    async def rebuild_for_articles(self, db: AsyncSession, article_chunk_ids: list[str]) -> int:
        """增量重建：新增/修改/删除 Article 后，只重建受影响的 Parent Chain。
        1. 根据 article_chunk_ids 找到所有受影响的 section_no / chapter_no / part_no
        2. 删除旧的对应 Parent Chunk（含 Milvus 向量）
        3. 重新生成并 Embedding（使用相同稳定 ID，幂等 upsert）
        """

    def generate_section_content(self, section_meta: dict, child_articles: list[dict]) -> str:
        """规则模板生成（不使用 LLM）:
        【{section_no} {section_title}】
        本节包含 {N} 条，主题包括：{从 article 内容提取前 10 字形成主题列表}。
        条文列表：{所有 article_no 逗号连接}
        """

    def generate_chapter_content(self, chapter_meta: dict, child_sections: list[dict]) -> str:
        """规则模板生成（不使用 LLM）:
        【{chapter_no} {chapter_title}】
        本章共 {N} 节，规定了{子节主题概括}：
        第一节 {section_title} — {section 内容中提取的首句}
        第二节 {section_title} — {section 内容中提取的首句}
        """
```

> **设计原则**：Parent Chunk 的 `content` 是为了让 Embedding 能够**检索到**这个章节，不是代替原文。真正生成回答时，根据 Child 的 `parent_chunk_id` 逐级向上展开，取出子 Chunk 的完整原文。

---

## 关键设计：版本管理

### 版本字段不再只靠 metadata

`knowledge_document` 表增加版本管理字段：

```sql
version                   VARCHAR(20)   -- 版本号（如 "2020", "2025"）
effective_date            INT           -- 生效日期 Unix 时间戳
is_latest                 TINYINT(1)    -- 是否最新有效版本
superseded_by_document_id BIGINT        -- 被哪个文档替代
```

### 默认检索过滤

```text
is_latest == True
```

只返回最新有效版本。用户显式查历史版本时才放开：

```text
version = "2020"
```

### Rerank 中的时效性加权

```text
latest_bonus         — is_latest == True 加 0.05
effective_date_bonus — 生效日期越新，加分越高
legal_level_bonus    — 原有法律位阶加分
```

> **注意**：法律问题不一定永远最新优先。例如 "2020 年当时如何规定？" 必须走历史版本。
> QueryRouter 检测到时间关键词（"当时"、"旧法"、"原规定"、"X 年版"）时，
> 移除 `is_latest` 过滤，改为 `version` 精确匹配。

---

## 关键设计：检索链路

### 阶段三闭环（先做这个）

```text
query
  ↓
RuleQueryRewriter（规则+词典）
  ↓
QueryRouter（意图路由）
  ↓
BM25 Top15 + Milvus Top15
  ↓
RRF Merge Top50
  ↓
RuleLegalReranker Top8
  ↓
CitationBuilder
  ↓
ContextBuilder
```

> **Cross-Encoder Reranker 可以先留接口**，不作为阶段三硬依赖。阶段三用规则 Reranker 完成闭环，阶段四再接入 BGE-Reranker / Cohere。

### RRF 融合

```text
RRF_score = Σ w_i / (60 + rank_i)
```

权重从 QueryRouter 获取（非硬编码）。

### Rerank 分数公式

```text
final_score =
  0.45 * semantic_score
+ 0.30 * bm25_score
+ 0.10 * legal_level_bonus
+ 0.10 * chunk_level_bonus
+ 0.05 * freshness_bonus
```

不同 intent 可调整各维度权重，阶段三先用统一公式。

---

### 检索策略

| 查询类型 | 检索目标 chunk_level | 说明 |
|---------|---------------------|------|
| 法条定位（"民法典第246条"） | `article` | 精准匹配法条编号 |
| 主题问答（"矿藏属于谁"） | `article` | 语义匹配法条内容 |
| 章节总结（"物权编国家所有权有哪些规定"） | `chapter` / `section` | 返回章节级 Chunk，避免返回碎片化的多条法条让 LLM 自己拼凑 |
| 体系概览（"民法典物权编结构"） | `book` / `chapter` | 返回编/章级 Chunk |

### 与 ContextEnhancer 的关系

- **父级 Chunk（chapter/section/book）**：`content` 已经是结构化的标题+摘要+列表，Embedding 时**直接使用 `content` 原文**，不经过 ContextEnhancer
- **叶子 Chunk（article）**：Embedding 时需要 ContextEnhancer 补充父级上下文（law_name → part → chapter → section → article_no），因为叶子节点的 `content` 缺少层级归属信息
- 父级 Chunk 的 `chunk_level` 字段可用于 Rerank 策略：用户问章节级问题时，提升 `chunk_level=chapter/section` 的权重

### 检索后的展开策略

检索到父级 Chunk 后，通过 `parent_chunk_id` 向下展开（而非读取不存在的 `child_chunk_ids`）：

```
1. 检索命中 chapter Chunk（如"国家所有权和集体所有权"）
2. SELECT * FROM knowledge_chunk WHERE parent_chunk_id = chapter.chunk_id
   → 获取所有 Section Chunk
3. 对每个 Section: SELECT * WHERE parent_chunk_id = section.chunk_id
   → 获取所有 Article Chunk
4. 将完整的 Article 原文送入 Context Builder → LLM 生成
```

这样既保证了 Embedding 质量（精简摘要），又保证了回答质量（完整原文）。

---

## 关键设计：ContextEnhancer（上下文增强）

**Embedding 用的文本** 不等于 **展示给用户的原文**。

Embedding 用的文本需要补充层级上下文，让向量携带更多语义信息：

```
原文 (metadata.content):
    矿藏、水流、海域属于国家所有……

增强后 (embedding 用):
    【中华人民共和国民法典】
    【第二编 物权】
    【第五章 国家所有权和集体所有权、私人所有权】
    【第一节 国家所有权】
    【第二百四十六条】
    矿藏、水流、海域属于国家所有……
```

- **Embedding 文本**：增强后的内容 → 送入 Embedding 模型 → 写入 Milvus 的 `embedding` 字段
- **展示文本**：`metadata.content` 原文 → 存入 `knowledge_chunk.text`
- **结构化信息**：metadata 的其余字段 → MySQL 为权威来源；Milvus 只存检索过滤必需的标量字段（chunk_type, chunk_level, legal_level, is_latest 等）

---

## 现有代码上下文

### 已完成的表和关键字段

```
knowledge_chunk: id, document_id, kb_id, chunk_index, parent_chunk_id, chunk_type, chunk_level, chunk_subtype, text(原文), token_count, vector_id(NULL), metadata(JSON), created_at
knowledge_document: ... version, effective_date, is_latest, superseded_by_document_id, embedding_status(pending/processing/completed/partial_failed/failed), embedding_count, embedding_failed_count
knowledge_base: ... embedding_model, rerank_model
rag_trace: 完整检索链路记录
task_log: 异步任务日志（阶段二已在用）
```

### 已有基础设施

```python
# config.py
settings.mysql_url / settings.redis_url

# database.py
get_db() → AsyncSession
get_redis() → Redis | None

# main.py
app.state.oss = OSSClient(...)

# worker/task_queue.py
class TaskQueue:    # Redis Stream
    enqueue(stream, task) → msg_id
    consume(stream, group, consumer, block_ms) → [(msg_id, dict)]
    ack(stream, group, msg_id)

# 已有 Stream Key
DOCUMENT_PARSE_STREAM = "lawrag:stream:document_parse"  # 阶段二

# 阶段三新增
CHUNK_EMBEDDING_STREAM = "lawrag:stream:chunk_embedding"
```

---

## 需要新增/修改的文件

```
rag_service/
├── retrieval/
│   ├── __init__.py              # 阶段三 RAG 检索核心包
│   ├── models.py                # 阶段三内部 DTO（RewriteResult / QueryIntent / RetrievalResult / ChunkHit / ContextResult / Citation）
│   ├── dependencies.py          # 检索运行态依赖注入
│   ├── parent_chunk.py          # 父级 Chunk 构建器（规则摘要）
│   ├── milvus_client.py         # Milvus 客户端封装
│   ├── tokenizer.py             # 分词器抽象层（BaseTokenizer / JiebaTokenizer / HanLPTokenizer）
│   ├── bm25.py                  # BM25 关键词检索引擎（MVP）
│   ├── query_rewrite.py         # Query Rewrite 查询重写
│   ├── query_router.py          # Query Router 意图路由
│   ├── retriever.py             # 混合检索编排
│   ├── reranker.py              # Rerank 精排（阶段三：规则版）
│   ├── context_builder.py       # Prompt Context 构建器
│   └── citation.py              # 引用构建
├── routers/
│   └── retrieval.py             # 检索调试接口（Retrieval Lab）
└── schemas/
    └── retrieval.py             # 检索请求/响应 schema

embedding_service/
├── embedding/
│   ├── context_enhancer.py      # 上下文增强器（生成 embedding_text）
│   ├── embedding.py             # Embedding 模型抽象层
│   └── embedding_cache.py       # Embedding 去重缓存（SHA256 → Redis）
├── services/
│   └── embedding.py             # Embedding 业务逻辑编排
└── worker/
    └── embedding.py             # Embedding Worker 独立进程
```

> 服务边界：`rag_service` 只放 RAG 检索链路代码；`embedding_service` 只放向量化、增强文本、Embedding 缓存与 Worker 代码。`backend/` 保留通用后端骨架、用户、知识库、文档入库、数据库模型、中间件、OSS 与 Parser Worker 等基础能力。

### rag_service/retrieval/models.py — 阶段三内部 DTO

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class RewriteResult:
    original_query: str
    legal_query: str
    keyword_query: str
    entity_list: list[str] = field(default_factory=list)

@dataclass
class QueryIntent:
    intent_type: str                                    # article_lookup / law_qa / case_analysis / contract_review / chapter_summary
    weights: dict[str, float] = field(default_factory=dict)       # RRF 权重
    rerank_weights: dict[str, float] = field(default_factory=dict) # Rerank 权重

@dataclass
class ChunkHit:
    chunk_id: str
    text: str
    bm25_score: Optional[float] = None
    milvus_score: Optional[float] = None
    final_score: float = 0.0
    metadata: dict = field(default_factory=dict)

@dataclass
class RetrievalResult:
    chunks: list[ChunkHit]
    citations: list[dict]
    trace: dict = field(default_factory=dict)

@dataclass
class ContextResult:
    context_text: str
    citation_map: dict[int, dict]
    token_count: int
    chunk_count: int

@dataclass
class Citation:
    chunk_id: str
    law_name: Optional[str]
    article_no: Optional[str]
    hierarchy_path: Optional[str]
    text: str
    score: float
    version: Optional[str]
    effective_date: Optional[int]
    page_start: Optional[int]
    page_end: Optional[int]
    char_start: Optional[int]
    char_end: Optional[int]
    source_uri: Optional[str]
```

> 避免 schema 和内部对象混在一起。`rag_service/retrieval/models.py` 放阶段三内部 DTO，`rag_service/schemas/retrieval.py` 放 API 请求/响应 Pydantic schema。

---

## 各文件详细要求

### 1. embedding_service/embedding/context_enhancer.py — 上下文增强器（是核心）

```python
from abc import ABC, abstractmethod

# ========== 策略模式：每种 chunk_type 一个 Enhancer ==========

class BaseEnhancer(ABC):
    """上下文增强器抽象基类。每种 chunk_type 独立实现，通过注册表分发。

    不在一个类里写 if-else 判断 chunk_type，否则后续增加 Patent/Medical/Policy
    等新类型时，ContextEnhancer 会膨胀到上千行。
    """

    @abstractmethod
    async def enhance(self, metadata: dict) -> str:
        """根据 metadata 生成增强后的 Embedding 文本"""

    @property
    @abstractmethod
    def chunk_type(self) -> str:
        """该增强器对应的 chunk_type"""

class LawEnhancer(BaseEnhancer):
    """法条/司法解释增强器。

    原始 content: "矿藏、水流、海域属于国家所有……"
    增强后文本:
        【中华人民共和国民法典】
        【第二编 物权】
        【第五章 国家所有权和集体所有权、私人所有权】
        【第一节 国家所有权】
        【第二百四十六条】
        矿藏、水流、海域属于国家所有……
    """
    chunk_type = "law"

    async def enhance(self, metadata: dict) -> str:
        """逐级叠加: law_name → part_no+part_title → chapter_no+chapter_title
                   → section_no+section_title(如有) → article_no → content"""
        ...

class JudicialEnhancer(LawEnhancer):
    """司法解释增强器（结构与 law 相同，继承 LawEnhancer）"""
    chunk_type = "judicial"

class CaseEnhancer(BaseEnhancer):
    """案例增强器。

    策略: case_name + court + cause_of_action + judgment_date + content 前200字
    """
    chunk_type = "case"

    async def enhance(self, metadata: dict) -> str:
        ...

class ContractEnhancer(BaseEnhancer):
    """合同增强器。

    策略: contract_name + clause_type中文名 + content
    """
    chunk_type = "contract"

    async def enhance(self, metadata: dict) -> str:
        ...

class EnterpriseEnhancer(BaseEnhancer):
    """企业制度增强器。

    策略: title + keywords + content 前200字
    """
    chunk_type = "enterprise"

    async def enhance(self, metadata: dict) -> str:
        ...


# ========== 注册表 + 门面 ==========

class ContextEnhancer:
    """上下文增强器门面。根据 chunk_type 自动路由到对应的 Enhancer 实现。

    不写 if chunk_type == "law": ... elif chunk_type == "case": ...
    而是通过注册表分发，新增 chunk_type 只需注册新的 Enhancer。
    """

    def __init__(self):
        self._registry: dict[str, BaseEnhancer] = {}

    def register(self, enhancer: BaseEnhancer) -> None:
        self._registry[enhancer.chunk_type] = enhancer

    def enhance(self, metadata: dict) -> str:
        enhancer = self._registry.get(metadata.get("chunk_type", ""))
        if enhancer is None:
            return metadata.get("content", "")  # fallback: 直接返回原文
        return enhancer.enhance(metadata)

    def enhance_batch(self, chunks: list[dict]) -> list[str]:
        """批量增强，返回 embedding_texts 列表"""
        return [self.enhance(c) for c in chunks]

# 初始化默认注册
context_enhancer = ContextEnhancer()
context_enhancer.register(LawEnhancer())
context_enhancer.register(JudicialEnhancer())
context_enhancer.register(CaseEnhancer())
context_enhancer.register(ContractEnhancer())
context_enhancer.register(EnterpriseEnhancer())
```

要求：
- 核心原则：**Embedding 文本 ≠ 展示文本**
- 增强后的文本只用于 `embed()` 调用，不存回 MySQL，不替代 `text` 字段
- 每个 chunk_type 有独立的增强策略
- 增强后的文本写入 `rag_trace` 全链路 trace 中供调试查看（Milvus 精简模式下不单独存储 enhanced_text 字段）
- **Token 长度控制**：增强后的文本总 token 数不得超过 Embedding 模型的 `max_tokens` 上限
  - `text-embedding-3-small`: 8191 token — 基本安全
  - `BGE-large-zh-v1.5`: **512 token** — 极易截断，必须控制
  - 实现：`ContextEnhancer` 内部集成 token 计数（使用 tiktoken 或模型对应 tokenizer），超过阈值时自动压缩：优先保留 `law_name` + `article_no` + 原文 `content`，裁剪中间层级（如省略 `section_title`）
  - 配置项：`max_embedding_tokens`（默认 500，BGE 安全值）
- **父级 Chunk 跳过增强**：`chunk_level=chapter/section/book` 的 Chunk 不需要 ContextEnhancer（其 content 已包含完整上下文，再叠加会重复）

### 2. embedding_service/embedding/embedding.py — Embedding 模型抽象层

```python
from abc import ABC, abstractmethod

class BaseEmbedding(ABC):
    """Embedding 模型抽象基类"""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """将文本列表转为向量列表"""

    @property
    @abstractmethod
    def dimension(self) -> int: ...

    @property
    @abstractmethod
    def model_name(self) -> str: ...

class OpenAIEmbedding(BaseEmbedding):
    """OpenAI text-embedding-3-large (dim=3072) 或 text-embedding-3-small (dim=1536)"""

class BGEEmbedding(BaseEmbedding):
    """BGE-large-zh-v1.5 (dim=1024)，通过 HTTP API 调用本地 TEI 服务"""

class DeepSeekEmbedding(BaseEmbedding):
    """DeepSeek Embedding API，兼容 OpenAI 接口"""

class QwenEmbedding(BaseEmbedding):
    """通义千问 Embedding（如 text-embedding-v4），法律中文效果优秀，兼容 OpenAI 接口"""

class EmbeddingFactory:
    """Embedding 工厂 — 注册表模式。新增 provider 只需 register，不修改 create()。

    不使用 if provider == "openai": ... elif provider == "qwen": ...
    否则以后增加 Voyage / M3E / Nomic / Jina 每次都要改代码。
    """

    _registry: dict[str, type[BaseEmbedding]] = {}

    @classmethod
    def register(cls, provider: str, embedding_cls: type[BaseEmbedding]) -> None:
        cls._registry[provider] = embedding_cls

    @classmethod
    def create(cls, provider: str, model_name: str, api_base: str | None, api_key: str | None) -> BaseEmbedding:
        if provider not in cls._registry:
            raise ValueError(f"Unknown embedding provider: {provider}. Registered: {list(cls._registry.keys())}")
        return cls._registry[provider](model_name=model_name, api_base=api_base, api_key=api_key)

# 注册内置 provider
EmbeddingFactory.register("openai", OpenAIEmbedding)
EmbeddingFactory.register("bge", BGEEmbedding)
EmbeddingFactory.register("deepseek", DeepSeekEmbedding)
EmbeddingFactory.register("qwen", QwenEmbedding)
# 后续新增 Voyage / M3E / Nomic / Jina 等只需一行 register 调用
```

要求：
- `embed()` 内部自动分批（单次最多 100 条）
- 失败重试 3 次，指数退避 1s/2s/4s
- 调用的是**增强后的文本**（由 ContextEnhancer 生成），不是原始 content

### 2.5 embedding_service/embedding/embedding_cache.py — Embedding 去重缓存

```python
import hashlib
from typing import Optional
from enum import Enum

class CacheScope(str, Enum):
    TENANT = "tenant"    # 租户隔离（默认）
    GLOBAL = "global"    # 跨租户共享（公共法律库可配置）

class EmbeddingCache:
    """基于 SHA256 的 Embedding 去重缓存。

    场景：重新上传同一份《民法典》PDF，Parser 产出的 Chunk 内容没变，
    但 Embedding Worker 会重新调用 Embedding API。
    Embedding 是 RAG 中最贵的操作，应该跳过重复计算。

    缓存 Key 设计（必须包含 tenant_id + provider + model + dimension + enhanced_text）:
      key = SHA256(f"{tenant_id}:{provider}:{model}:{dimension}:{enhanced_text}")

    如果只 Hash 文本，换模型（如 text-embedding-3-small→BGE）时
    Redis 会命中旧缓存，导致维度不匹配（1536 vs 1024）崩溃。
    """

    def __init__(self, redis: "Redis", scope: CacheScope = CacheScope.TENANT):
        self.redis = redis
        self.scope = scope
        self.prefix = "lawrag:embed_cache:"

    def compute_hash(self, enhanced_text: str, tenant_id: str, provider: str,
                     model: str, dimension: int) -> str:
        """计算缓存 key 的 SHA256。
        key = tenant_id:provider:model:dimension:enhanced_text
        不同 tenant / provider / model / dimension 组合的相同文本有不同缓存 key。

        如果 scope=GLOBAL，tenant_id 部分使用固定值 "_global_"。
        """
        tid = "_global_" if self.scope == CacheScope.GLOBAL else tenant_id
        key = f"{tid}:{provider}:{model}:{dimension}:{enhanced_text}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def _redis_key(self, content_hash: str) -> str:
        return f"{self.prefix}{content_hash}"

    async def get(self, content_hash: str) -> Optional[list[float]]:
        """从 Redis 读取缓存向量"""

    async def set(self, content_hash: str, vector: list[float], ttl: int = 86400 * 30) -> None:
        """写入 Redis 缓存，默认 TTL=30 天"""

    async def batch_get(self, hashes: list[str]) -> dict[str, Optional[list[float]]]:
        """批量读取，返回 {hash: vector_or_None}"""

    async def batch_set(self, hash_vector_map: dict[str, list[float]]) -> None:
        """批量写入"""
```

Embedding Worker 集成流程：

```python
# 在 embedding worker 中：
cache = EmbeddingCache(redis, scope=CacheScope.TENANT)
hashes = [cache.compute_hash(t, tenant_id="default", provider="openai",
          model="text-embedding-3-small", dimension=1536)
          for t in enhanced_texts]
cached = await cache.batch_get(hashes)

# 缓存命中的直接使用，未命中的调用 API
to_embed = [(i, t) for i, (t, h) in enumerate(zip(enhanced_texts, hashes)) if h not in cached]
if to_embed:
    indices, texts = zip(*to_embed)
    new_vectors = await embedding.embed(list(texts))
    new_cache = {hashes[i]: v for i, v in zip(indices, new_vectors)}
    await cache.batch_set(new_cache)
```

### Embedding 缓存与文档生命周期的解耦

> **删除文档时：删除 Milvus 向量 + 清空 `knowledge_chunk.vector_id`，但不删除 Embedding 缓存。**
>
> 缓存是可复用资产，不应跟文档生命周期绑定。重新上传同一份文件时，缓存仍能命中。

```text
delete_document(doc_id):
  1. 按 chunk_ids 删除 Milvus 向量
  2. UPDATE knowledge_chunk SET vector_id = NULL WHERE document_id = doc_id
  3. 不删除 Redis embedding cache
```

### 3. rag_service/retrieval/milvus_client.py — Milvus 客户端

```python
from pymilvus import MilvusClient

class MilvusStore:
    """Milvus 向量数据库封装"""

    def __init__(self, host: str = "localhost", port: int = 19530):
        self.client = MilvusClient(uri=f"http://{host}:{port}")

    def init_collection(self, embedding_dim: int) -> None:
        """创建单一 Collection: lawrag_chunks

        设计决策：**初期使用 1 个 Collection，不做 5 个 Collection 拆分**。

        理由：
        - 当前数据量预估几十万 Chunk，一个 Collection 完全够用
        - 跨类型查询（如"公司合同违约怎么办？"需要同时查 contract + law + judicial）只需一次 search
        - 单一 Embedding Space，RRF 融合更简单
        - 后续扩展容易：数据量超 5000 万 Chunk 后再考虑按 chunk_type 拆分

        **Milvus 标量字段精简原则**：Milvus 不要塞太多复杂 metadata。
        完整 metadata 以 MySQL 为准。Milvus 只保留检索必需的过滤字段。

        Schema（精简后）:
          - id: INT64 (primary, auto_id)
          - embedding: FLOAT_VECTOR(dim=embedding_dim)
          - chunk_id: VARCHAR(128)        # MySQL knowledge_chunk.id，检索后回查 MySQL
          - tenant_id: VARCHAR(50)         # 租户隔离
          - kb_id: VARCHAR(100)            # 知识库 ID
          - document_id: VARCHAR(100)      # 文档 ID
          - doc_type: VARCHAR(30)          # statute / regulation / judicial_doc / case_file / contract_doc / policy
          - chunk_type: VARCHAR(30)        # law / judicial / case / contract / enterprise
          - chunk_subtype: VARCHAR(64)     # article / case_basic_info / court_view / judgment_result / liability / payment / termination / policy_rule
          - chunk_level: VARCHAR(20)       # book / chapter / section / article / paragraph / clause
          - legal_level: VARCHAR(40)       # constitution / basic_law / administrative_regulation / local_regulation / judicial_interpretation / departmental_rule
          - version: VARCHAR(20)           # 版本号（如 "2020", "2025"）
          - is_latest: BOOL                # 是否为最新版本
          - page_start: INT32              # PDF 起始页码
          - page_end: INT32                # PDF 结束页码
          - content_hash: VARCHAR(96)      # SHA256(tenant_id:provider:model:dimension:enhanced_text)，Embedding 去重缓存

        可选保留（检索过滤常用）:
          - law_name: VARCHAR(200)         # 法律名称
          - article_no: VARCHAR(20)        # 法条编号

        检索流程：
          Milvus TopK 命中 → 取 chunk_id 列表
                ↓
          MySQL 批量回查 knowledge_chunk（WHERE chunk_id IN (...)）
                ↓
          组装完整 metadata / citation / context

        索引: HNSW, metric_type=COSINE
        """

    def insert(self, vectors: list[dict]) -> list[str]:
        """批量插入。每批 ≤1000 条，返回 ID 列表"""

    def upsert(self, vectors: list[dict]) -> list[str]:
        """幂等 upsert（按 chunk_id 去重）。用于 Parent Chunk 重建场景"""

    def search(
        self,
        query_vector: list[float],
        top_k: int = 20,
        filter_expr: str | None = None,
        output_fields: list[str] | None = None
    ) -> list[dict]:
        """向量检索。

        典型 filter_expr 示例:
        - 按知识库过滤: kb_id in ["civil_code", "contract_law"]
        - 按 chunk_type 过滤: chunk_type in ["law", "case"]
        - 按版本过滤: is_latest == True
        - 按 chunk_level 过滤: chunk_level == "article"
        - 组合: kb_id in ["civil_code"] and chunk_type == "law" and is_latest == True
        """

    def delete_by_chunk_ids(self, chunk_ids: list[str]) -> None: ...
    def flush(self) -> None: ...
```

要求：
- `init_collection()` 幂等（已存在则跳过）
- `search()` 返回 `[{id, distance, entity: {chunk_id, kb_id, document_id, chunk_type, chunk_level, ...}}, ...]`
- 标量过滤格式：`kb_id in ["civil_code", "contract_law"]`
- insert 后自动 flush
- **不再区分 Collection**，所有查询通过 `filter_expr` 中的 `chunk_type` / `chunk_level` 字段过滤
- **Milvus 返回后通过 MySQL 批量回查补充完整 metadata**，不要把完整 JSON 塞进 Milvus

### 4. rag_service/retrieval/bm25.py — BM25 关键词检索（MVP）

> **BM25Retriever 为单机 MVP 实现**，支持索引持久化加载。
> 当 API 多进程或百万级 Chunk 时迁移 Elasticsearch。

> Tokenizer 实现放在独立文件 `rag_service/retrieval/tokenizer.py`，`bm25.py` 通过 `from .tokenizer import BaseTokenizer, JiebaTokenizer` 引用。

```python
from abc import ABC, abstractmethod
from rank_bm25 import BM25Okapi
from .tokenizer import BaseTokenizer, JiebaTokenizer

# ========== BM25 检索引擎 ==========

class BM25Retriever:
    """BM25 关键词检索，支持索引持久化，初期不做 ES"""

    def __init__(self, tokenizer: BaseTokenizer | None = None):
        self.tokenizer = tokenizer or JiebaTokenizer()

    async def build_index(self, chunks: list[dict]) -> None:
        """构建索引。chunks: [{chunk_id, text, kb_id, ...}]"""

    async def search(
        self, query: str, top_k: int = 20,
        filter_kb_ids: list[str] | None = None
    ) -> list[dict]: ...

    async def rebuild_all(self, db: AsyncSession) -> None:
        """启动时从 MySQL 全量重建索引"""

    # ========== 索引持久化 ==========

    async def save(self, path: str = "storage/bm25/bm25_index.pkl") -> None:
        """持久化 BM25 索引到磁盘（pickle），避免重启后全量重建"""

    async def load(self, path: str = "storage/bm25/bm25_index.pkl") -> bool:
        """从磁盘加载 BM25 索引。返回 True 表示加载成功，False 表示文件不存在需重建"""

    async def append_chunks(self, new_chunks: list[dict]) -> None:
        """增量追加新 Chunk 到已有索引（Embedding Worker 完成后调用）"""
```

### BM25 启动与增量更新流程

```text
API startup:
  1. load() 已有索引文件 → 成功则跳过重建
  2. load() 失败 → rebuild_all() 从 MySQL 全量构建 → save()

Embedding Worker 成功后:
  append_chunks(new_chunks) → 增量写入 → save()

调试接口:
  POST /api/retrieve/bm25/reload → 手动触发全量重建
```

要求：
- **Tokenizer 抽象**：`BM25Retriever` 接受 `BaseTokenizer` 注入，默认用 `JiebaTokenizer`
- jieba 精确模式 + 法律自定义词典（`dict_path` 可配置）
- 后续可替换为 HanLP / pkuseg 等分词器，BM25 逻辑不变
- 内存索引用 `asyncio.to_thread` 包装
- 支持按 kb_id 过滤
- **索引持久化**：
  - 启动时优先 `load()` 已有索引文件，没有则 `rebuild_all()` 并 `save()`
  - 法律库几十万条数据全量重建耗时长，持久化是关键性能优化
  - 存储路径：`storage/bm25/`，按知识库分文件（如 `civil_code.pkl`, `contract.pkl`）
  - Embedding Worker 完成新文档处理后调用 `append_chunks()` 增量更新，并触发 `save()`
- **多进程注意事项**：当前为单机单进程 MVP。多进程部署时各进程独立维护 BM25 索引会导致不一致，届时迁移 Elasticsearch
- **备选方案**：百万级 Chunk 后迁移到 SQLite/Whoosh（比 pickle 恢复快一个数量级，且支持增量写入），最终方案是 Elasticsearch（阶段六）

### 5. rag_service/retrieval/reranker.py — Rerank 精排（法律特化加权）

> **阶段三**：使用 `RuleLegalReranker`（规则加权 + BM25 分数融合），完成闭环。
> **阶段四**：接入 Cross-Encoder（BGE-Reranker / Cohere），替换 `semantic_score` 来源。

```python
from abc import ABC, abstractmethod

# ========== 可插拔打分组件 ==========

class BaseScorer(ABC):
    """单个打分维度基类。每个维度独立计算、独立测试、独立替换。"""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def score(self, candidate: dict, context: dict) -> float:
        """返回 0~1 之间的分数。context 包含 query 等公共上下文。"""

class SemanticScorer(BaseScorer):
    """Milvus 余弦相似度分（阶段三）。
    阶段四替换为 Cross-encoder: BGE-Reranker / Cohere Rerank API
    """
    name = "semantic"

    def score(self, candidate: dict, context: dict) -> float:
        """将 Milvus 返回的 cosine distance 归一化到 0~1"""
        distance = candidate.get("milvus_distance", 0)
        return max(0.0, 1.0 - distance)

class BM25Scorer(BaseScorer):
    """BM25 关键词匹配分（阶段三新增）"""
    name = "bm25"

    def score(self, candidate: dict, context: dict) -> float:
        bm25_score = candidate.get("bm25_score", 0)
        return min(1.0, bm25_score)

class LegalLevelScorer(BaseScorer):
    """法律位阶加分（来源: metadata.legal_level，固定查表，不做字符串推断）"""
    name = "legal_level"

    LEVEL_MAP = {
        "constitution": 1.0,
        "basic_law": 1.0,
        "administrative_regulation": 0.8,
        "judicial_interpretation": 0.7,
        "local_regulation": 0.65,
        "departmental_rule": 0.6,
    }

    def score(self, candidate: dict, context: dict) -> float:
        legal_level = candidate.get("legal_level", "")
        return self.LEVEL_MAP.get(legal_level, 0.5)

class ChunkLevelScorer(BaseScorer):
    """Chunk 层级加分（阶段三新增）。
    article 级精确匹配权重大于 chapter/section 级概览
    """
    name = "chunk_level"

    LEVEL_MAP = {
        "article": 1.0,
        "clause": 0.95,
        "paragraph": 0.9,
        "section": 0.7,
        "chapter": 0.5,
        "book": 0.3,
    }

    def score(self, candidate: dict, context: dict) -> float:
        chunk_level = candidate.get("chunk_level", "")
        return self.LEVEL_MAP.get(chunk_level, 0.5)

class FreshnessScorer(BaseScorer):
    """时效性加分"""
    name = "freshness"

    def score(self, candidate: dict, context: dict) -> float:
        effective_date = candidate.get("effective_date", 0)
        is_latest = candidate.get("is_latest", False)
        if is_latest:
            return 1.0
        if not effective_date:
            return 0.5
        # 根据生效日期距今的时间衰减
        ...

class KeywordMatchScorer(BaseScorer):
    """关键词匹配加分"""
    name = "keyword"

    def score(self, candidate: dict, context: dict) -> float:
        query_keywords = context.get("query_keywords", [])
        chunk_keywords = candidate.get("keywords", [])
        if not query_keywords or not chunk_keywords:
            return 0.5
        overlap = len(set(query_keywords) & set(chunk_keywords))
        return min(1.0, overlap / max(len(query_keywords), 1))


# ========== 可配置的打分流水线 ==========

class ScorePipeline:
    """按序执行 scorer 列表，加权组合。新增维度只需 add_scorer，不修改现有代码。"""

    def __init__(self):
        self._scorers: list[tuple[BaseScorer, float]] = []  # (scorer, weight)

    def add_scorer(self, scorer: BaseScorer, weight: float) -> "ScorePipeline":
        self._scorers.append((scorer, weight))
        return self

    def compute_final_score(self, candidate: dict, context: dict) -> float:
        total = 0.0
        for scorer, weight in self._scorers:
            total += weight * scorer.score(candidate, context)
        return total


class RuleLegalReranker:
    """阶段三规则 Reranker。组合 BM25 + semantic + legal 特化维度。

    不依赖 Cross-Encoder API，完成独立闭环。
    阶段四替换为 CrossEncoderReranker 接入 BGE-Reranker / Cohere。
    """

    def __init__(self, pipeline: ScorePipeline):
        self.pipeline = pipeline

    async def rerank(
        self, query: str, candidates: list[dict],
        top_k: int = 8
    ) -> list[dict]:
        """
        1. 对每个 candidate 计算 pipeline 加权总分
        2. 排序返回 TopK
        """
```

### 阶段三默认 Pipeline 配置

```python
# 阶段三默认 pipeline（包含 BM25 分数）
pipeline = (ScorePipeline()
    .add_scorer(SemanticScorer(),   0.45)   # Milvus 相似度
    .add_scorer(BM25Scorer(),       0.30)   # BM25 关键词分
    .add_scorer(LegalLevelScorer(), 0.10)   # 法律位阶
    .add_scorer(ChunkLevelScorer(), 0.10)   # Chunk 层级
    .add_scorer(FreshnessScorer(),  0.05)   # 时效性
)

# 最终公式对应:
# final_score = 0.45 * semantic + 0.30 * bm25 + 0.10 * legal_level + 0.10 * chunk_level + 0.05 * freshness
```

> **不同 intent 可调整权重**，但阶段三先用统一公式，避免过早优化。
> **禁止通过 law_name 字符串匹配推断 legal_level**（如 `if "中华人民共和国" in law_name`），
> 这种规则脆弱且不可维护。`LegalLevelScorer` 只从 `metadata.legal_level` 查表。

### 6. rag_service/retrieval/query_rewrite.py — Query Rewrite（查询重写）

```python
from abc import ABC, abstractmethod

# ========== 抽象基类 ==========

class BaseQueryRewriter(ABC):
    """Query Rewrite 抽象基类。不同实现通过多态切换，Retriever 只依赖接口。"""

    @abstractmethod
    async def rewrite(self, user_query: str) -> RewriteResult:
        """
        输入: "老王借钱不还怎么办"
        输出: RewriteResult(
            original_query="老王借钱不还怎么办",
            legal_query="民间借贷纠纷 借款合同 违约责任 诉讼请求",
            keyword_query="民间借贷 借款合同 违约 利息 诉讼时效",
            entity_list=["民间借贷", "借款合同", "违约责任"],
        )
        """

class RuleQueryRewriter(BaseQueryRewriter):
    """规则+法律词典版本（阶段三实现）。
    同义词替换、法律术语映射、口语→法律用语词典。
    """

    def __init__(self, dict_path: str | None = None):
        self.synonym_map = {}   # "借钱不还" → "民间借贷 借款合同 违约责任"
        self.entity_dict = {}   # 法律实体识别词典

    async def rewrite(self, user_query: str) -> RewriteResult:
        ...

class LLMQueryRewriter(BaseQueryRewriter):
    """LLM 驱动的 Query Rewrite（阶段四启用）。
    深度法律术语转换、意图理解、实体抽取。
    """

    def __init__(self, llm_client):
        self.llm = llm_client

    async def rewrite(self, user_query: str) -> RewriteResult:
        ...
```

要求：
- **不写 `if llm: rewrite_with_llm() else: rewrite()` 的分支逻辑**，Retriever 只调用 `rewriter.rewrite()`
- 阶段三用 `RuleQueryRewriter`，阶段四替换为 `LLMQueryRewriter`
- 输出至少包含 `legal_query`（用于语义检索）和 `keyword_query`（用于 BM25）
- `RewriteResult` 传递给 `HybridRetriever`，分别用于不同检索通路：
  - `legal_query` → Milvus 语义检索
  - `keyword_query` → BM25 关键词检索

### 7. rag_service/retrieval/query_router.py — Query Router（查询意图路由）

```python
class QueryRouter:
    """判断用户查询意图，动态调整检索策略权重。

    不同问题类型需要不同的 BM25/语义/结构化字段的权重配比。
    """

    async def route(self, user_query: str) -> QueryIntent:
        """
        输入: "民法典第246条"
        输出: QueryIntent(
            intent_type="article_lookup",
            weights={
                "bm25": 0.35,
                "semantic": 0.25,
                "article_match": 0.40,
            },
            rerank_weights={
                "semantic": 0.30,
                "hierarchy": 0.10,
                "freshness": 0.15,
                "completeness": 0.20,
                "keyword": 0.20,
                "citation": 0.05,
            }
        )

        输入: "公司股东责任如何认定？"
        输出: QueryIntent(
            intent_type="case_analysis",
            weights={
                "bm25": 0.25,
                "semantic": 0.55,
                "case_relevance": 0.20,
            },
            rerank_weights={
                "semantic": 0.50,
                "hierarchy": 0.10,
                "freshness": 0.10,
                "completeness": 0.10,
                "keyword": 0.15,
                "citation": 0.05,
            }
        )

        意图类型: article_lookup / law_qa / case_analysis / contract_review / chapter_summary
        """
```

### 8. rag_service/retrieval/retriever.py — 混合检索编排

```python
class HybridRetriever:
    """Query Rewrite → BM25 + Milvus → RRF 融合 → MySQL 回查 → Rerank"""

    def __init__(self, bm25, milvus, reranker, query_rewriter: "BaseQueryRewriter", query_router, db: AsyncSession):
        self.bm25 = bm25
        self.milvus = milvus
        self.reranker = reranker
        self.query_rewriter = query_rewriter  # BaseQueryRewriter 接口，不关心具体实现
        self.query_router = query_router
        self.db = db                          # 用于检索后 MySQL 回查

    async def retrieve(
        self, user_query: str,
        kb_ids: list[str] | None, top_k: int = 20, rerank_top_k: int = 8
    ) -> RetrievalResult:
        """
        完整检索流程:

        1. Query Rewrite（查询重写）:
           用户输入 "老王借钱不还怎么办"
           → legal_query: "民间借贷纠纷 借款合同 违约责任 诉讼请求"
           → keyword_query: "民间借贷 借款合同 违约 利息"
           → original_query 保留用于最终展示

        2. Query Router（意图路由）:
           判断意图类型 → 动态权重配置
           article_lookup → BM25 权重高（法条编号匹配）
           case_analysis  → 语义权重高（案情相似度）
           law_qa         → 均衡权重

        3. BM25 检索 Top15:
           使用 keyword_query 进行关键词匹配
           通过 filter_expr 按 kb_ids 过滤

        4. Milvus 检索 Top15:
           使用 legal_query 进行语义匹配
           默认 filter_expr: kb_id in [...] AND is_latest == True
           chunk_level 默认不过滤，除非 query_intent 为 article_lookup 时限定 article

        5. RRF 融合 Top50:
           score = Σ w_i / (60 + rank_i)
           权重从 QueryRouter 获取（非硬编码）

        6. MySQL 回查:
           将 RRF Top50 的 chunk_id 列表 → MySQL 批量查询 knowledge_chunk
           → 补充完整 metadata（article_no, law_name, hierarchy_path, keywords, effective_date 等）
           → 这些字段 Milvus 不存或不全，MySQL 是权威来源

        7. Rerank: Top50 → Top{rerank_top_k}
           使用 RuleLegalReranker（阶段三规则版）:
           final_score = 0.45*semantic + 0.30*bm25 + 0.10*legal_level + 0.10*chunk_level + 0.05*freshness

        8. 返回 RetrievalResult（含全链路 Trace）
        """
```

### 9. rag_service/retrieval/context_builder.py — Prompt Context 构建器

```python
class ContextBuilder:
    """将检索结果构建为 LLM 可用的结构化 Prompt Context。

    这个模块是 Retriever 和 LLM 之间的桥梁。
    很多人直接在代码里 '\n\n'.join([c.text for c in chunks])，
    这会导致后期维护困难、引用丢失、token 浪费。

    ContextBuilder 负责:
    - 按 chunk_level 组织引用层级
    - 为 LLM 提供带编号的、可引用的 Context
    - 控制总 token 数不超过 LLM 上下文窗口
    """

    async def build(
        self,
        chunks: list[dict],
        citations: list[dict],
        max_tokens: int = 4000,
        include_hierarchy: bool = True
    ) -> ContextResult:
        """
        输入: 8 条 reranked Chunk + 对应的 citations
        输出:
          ContextResult(
            context_text="[1] 《民法典》第二百四十六条:\n矿藏、水流、海域属于国家所有……\n\n[2] …",
            citation_map={1: CitationObj, 2: CitationObj, ...},
            token_count=1240,
            chunk_count=8,
          )
        """

    async def build_with_parent_expansion(
        self,
        parent_chunks: list[dict],
        db: AsyncSession,                    # 用于查询 parent_chunk_id
        max_tokens: int = 6000
    ) -> ContextResult:
        """
        对 chapter_summary 意图：检索到 chapter Chunk → 展开子 Chunk → 构建完整 Context。

        流程（通过 parent_chunk_id 向下查询，不使用 child_chunk_ids）:
        1. SELECT * FROM knowledge_chunk WHERE parent_chunk_id = chapter.chunk_id → Section Chunk
        2. SELECT * FROM knowledge_chunk WHERE parent_chunk_id IN (section_ids) → Article Chunk
        3. 按层级组织为结构化 Context
        4. token 超过 max_tokens 时优先保留层级高的内容，裁剪叶子 Chunk
        """
```

要求：
- Context Builder 是**独立模块**，不耦合 Retriever 和 LLM
- 输出格式为带编号的文本，`[1]` `[2]` 对应 `citation_map`，方便 LLM 回答时输出引用编号
- 支持 token 上限控制，超过时自动裁剪
- 支持父级 Chunk 展开模式（通过 `parent_chunk_id` 逐级向下查询获取子 Chunk）
- 阶段三只需要输出 `context_text`，但接口设计要预留 `citation_map`

### 10. rag_service/retrieval/citation.py — 引用构建

```python
async def build_citations(chunks: list[dict]) -> list[dict]:
    """从检索结果构建法律引用。

    每条引用:
    {
      "chunk_id": "LAW_000000246",
      "law_name": "中华人民共和国民法典",
      "article_no": "第二百四十六条",
      "hierarchy_path": "第二编 物权 > 第五章 > 第一节 > 第二百四十六条",
      "text": "矿藏、水流、海域属于国家所有……",  # 从 metadata.content 取，≤200字
      "score": 0.94,
      "version": "2025",
      "effective_date": 1609430400,
      "page_start": 32,       # PDF 起始页码（阶段二必填）
      "page_end": 32,         # PDF 结束页码（阶段二必填）
      "char_start": 145,      # 原文在页面内的字符偏移（阶段二如能产出则填写，否则为 null）
      "char_end": 210,        # 同上
      "source_uri": "documents/civil_code/civil_code_2025.pdf"  # OSS key，前端查看原文
    }
    """
```

### PDF 定位策略

| 字段 | 来源 | 说明 |
|------|------|------|
| `page_start` / `page_end` | 阶段二必填 | PDF 页码，前端跳转定位 |
| `char_start` / `char_end` | 阶段二如能从 MinerU 产出则填写，否则为 `null` | PDF 页面内精确字符偏移 |

**前端逻辑**：

```text
有 char_start/char_end → 精确高亮
没有 char_start/char_end → 跳转 page_start，并用 text 搜索辅助高亮
```

> `char_start` / `char_end` 阶段三不能凭空生成。不要把 char 定位作为阶段三强依赖。

### 11. embedding_service/worker/embedding.py — Embedding Worker 独立进程

```bash
uv run python -m embedding_service.worker.embedding
```

```python
CHUNK_EMBEDDING_STREAM = "lawrag:stream:chunk_embedding"

async def main():
    """
    消费 Redis Stream 中的 embedding 任务。

    任务格式:
    {"document_id": "civil_code_2025", "kb_id": "civil_code", "kb_type": "law"}

    处理流程:
    1. 从 MySQL 查 knowledge_document WHERE embedding_status IN ("pending", "partial_failed")
    2. 从 MySQL 批量查 knowledge_chunk（WHERE document_id=xxx AND vector_id IS NULL）
    3. 从 knowledge_base 获取 embedding_model
    4. 创建 Embedding 实例
    5. ContextEnhancer.enhance_batch(chunks) → 增强文本列表
       - chunk_level IN ("chapter", "section", "book") 的父级 Chunk 跳过增强
       - Parent Chunk 的 content 由 ParentChunkGenerator 生成（标题+摘要+Article列表）
    6. Embedding 缓存检查:
       计算 SHA256(f"{tenant_id}:{provider}:{model}:{dimension}:{enhanced_text}") → 查 Redis → 命中跳过 API
    7. embed(missed_texts) → 新向量列表（只对未缓存的文本调用 API）
    8. 缓存回写: SHA256 → vector → Redis（TTL=30天）
    9. 写入 Milvus（单一 Collection: lawrag_chunks，精简标量字段）:
       - embedding 字段: 向量
       - chunk_id 字段: MySQL knowledge_chunk.id
       - content_hash 字段: SHA256(tenant_id:provider:model:dimension:enhanced_text)
       - tenant_id, kb_id, document_id, doc_type, chunk_type, chunk_subtype, chunk_level, legal_level,
         version, is_latest, page_start, page_end 等标量字段: 从 metadata 提取
       - (可选) law_name, article_no
       - 注意: 完整 metadata 以 MySQL 为准，Milvus 只存检索过滤必需字段
    10. 回写 knowledge_chunk.vector_id（Milvus 返回的 ID）
    11. 更新 knowledge_document:
       - embedding_status = "completed"  (全部成功)
       - embedding_status = "partial_failed"  (部分成功，如 9999 成功 1 失败)
       - embedding_status = "failed"  (全部失败)
       - embedding_count = 成功数量
       - embedding_failed_count = 失败数量
       - error_message = 错误信息（如有）
    12. 异步更新 BM25 索引（增量追加新 Chunk）
    13. ACK

    错误处理:
    - 单个 Chunk embedding 失败 → 记录错误但继续处理剩余 Chunk
    - 全部失败 → embedding_status=failed，仍然 ACK
    - 部分失败 → embedding_status=partial_failed，成功的不重做
    """
```

要求：
- **新增 `embedding_status` 状态值**：`partial_failed`（区别于 `completed` 和 `failed`）
- **新增字段**：`knowledge_document` 表增加 `embedding_count`（成功数）和 `embedding_failed_count`（失败数）
- **失败不阻塞**：单个 Chunk 失败不影响其他 Chunk 的 embedding
- 父级 Chunk（`chunk_level=chapter/section/book`）不经过 ContextEnhancer

### 12. embedding_service/services/embedding.py — Embedding 业务编排

```python
async def trigger_embedding(
    db: AsyncSession, task_queue: "TaskQueue", document_id: str
) -> None:
    """入队 Redis Stream 任务"""

async def delete_document_vectors(
    milvus: MilvusStore, db: AsyncSession, document_id: str
) -> None:
    """删除文档在 Milvus 中的向量（重新解析时调用）。
    1. 按 chunk_ids 删除 Milvus 向量
    2. UPDATE knowledge_chunk SET vector_id = NULL WHERE document_id = ?
    3. 不删除 Embedding 缓存（缓存是可复用资产，不跟文档生命周期绑定）
    """

async def check_embedding_cache(
    cache: "EmbeddingCache", content_hash: str
) -> list[float] | None:
    """检查 tenant_id:provider:model:dimension:text 的 SHA256 是否有缓存的向量"""
```

### 13. rag_service/routers/retrieval.py — Retrieval Lab 调试接口

```python
router = APIRouter(prefix="/api/retrieve", tags=["检索"])

@router.post("/debug")
async def debug_retrieve(
    body: RetrieveDebugRequest,
    current_user = Depends(get_current_user),
    db = Depends(get_db),
) -> ApiResponse[RetrieveDebugResponse]:
    """
    输入: query + kb_ids + agent_type
    输出: 完整检索链路（每一步的输入输出，用于 Debug）:
      - original_query: 用户原始输入
      - rewritten_query: Query Rewrite 输出（legal_query + keyword_query + entity_list）
      - query_intent: Query Router 输出（intent_type + 动态权重）
      - bm25_results: BM25 Top15（使用 keyword_query，含原始 query）
      - milvus_results: Milvus Top15（使用 legal_query，含 filter_expr）
      - merged_results: RRF Top50（含实际使用的 RRF 权重）
      - reranked_results: 精排 Top8（含实际使用的 Rerank 权重）
      - citations: 引用列表（含 page_start/page_end/char_start/char_end）
      - context_text: Context Builder 输出的结构化文本（可直接送 LLM）
      - latency_ms: {rewrite, router, bm25, milvus, merge, rerank, context_build, total}
    写入 rag_trace 表（完整 Trace）
    """

@router.post("/bm25/reload")
async def reload_bm25(
    current_user = Depends(get_current_user),
    bm25 = Depends(get_bm25),
    db = Depends(get_db),
) -> ApiResponse[dict]:
    """手动触发 BM25 全量重建索引（调试用）"""

@router.get("/trace/{trace_id}")
async def get_trace(trace_id: str, ...) -> ApiResponse[RetrieveTraceResponse]:
    """查看历史 Trace"""
```

### 14. rag_service/schemas/retrieval.py

```python
class RetrieveDebugRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    kb_ids: list[str] = Field(min_length=1, max_length=10)
    agent_type: str = "law_qa"
    top_k: int = Field(default=8, ge=1, le=20)

class ChunkResultItem(BaseModel):
    chunk_id: str
    text: str
    score: float
    bm25_score: float | None
    milvus_score: float | None
    chunk_type: str | None
    chunk_subtype: str | None
    chunk_level: str | None
    article_no: str | None
    law_name: str | None
    hierarchy_path: str | None
    legal_level: str | None
    version: str | None
    is_latest: bool | None
    page_start: int | None
    page_end: int | None
    char_start: int | None
    char_end: int | None
    source_uri: str | None
    metadata: dict | None

class RetrieveDebugResponse(BaseModel):
    trace_id: str
    original_query: str
    rewritten_query: RewriteResult | None   # Query Rewrite 输出
    query_intent: QueryIntent | None        # Query Router 输出
    bm25_results: list[ChunkResultItem]
    milvus_results: list[ChunkResultItem]
    merged_results: list[ChunkResultItem]
    reranked_results: list[ChunkResultItem]
    citations: list[dict]
    context_text: str | None               # Context Builder 输出（可直接送 LLM）
    latency_ms: dict   # {"rewrite": 80, "router": 5, "bm25": 12, "milvus": 45, "merge": 3, "rerank": 120, "context_build": 5, "total": 270}

class RetrieveTraceResponse(BaseModel):
    """完整检索链路 Trace，记录每一步的输入输出"""
    trace_id: str
    # Step 1: 输入
    original_query: str
    # Step 2: Query Rewrite
    rewritten_query: RewriteResult | None
    # Step 3: Query Router
    query_intent: QueryIntent | None
    # Step 4: BM25 Raw
    bm25_raw_query: str | None            # BM25 实际使用的 keyword_query
    bm25_results: list[ChunkResultItem] | None
    bm25_latency_ms: int | None
    # Step 5: Milvus Raw
    milvus_query_vector_dim: int | None   # Embedding 向量维度
    milvus_filter_expr: str | None        # 实际 filter 表达式
    milvus_results: list[ChunkResultItem] | None
    milvus_latency_ms: int | None
    # Step 6: RRF Merge
    rrf_weights: dict | None              # 实际使用的 RRF 权重
    merged_results: list[ChunkResultItem] | None
    merge_latency_ms: int | None
    # Step 7: Rerank
    rerank_weights: dict | None           # 实际使用的 Rerank 权重
    reranked_results: list[ChunkResultItem] | None
    rerank_latency_ms: int | None
    # Step 8: Citations
    citations: list[dict] | None
    # Step 9: Context Builder (可选，阶段四 LLM 消费)
    context_text: str | None
    context_token_count: int | None
    # 汇总
    total_latency_ms: int
    created_at: datetime
```

### 15. 修改已有文件

**backend/main.py** — lifespan 中新增：

```python
# RAG 检索运行态对象来源于 rag_service/retrieval/
# Embedding 缓存来源于 embedding_service/embedding/
# 具体 import/package 名称由服务拆分后的工程包装层统一适配。

# startup:
app.state.milvus = MilvusStore(settings.milvus_host, settings.milvus_port)
app.state.milvus.init_collection(embedding_dim=settings.embedding_dim)  # 单一 Collection
app.state.tokenizer = JiebaTokenizer(dict_path=settings.tokenizer_dict_path or None)
app.state.bm25 = BM25Retriever(tokenizer=app.state.tokenizer)
app.state.query_rewriter = RuleQueryRewriter(dict_path=settings.tokenizer_dict_path or None)
app.state.query_router = QueryRouter()
app.state.context_builder = ContextBuilder()
app.state.embedding_cache = EmbeddingCache(redis) if settings.embedding_cache_enabled else None
# 异步加载/重建 BM25 索引（优先加载持久化文件）

# 新增依赖注入
async def get_milvus(request: Request) -> MilvusStore: ...
async def get_bm25(request: Request) -> BM25Retriever: ...
async def get_tokenizer(request: Request) -> "JiebaTokenizer": ...
async def get_query_rewriter(request: Request) -> "BaseQueryRewriter": ...
async def get_query_router(request: Request) -> QueryRouter: ...
async def get_context_builder(request: Request) -> ContextBuilder: ...
```

**backend/config.py** — 新增：

```python
milvus_host: str = "127.0.0.1"
milvus_port: int = 19530
embedding_provider: str = "openai"        # openai / bge / deepseek / qwen
embedding_model: str = "text-embedding-3-small"
embedding_dim: int = 1536
embedding_api_base: str = ""
embedding_api_key: str = ""
max_embedding_tokens: int = 500            # ContextEnhancer token 上限（BGE 512，留 12 token 余量）
embedding_cache_enabled: bool = True       # 是否启用 Embedding 去重缓存
embedding_cache_ttl: int = 2592000         # 缓存 TTL（秒，默认 30 天）
embedding_cache_scope: str = "tenant"      # 缓存隔离范围: tenant / global
reranker_provider: str = "rule"            # 阶段三: rule（规则Reranker），阶段四: bge / cohere
reranker_model: str = "bge-reranker-v2-m3"
reranker_api_base: str = "http://localhost:8081/rerank"
bm25_index_dir: str = "storage/bm25"      # BM25 索引持久化目录
tokenizer_provider: str = "jieba"          # jieba / hanlp / pkuseg
tokenizer_dict_path: str = ""              # 法律自定义词典路径
context_max_tokens: int = 4000             # Context Builder 默认 token 上限
```

**backend/routers/__init__.py** — 导出检索 router。

---

## 依赖新增

```toml
"pymilvus>=2.4.0",       # Milvus SDK
"openai>=1.50.0",        # Embedding API (OpenAI / DeepSeek / Qwen 兼容)
"jieba>=0.42.1",         # 中文分词
"rank-bm25>=0.2.2",      # BM25
"httpx>=0.27.0",         # 异步 HTTP
"tiktoken>=0.7.0",       # Token 计数（ContextEnhancer 长度控制）
```

---

## 验证方式

```bash
# 1. 启动基础设施
docker compose up -d mysql redis milvus

# 2. 安装依赖
uv sync

# 3. 启动 Embedding Worker
uv run python -m embedding_service.worker.embedding

# 4. 启动 API
uv run uvicorn backend.main:app --reload --port 8000

# 5. 上传民法典 PDF
curl -X POST http://localhost:8000/api/document/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "kb_id=civil_code" \
  -F "file=@民法典.pdf"

# 6. 等待 Parser Worker + Embedding Worker 处理完成
curl http://localhost:8000/api/document/civil_code_2025 \
  -H "Authorization: Bearer $TOKEN"
# → embedding_status: "completed"

# 7. 检索
curl -X POST http://localhost:8000/api/retrieve/debug \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "矿藏属于谁所有",
    "kb_ids": ["civil_code"],
    "agent_type": "law_qa"
  }'
# → 返回 BM25/Milvus/Rerank 全链路 + Query Rewrite + Query Intent + 第二百四十六条排在第一位
```

---

---

## 阶段三目标重定义

```text
阶段三只完成"可检索、可引用、可调试"的 RAG 核心闭环。
```

### 必须完成

| # | 模块 | 说明 |
|---|------|------|
| 1 | metadata 兼容扩展 | 阶段二字段不删不改，新增 `parent_chunk_id`、`chunk_subtype`、`is_latest`、`char_start`、`char_end`、`source_uri` |
| 2 | parent_chunk_id + 稳定 Parent ID | `{document_id}:{chunk_level}:{part_no}:{chapter_no}:{section_no}` 格式，幂等 upsert |
| 3 | ContextEnhancer | 策略模式，每种 chunk_type 独立增强器，增强后文本只用于 embedding |
| 4 | Embedding Worker | Redis Stream 消费，缓存检查，部分失败不阻塞 |
| 5 | Milvus 写入与 MySQL 回查 | Milvus 精简标量字段，检索后 MySQL 批量回查补全 metadata |
| 6 | BM25 MVP | Jieba 分词，pickle 持久化，启动自动加载，增量追加 |
| 7 | HybridRetriever + RRF | Query Rewrite → BM25 Top15 + Milvus Top15 → RRF Top50 |
| 8 | RuleLegalReranker | 规则加权: `0.45*semantic + 0.30*bm25 + 0.10*legal_level + 0.10*chunk_level + 0.05*freshness` |
| 9 | CitationBuilder | 含 page_start/page_end，char_start/char_end 可为 null |
| 10 | ContextBuilder | 带编号结构化文本，token 上限控制，父级展开 |
| 11 | /api/retrieve/debug 全链路 trace | 每一步输入输出 + 延迟，写入 rag_trace 表 |

### 暂不强制

| # | 模块 | 阶段 |
|---|------|------|
| 1 | Cross-Encoder Reranker（BGE-Reranker / Cohere） | 阶段四 |
| 2 | LLM Query Rewrite | 阶段四 |
| 3 | 精确 PDF char 高亮（依赖 MinerU） | 阶段二兜底 |
| 4 | Elasticsearch 替换 BM25 | 阶段六 |
| 5 | Graph Retrieval（Neo4j / NebulaGraph） | 阶段五 |

---

## 未来扩展（阶段四—阶段六预留设计）

### 阶段四：LLM Agent + Cross-Encoder Rerank

- `LLMQueryRewriter` 替换 `RuleQueryRewriter`
- `CrossEncoderReranker` 替换 `RuleLegalReranker`（或作为 SemanticScorer 实现）
- Context Builder 输出对接 LLM Agent

### 阶段五：Graph Retrieval（知识图谱检索）

法律天然适合 Graph。Milvus 关联 Neo4j / NebulaGraph：

```text
Chunk → [Related Chunks] → 2-hop → 完整法律上下文
```

### 阶段六：Hybrid Search V2

- Elasticsearch 替换 BM25
- Graph Search 接入
- 多路融合 + Cross-Encoder

---

## 禁止事项

- **禁止 `RecursiveCharacterTextSplitter`** 和任何基于 token 数/字符数的切分器
- **禁止 LangChain 的 Splitter/Chunker**
- metadata schema 阶段二字段不删除、不改名，只新增
- 不要引入 Elasticsearch（阶段六再说）
- 允许通过 migration 和最小 ORM 字段扩展修改 models/knowledge.py；
- 不改动阶段二 parser 的既有解析逻辑，只在阶段三后处理补充检索字段。
- 不要做 LLM 生成（阶段四的事）
- **Parent Chunk 摘要不要用 LLM**，阶段三用规则模板生成
- **Milvus 不要塞完整 metadata JSON**，精简为检索必需的过滤字段
