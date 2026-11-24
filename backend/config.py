"""本文件负责从环境变量加载 LawAgent 后端运行配置。"""

from functools import lru_cache

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """LawAgent 后端运行期配置项。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_name: str = "LawAgent"
    app_debug: bool = True

    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = "123456"
    mysql_database: str = "lawrag"
    mysql_pool_size: int = 10
    mysql_max_overflow: int = 20

    redis_url: str = "redis://127.0.0.1:6379/4"

    jwt_secret: str = "change-me-to-a-random-string-at-least-32-chars"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 4320
    refresh_token_expire_days: int = 3

    oss_endpoint: str = "https://oss-cn-hangzhou.aliyuncs.com"
    oss_access_key_id: str = ""
    oss_access_key_secret: str = ""
    oss_documents_bucket: str = "lawrag-documents"
    oss_reports_bucket: str = "lawrag-reports"

    cors_origins: str = "*"

    # 阶段三检索基础设施与模型配置。
    milvus_host: str = "127.0.0.1"
    milvus_port: int = 19530
    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    embedding_api_base: str = ""
    embedding_api_key: str = ""
    max_embedding_tokens: int = 500
    embedding_batch_size: int = 100
    milvus_upsert_batch_size: int = 1000
    embedding_cache_enabled: bool = True
    embedding_cache_ttl: int = 2592000
    embedding_cache_scope: str = "tenant"
    reranker_provider: str = "rule"
    reranker_model: str = "bge-reranker-v2-m3"
    reranker_api_base: str = "http://localhost:8081/rerank"
    bm25_index_dir: str = "storage/bm25"
    tokenizer_provider: str = "jieba"
    tokenizer_dict_path: str = ""
    context_max_tokens: int = 8000

    # 阶段四 LLM 基础配置；未配置 api_key/api_base 时默认不启用真实模型调用。
    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-chat"
    llm_api_base: str = ""
    llm_api_key: str = ""
    llm_temperature: float = 0.3
    llm_max_tokens: int = 4096
    llm_timeout: int = 60
    llm_retry: int = 2

    # 用户 LLM 配置加密密钥（BYOK）；为空时回退到 jwt_secret 派生，仅限开发环境。
    llm_config_secret: str = ""
    byok_enabled: bool = True
    byok_fallback_to_global: bool = True

    # Router Agent 配置；Router 只做路由决策，输出 JSON，不生成最终法律回答。
    router_llm_temperature: float = 0.1
    router_llm_max_tokens: int = 800
    router_llm_timeout: int = 8
    router_llm_retry: int = 2
    router_confidence_threshold: float = 0.6
    router_confidence_max: float = 0.95

    # Agent 三层记忆：结构化事实 + 模型长期摘要 + 近期原文窗口。
    agent_memory_ttl: int = 86400
    agent_memory_max_turns: int = 6
    agent_memory_max_tokens: int = 12000
    agent_memory_summary_trigger_tokens: int = 9000
    agent_memory_summary_tokens: int = 3000
    agent_memory_recent_tokens: int = 7500
    agent_retry_max: int = 1
    langgraph_checkpoint_enabled: bool = False

    # 阶段四工具与防幻觉校验配置。
    tavily_api_key: str = ""
    tavily_api_base: str = "https://api.tavily.com"
    tavily_max_results: int = 5
    tavily_search_depth: str = "advanced"
    # 开启 include_raw_content 拉取网页正文存入引用 full_text；单条正文上限（字符）。
    tavily_include_raw_content: bool = True
    tavily_full_text_limit: int = 6000
    # OCR 提供方：rapidocr(基于 onnxruntime，默认启用) / none(禁用)
    # 注：原 paddle 选项因 paddlepaddle 无 Python 3.14 wheel 已弃用
    ocr_provider: str = "rapidocr"
    # 以下两项为 PaddleOCR 历史配置，RapidOCR 不使用，保留以兼容已有 .env
    paddle_ocr_lang: str = "ch"
    paddle_use_gpu: bool = False
    # 扫描件判定：PDF 每页平均字符数低于此值时认为是扫描件，走 OCR 链路
    ocr_min_chars_per_page: int = 50
    citation_validation_enabled: bool = True

    # Supervisor 多 Agent 协同配置；supervisor_enabled=False 时完全走老链路。
    # 决策 LLM 失败重试 1 次，仍失败则降级到 Router 单 Agent。
    supervisor_enabled: bool = True
    supervisor_max_rounds: int = 5               # Supervisor 最大决策轮次
    supervisor_llm_temperature: float = 0.2      # 决策温度，偏低求稳
    supervisor_llm_max_tokens: int = 512         # 决策输出不大
    supervisor_llm_timeout: int = 15             # 决策超时秒数
    supervisor_llm_retry: int = 1                # 决策失败重试次数
    supervisor_max_agent_calls: int = 2          # 同一 Agent 最多调用次数
    synthesizer_temperature: float = 0.3         # 合成阶段温度

    # ===== 查询改写层：用户提问后、意图识别前，v1/v2 编排共用 =====
    # 规则优先纠错别字/口语化表达；LLM 增强默认关闭，避免每轮提问多一次 LLM 调用。
    query_rewrite_enabled: bool = True
    query_rewrite_llm_enabled: bool = False
    query_rewrite_llm_temperature: float = 0.1
    query_rewrite_llm_max_tokens: int = 256
    query_rewrite_llm_timeout: int = 15
    query_rewrite_llm_retry: int = 1

    # ===== 多 Agent v2 编排（doc 19 多Agent编排与治理方案）=====
    # 新链路先灰度：multiagent_v2_enabled=False 时沿用 Supervisor V1 决策循环。
    # 意图→规划→执行→审查→合成 五层链路在 agent_service/orchestrator/ 下实现。
    multiagent_v2_enabled: bool = False

    # 规划层：Plan DAG 生成与守卫。
    plan_max_steps: int = 4               # 单次计划最大步数，超出守卫直接兜底
    planner_llm_temperature: float = 0.1  # 规划温度偏低求稳
    planner_llm_max_tokens: int = 1024
    planner_llm_timeout: int = 15
    planner_llm_retry: int = 1

    # 执行层：slot 表 + 拓扑执行 + 并行组。
    step_timeout: float = 60.0            # 单步超时秒数
    step_retry: int = 1                   # 单步失败重试次数（指数退避）
    replan_max: int = 1                   # 失败重规划最大次数
    contract_rag_max_queries: int = 3     # 合同法条检索最多选取的代表性条款数
    contract_rag_query_timeout: float = 12.0  # 单条款检索超时；失败时保留其他条款结果

    # 审查层：L1 确定性 + L2 抽样 + 重试/升级闭环。
    review_retry_max: int = 1             # 审查失败重试出错步上限
    review_l2_enabled: bool = True        # L2 落地抽查开关
    review_l2_sample_max: int = 3         # L2 抽样论断数

    # 合成层：控制传给合成器的 context_text 长度，避免 token 膨胀。
    synth_context_max_tokens: int = 8000

    # 模型分层（doc 19 §5.5）骨架：留空=沿用主 LLM（user_llm）。
    # 接必应/其他 provider 后按档位映射 cheap/strong 模型。
    model_tier_cheap: str = ""            # 意图/规划/路由用小模型
    model_tier_strong: str = ""           # 推理/合成用大模型

    # ===== MCP 客户端（doc 20 必应中文搜索 MCP 接入）=====
    # LawRAG 作为 MCP 客户端连接外部 Streamable HTTP 必应搜索服务器；
    # 仅 bing_search 单工具，必应 Key 由 MCP 服务器侧持有。
    mcp_enabled: bool = False                 # 总开关；开启且配置 URL 时启动连接 MCP
    mcp_client_timeout: float = 30.0          # MCP 客户端操作超时秒数
    mcp_connect_retry: int = 2                # 连接/调用失败重连次数
    mcp_tool_allowlist: list[str] = ["bing_search"]  # 安全白名单：只允许调用该 MCP 工具

    # 联网搜索 provider 抽象（doc 19 §5 + doc 20）。
    # 取值：tavily（现有实现） | bing_mcp（走 MCP 客户端）。
    web_search_provider: str = "tavily"
    bing_mcp_server_url: str = ""             # 外部必应搜索 MCP 服务器地址（Streamable HTTP）
    bing_mcp_tool_name: str = "bing_search"   # 服务器暴露的搜索工具名（实测为 bing_search）
    bing_mcp_timeout: float = 30.0            # 搜索调用超时秒数

    # 内嵌 Worker 开关；开发环境为 true 时由后端进程同时跑解析与向量化 Worker，无需单独开终端。
    # 生产环境建议设为 false，使用独立 Worker 进程横向扩展。
    inline_workers: bool = True

    # 文档版面解析配置；生产环境显式开启 MinerU 后优先走 PDF/Word -> Markdown 的版面解析链路。
    mineru_enabled: bool = False
    mineru_api_url: str = ""
    mineru_backend: str = ""
    mineru_method: str = "auto"
    mineru_lang: str = "ch"
    mineru_timeout_seconds: int = 3600

    # ===== 知识库文档上传 =====
    # 法律汇编、司法解释和案例集 PDF 通常较大，默认允许单文件 200 MB。
    knowledge_upload_max_bytes: int = 200 * 1024 * 1024
    oss_download_retry: int = 3                 # OSS 下载遇到临时 TLS/网络错误时的最大尝试次数
    oss_download_retry_backoff: float = 1.0     # 下载重试退避基数（秒）

    # ===== 会话临时上传（合同分析）=====
    # 聊天中上传的合同等文件经解析后落 chat_upload 表，供多 Agent 分析；到期自动清理。
    chat_upload_ttl_hours: int = 24              # 临时上传文件保留小时数
    chat_upload_max_bytes: int = 50 * 1024 * 1024  # 单文件大小上限

    # ===== 阿里云 OCR（文字识别）=====
    # 启用后图片/扫描件优先走阿里云 OCR（按量计费），失败自动降级本地 RapidOCR；
    # 未配置密钥时 aliyun_ocr_enabled 视为关闭，仅走本地 RapidOCR。
    aliyun_ocr_enabled: bool = False
    aliyun_ocr_access_key_id: str = ""
    aliyun_ocr_access_key_secret: str = ""
    aliyun_ocr_region: str = "cn-shanghai"        # 接入点 ocr-api.{region}.aliyuncs.com
    aliyun_ocr_max_pages: int = 100               # 扫描 PDF 最多 OCR 页数

    # ===== Agent Harness 治理中间件（doc 21）=====
    # 复用现有 v2 编排层，只补可观测性 / 护栏 / 评估；各开关默认开，可灰度关闭。
    harness_enabled: bool = True                  # 总开关；关闭时 trace/评估全跳过
    harness_trace_enabled: bool = True            # agent_run_trace 落库
    harness_metrics_enabled: bool = True          # Prometheus /metrics 指标
    llm_usage_enabled: bool = True                # llm_usage 采集与落库
    evaluation_enabled: bool = True               # 在线确定性评估
    evaluation_sample_rate: float = 0.05          # 离线 LLM 评审抽样率（Phase 3 使用，先落配置）
    # Prompt 版本全局覆盖：{"prompt_name": "version"}，手动固定某版本；A/B 时由实验框架按请求覆盖。
    prompt_version_overrides: dict[str, str] = {}
    # A/B 实验开关（Phase 3）：开启后 v2 编排按 user_id 哈希分流 prompt 版本并落库记录。
    experiment_enabled: bool = True

    # ===== Input Guard（doc 21 §4.1，Phase 2）=====
    guard_enabled: bool = True                    # 总开关；关闭则直接放行
    guard_max_query_chars: int = 4000             # 单条 query 最大字符数
    guard_max_upload_files: int = 10              # 单次会话最大上传文件数
    guard_prompt_injection_enabled: bool = True   # 提示注入规则检测
    guard_blocked_keywords: str = ""              # 逗号分隔的敏感词表（业务方提供，默认空）
    guard_request_token_cap: int = 4000           # 单请求估算 token 上限（0=不限）
    guard_user_daily_token_quota: int = 200000    # 单用户每日 token 配额（0=不限）
    guard_max_concurrency: int = 3                # 单用户并发会话上限（0=不限）

    @computed_field
    @property
    def mysql_url(self) -> str:
        """返回带数据库名的异步 SQLAlchemy MySQL URL。"""
        return (
            f"mysql+aiomysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}?charset=utf8mb4"
        )

    @computed_field
    @property
    def mysql_server_url(self) -> str:
        """返回不指定数据库的异步 SQLAlchemy MySQL URL。"""
        return (
            f"mysql+aiomysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/?charset=utf8mb4"
        )


@lru_cache
def get_settings() -> Settings:
    """构建并缓存应用配置实例。"""
    return Settings()


settings = get_settings()
