"""本文件创建 FastAPI 应用，并管理数据库、Redis、OSS 与检索组件生命周期。"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.database import AsyncSessionLocal, close_connections, init_database_if_empty, init_redis
from backend.middleware.exception import register_exception_handlers
from backend.middleware.trace_id import TraceIdMiddleware
from agent_service.agents import AgentManager
from agent_service.citation import CitationValidator
from agent_service.metrics import init_metrics
from agent_service.tools import ToolRegistry
from backend.routers import routers
from agent_service.memory import RedisMemory
from agent_service.router import RouterAgent
from agent_service.router.trace import RagTraceRouterRecorder
from embedding_service.embedding.embedding import EmbeddingFactory
from embedding_service.embedding.embedding_cache import CacheScope, EmbeddingCache
from rag_service.retrieval.bm25 import BM25Retriever
from rag_service.retrieval.context_builder import ContextBuilder
from rag_service.retrieval.milvus_client import MilvusStore
from rag_service.retrieval.query_rewrite import RuleQueryRewriter
from rag_service.retrieval.query_router import QueryRouter
from rag_service.retrieval.tokenizer import JiebaTokenizer
from backend.storage.oss import OSSClient
from backend.utils.logger import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


async def get_oss(request: Request) -> OSSClient:
    """返回应用级 OSS 客户端。"""
    return request.app.state.oss


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """管理后端启动与关闭期间所需的各类资源。"""
    try:
        await init_database_if_empty()
    except Exception as exc:
        logger.warning("数据库初始化已跳过: %s", exc.__class__.__name__)
    redis = await init_redis()
    app.state.memory = RedisMemory(redis)
    app.state.router_agent = RouterAgent(
        memory=app.state.memory,
        trace_recorder=RagTraceRouterRecorder(AsyncSessionLocal),
    )
    app.state.oss = OSSClient(
        settings.oss_endpoint,
        settings.oss_access_key_id,
        settings.oss_access_key_secret,
    )
    app.state.milvus = None
    try:
        milvus = MilvusStore(settings.milvus_host, settings.milvus_port)
        await asyncio.to_thread(milvus.init_collection, settings.embedding_dim)
        app.state.milvus = milvus
    except Exception as exc:
        logger.warning("Milvus初始化失败，检索将降级为BM25: %s", exc.__class__.__name__)

    app.state.tokenizer = JiebaTokenizer(settings.tokenizer_dict_path or None)
    app.state.bm25 = BM25Retriever(
        tokenizer=app.state.tokenizer,
        index_dir=settings.bm25_index_dir,
    )
    app.state.query_rewriter = RuleQueryRewriter(settings.tokenizer_dict_path or None)
    app.state.query_router = QueryRouter()
    app.state.context_builder = ContextBuilder()
    app.state.agent_embedding = EmbeddingFactory.create(
        settings.embedding_provider,
        settings.embedding_model,
        settings.embedding_api_base or None,
        settings.embedding_api_key or None,
        dimension=settings.embedding_dim,
    )
    app.state.tool_registry = ToolRegistry()
    app.state.citation_validator = CitationValidator()
    app.state.agent_manager = AgentManager(
        bm25=app.state.bm25,
        milvus=app.state.milvus,
        embedding=app.state.agent_embedding,
        query_rewriter=app.state.query_rewriter,
        query_router=app.state.query_router,
        context_builder=app.state.context_builder,
        tool_registry=app.state.tool_registry,
        memory=app.state.memory,
        citation_validator=app.state.citation_validator,
    )

    # MCP 客户端（doc 20 必应中文搜索 MCP 接入）：连接失败仅降级，不阻塞启动。
    # 模块级导入放到条件外，避免 UnboundLocalError（lifespan 作用域问题）。
    from agent_service.mcp import MCPClientManager, set_mcp_manager

    app.state.mcp_manager = None
    if settings.mcp_enabled and settings.bing_mcp_server_url:
        app.state.mcp_manager = MCPClientManager(
            server_url=settings.bing_mcp_server_url,
            timeout=settings.bing_mcp_timeout,
        )
        set_mcp_manager(app.state.mcp_manager)
        try:
            await app.state.mcp_manager.ensure_connected()
            mcp_tools = await app.state.mcp_manager.list_tools()
            logger.info("[MCP] 客户端已就绪，服务器工具: %s", [t["name"] for t in mcp_tools])
        except Exception as exc:
            logger.warning("[MCP] 客户端初始化失败，联网检索将降级: %s", exc.__class__.__name__)
    else:
        set_mcp_manager(None)
    app.state.embedding_cache = (
        EmbeddingCache(
            redis,
            scope=CacheScope(settings.embedding_cache_scope),
            ttl=settings.embedding_cache_ttl,
        )
        if redis is not None and settings.embedding_cache_enabled
        else None
    )
    try:
        if not await app.state.bm25.load():
            async with AsyncSessionLocal() as db:
                await app.state.bm25.rebuild_all(db)
            await app.state.bm25.save()
    except Exception as exc:
        logger.warning("BM25索引加载或重建失败: %s", exc.__class__.__name__)

    # 内嵌 Worker：开发环境单进程同时跑解析与向量化，上传后自动完成全链路。
    # 生产环境设置 LAWRAG_INLINE_WORKERS=false，改用独立 Worker 进程横向扩展。
    app.state.inline_stop = asyncio.Event()
    app.state.inline_tasks: list[asyncio.Task] = []
    if settings.inline_workers:
        # 延迟导入避免循环依赖；Worker 模块本身较重，仅在启用时加载。
        from backend.worker import contract_review as contract_review_worker
        from backend.worker import evaluator as evaluator_worker
        from backend.worker import parser as parser_worker
        from embedding_service.worker import embedding as embedding_worker

        async def _run_parser() -> None:
            try:
                await parser_worker.main(
                    stop_event=app.state.inline_stop,
                    register_signals=False,
                    close_on_exit=False,
                )
            except Exception:
                logger.exception("内嵌解析 Worker 异常退出")

        async def _run_embedding() -> None:
            try:
                await embedding_worker.main(
                    stop_event=app.state.inline_stop,
                    register_signals=False,
                    close_on_exit=False,
                )
            except Exception:
                logger.exception("内嵌向量化 Worker 异常退出")

        async def _run_contract_review() -> None:
            try:
                await contract_review_worker.main(
                    stop_event=app.state.inline_stop,
                    register_signals=False,
                    close_on_exit=False,
                )
            except Exception:
                logger.exception("内嵌合同审查 Worker 异常退出")

        async def _run_evaluator() -> None:
            try:
                await evaluator_worker.main(
                    stop_event=app.state.inline_stop,
                    register_signals=False,
                    close_on_exit=False,
                )
            except Exception:
                logger.exception("内嵌离线评估 Worker 异常退出")

        app.state.inline_tasks.append(asyncio.create_task(_run_parser(), name="inline-parser"))
        app.state.inline_tasks.append(asyncio.create_task(_run_embedding(), name="inline-embedding"))
        app.state.inline_tasks.append(asyncio.create_task(_run_contract_review(), name="inline-contract-review"))
        app.state.inline_tasks.append(asyncio.create_task(_run_evaluator(), name="inline-evaluator"))
        logger.info("内嵌 Worker 已启动（解析 + 向量化 + 合同审查 + 离线评估），上传后自动处理")

    # Harness 治理中间件：注册 Prometheus 指标处理器到 HookBus（幂等，见 doc 21）
    init_metrics()

    yield

    # 关闭：先通知 Worker 退出，等待最多 10s，超时则取消。
    app.state.inline_stop.set()
    for task in app.state.inline_tasks:
        try:
            await asyncio.wait_for(task, timeout=10)
        except asyncio.TimeoutError:
            task.cancel()
        except Exception:
            logger.exception("内嵌 Worker 退出时发生异常")
    if app.state.mcp_manager is not None:
        await app.state.mcp_manager.close()
    await close_connections()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    debug=settings.app_debug,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(TraceIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.app_env == "development" else settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_exception_handlers(app)

for router in routers:
    app.include_router(router)


@app.get(
    "/api/health",
    summary="健康检查",
    description="返回服务状态和当前后端版本。",
)
async def health() -> dict[str, str]:
    """返回服务健康状态。"""
    return {"status": "ok", "version": "0.1.0"}


__all__ = ["app"]
