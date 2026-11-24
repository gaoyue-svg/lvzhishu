# Repository Guidelines

## 项目结构与模块组织

本仓库是 LawRAG 法律 RAG 平台工程。主要目录如下：

- `backend/`：FastAPI 后端通用源码，包含 `routers/`、`services/`、`models/`、`schemas/`、`middleware/`、`utils/`、`storage/`、`worker/`。
- `rag_service/`：阶段三 RAG 检索服务代码，包含混合检索、BM25、Milvus、重排、引用、上下文构建、检索调试接口和检索 Schema。
- `embedding_service/`：阶段三 Embedding 服务代码，包含上下文增强、Embedding 模型抽象、Embedding 缓存、向量化业务编排和 Embedding Worker。
- `sql/init.sql`：MySQL 初始化脚本和表结构定义，不要随意修改。
- `doc/`：产品、架构、接口、数据库、测试与部署设计文档。
- `frontend/`、`parser-service/`：后续阶段服务目录。
- `.env`：本地开发环境变量；提交前避免写入真实密钥。

当前后端入口为 `backend/main.py`。注意 Python 包目录使用下划线命名：`rag_service`、`embedding_service`，不要再创建或引用带连字符的 `rag-service`、`embedding-service` 包路径。

## 构建、测试与开发命令

常用命令：

```bash
uv sync
```

安装并同步 Python 依赖。

```bash
uv run uvicorn backend.main:app --reload --port 8000
```

启动后端开发服务器，访问 `http://localhost:8000/docs` 查看 Swagger。

```bash
uv run python -c "import backend.main; print('import ok')"
```

快速检查应用是否可正常导入。

```bash
uv run python -c "import backend.main; import embedding_service.worker.embedding; print('import ok')"
```

快速检查 API 与 Embedding Worker 是否可正常导入。

```bash
uv run python -m compileall backend rag_service embedding_service tests
```

检查后端、RAG、Embedding 与测试源码语法。

```bash
uv run python -m unittest tests.test_retrieval_core -v
```

运行阶段三核心检索单元测试。

```bash
uv run python -m backend.worker.parser
```

启动文档解析 Worker。

```bash
uv run python -m embedding_service.worker.embedding
```

启动 Embedding Worker。

## 编码风格与命名规范

Python 代码使用 4 空格缩进，优先使用类型标注和 SQLAlchemy 2.0 `Mapped` 风格。函数、变量、模块使用 `snake_case`，类使用 `PascalCase`。接口返回统一使用 `ApiResponse[T]`。所有新增函数应包含简短 docstring。避免同步阻塞数据库操作，数据库访问使用 `AsyncSession`。
在编写代码的时候，在关键处要有中文的代码注释，在每一个文件的开头，都用中文注释解释，这个文件代码的作用是什么。

## 测试指南

当前仓库已建立 `tests/`，阶段三核心测试位于 `tests/test_retrieval_core.py`。新增测试时建议放在 `tests/`，按模块命名，例如 `tests/test_auth.py`、`tests/test_user.py`、`tests/test_retrieval_core.py`。接口测试优先使用 FastAPI `TestClient` 或异步 HTTP 客户端。核心场景应覆盖注册、登录、鉴权、资料更新、异常响应、并发唯一键冲突，以及检索链路的 Query Rewrite、Query Router、RRF、Rerank、Citation 和 Context Builder。

## 提交与 Pull Request 规范

当前目录未包含可用 Git 历史，提交信息建议采用简洁动词开头，例如：

- `feat: add auth endpoints`
- `fix: handle register integrity error`
- `docs: add contributor guide`

PR 应说明变更目的、影响范围、验证命令和结果。涉及接口变更时，附上请求/响应示例；涉及前端 UI 时附截图。

## 安全与配置提示

不要在代码或日志中输出密码、JWT、OSS 密钥等敏感信息。`.env` 仅用于本地开发，生产环境应通过部署平台注入配置。Redis 不可用时，登出黑名单能力可降级，但请求不应被阻塞。`sql/init.sql` 和 `doc/` 是基础设计资产，除非任务明确要求，否则不要修改。

## 阶段二：知识库与文档入库功能现状

本阶段已实现知识库、文档入库、Chunk 查询、OSS 存储和 Redis Stream 解析 Worker。后续开发应基于以下现状继续演进：

- 知识库接口位于 `backend/routers/kb.py`，提供 `/api/kb` 的列表、创建、详情、更新和删除能力；业务逻辑位于 `backend/services/kb.py`。
- 文档接口位于 `backend/routers/document.py`，提供 `/api/document/upload`、列表、详情、删除和重解析能力；业务逻辑位于 `backend/services/document.py`。
- Chunk 查询接口位于 `backend/routers/chunk.py`，按 `document_id`、`kb_id` 分页返回 `knowledge_chunk`，并按 `chunk_index` 排序。
- 文档解析逻辑位于 `backend/services/parser.py`，支持 `pdf`、`docx`、`txt`、`html`。上传白名单必须与解析器支持范围保持一致，不要放开未实现解析器的格式。
- 后台解析 Worker 位于 `backend/worker/parser.py`，启动命令为 `uv run python -m backend.worker.parser`；任务队列封装位于 `backend/worker/task_queue.py`，使用 Redis Stream `lawrag:stream:document_parse`。
- OSS 封装位于 `backend/storage/oss.py`。数据库中的 `oss_url` 使用 `build_storage_url()` 保存紧凑 URL，真实 HTTP 访问和签名 URL 仍使用编码后的访问 URL。不要把百分号编码后的长 URL 直接写入 `knowledge_document.oss_url`。
- `knowledge_chunk` 已要求 `(document_id, chunk_index)` 唯一，`sql/init.sql` 中使用 `UNIQUE KEY uk_doc_chunk (document_id, chunk_index)`，ORM 元数据中也通过 `Index("uk_doc_chunk", ..., unique=True)` 声明。已有数据库需要单独执行迁移或确认索引存在。
- 删除知识库时不直接物理删除 OSS 文件，而是写入 `task_log` 的 `oss_cleanup` 任务，供后续清理任务处理。
- 删除单个文档时先提交数据库删除，再 best-effort 删除 OSS；OSS 删除失败只记录 warning，不回滚数据库删除。
- 文档上传时如果 OSS 上传后入队或数据库提交失败，路由层会尝试补偿删除已上传 OSS 对象，避免孤儿文件。
- 重解析接口在文档 `parse_status == "parsing"` 时返回 409，避免多个 Worker 并发写同一文档 Chunk。
- Worker 单条消息处理必须使用 per-message `try/finally` ACK，坏消息不能导致整个 Worker 崩溃或 pending 死循环。
- Chunk 切分需要保留段落空行；法条外文本以 `chunk_type="preamble"` 保留；短 chunk 不应被 overlap 完整复制到下一个 chunk；空文本 token 估算应为 0。

常用验证命令：

```bash
uv run python -m compileall backend rag_service embedding_service tests
uv run python -c "import backend.main; import backend.worker.parser; import embedding_service.worker.embedding; print('import ok')"
```

## 阶段三：Embedding 与检索功能现状

本阶段已实现可检索、可引用、可调试的 RAG 核心闭环。后续开发应基于以下现状继续演进：

- RAG 检索服务代码位于 `rag_service/`，Embedding 向量化服务代码位于 `embedding_service/`。不要再把阶段三检索或向量化代码新增到 `backend/retrieval/`、`backend/services/embedding.py` 或 `backend/worker/embedding.py`。
- `rag_service/retrieval/` 包含 `models.py`、`tokenizer.py`、`bm25.py`、`milvus_client.py`、`query_rewrite.py`、`query_router.py`、`retriever.py`、`reranker.py`、`citation.py`、`context_builder.py`、`parent_chunk.py` 和 `dependencies.py`。
- `embedding_service/embedding/` 包含 `context_enhancer.py`、`embedding.py`、`embedding_cache.py`；`embedding_service/services/embedding.py` 负责任务入队、向量清理和缓存查询；`embedding_service/worker/embedding.py` 是独立向量化 Worker。
- `backend/main.py` 在 lifespan 中初始化 Milvus、JiebaTokenizer、BM25Retriever、RuleQueryRewriter、QueryRouter、ContextBuilder 和 EmbeddingCache，并通过 `rag_service.retrieval.dependencies` 暴露给路由依赖。
- 检索调试接口位于 `rag_service/routers/retrieval.py`，挂载前缀为 `/api/retrieve`，提供 `/debug`、`/bm25/reload`、`/trace/{trace_id}`；请求响应 Schema 位于 `rag_service/schemas/retrieval.py`。
- 文档解析 Worker `backend/worker/parser.py` 在解析完成后调用 `ParentChunkBuilder` 构建父级 Chunk，再通过 `embedding_service.services.embedding.trigger_embedding()` 写入 Redis Stream `lawrag:stream:chunk_embedding`。
- Embedding Worker 启动命令为 `uv run python -m embedding_service.worker.embedding`，消费 `lawrag:stream:chunk_embedding`，执行上下文增强、Embedding 缓存检查、Milvus 写入、`knowledge_chunk.vector_id` 回写、`knowledge_document.embedding_status` 更新和 BM25 增量更新。
- `ContextEnhancer` 只生成 Embedding 用文本，不替换 `knowledge_chunk.text`。`chunk_level` 为 `book`、`chapter`、`section` 的父级 Chunk 直接使用规则摘要正文，不再叠加层级增强。
- `ParentChunkBuilder` 与 Parser 解耦。Parser 只负责产出叶子 Chunk；父级 Chunk 使用稳定 ID，按 `book`、`chapter`、`section` 规则模板生成，Parent 不保存 `child_chunk_ids`，子节点展开通过 `parent_chunk_id` 查询。
- `HybridRetriever` 链路为 RuleQueryRewriter → QueryRouter → BM25 + Milvus → RRF Merge → MySQL 回查 → RuleLegalReranker → CitationBuilder → ContextBuilder。RRF 权重来自 QueryRouter，不要硬编码。
- `RuleLegalReranker` 默认公式为 `0.45*semantic + 0.30*bm25 + 0.10*legal_level + 0.10*chunk_level + 0.05*freshness`。`legal_level` 只能来自 metadata 字段，禁止通过 `law_name` 字符串推断法律位阶。
- Milvus 使用单一 Collection `lawrag_chunks`，只保存检索过滤必需的精简标量字段。完整 metadata 以 MySQL 为权威来源，检索后必须批量回查 MySQL 补全。
- Embedding 缓存 key 必须包含 `tenant_id`、`provider`、`model`、`dimension` 和增强文本的 SHA256。删除文档时只删除 Milvus 向量并清空 `vector_id`，不要删除 Redis Embedding 缓存。
- `knowledge_document` 已扩展 `version`、`effective_date`、`is_latest`、`superseded_by_document_id`、`embedding_status`、`embedding_count`、`embedding_failed_count` 等字段；`knowledge_chunk` 已扩展 `parent_chunk_id`、`chunk_subtype`、`chunk_level`、`legal_level`、`page_start`、`page_end`、`char_start`、`char_end`、`source_uri`、`vector_id` 等检索字段。
- 阶段三迁移脚本位于 `sql/migrations/001_phase3_embedding_retrieval.sql`。已有数据库需要单独执行迁移或确认字段、索引已存在。
- 通用 token 计数与截断函数位于 `backend/utils/tokenizer.py`。`rag_service` 与 `embedding_service` 都应依赖该通用工具，避免两个服务互相引用造成循环依赖。
- 阶段三测试位于 `tests/test_retrieval_core.py`，覆盖 ContextEnhancer、ParentChunkBuilder、Query Rewrite、Query Router、RRF、Rerank、Citation、Context Builder 和 TaskQueue 坏消息处理。

阶段三常用验证命令：

```bash
uv run python -m compileall backend rag_service embedding_service tests
uv run python -c "import backend.main; import embedding_service.worker.embedding; print('import ok')"
uv run python -m unittest tests.test_retrieval_core -v
```
