"""本文件集中提供从 FastAPI app.state 获取检索组件的依赖函数。"""

from fastapi import Request

from .bm25 import BM25Retriever
from .context_builder import ContextBuilder
from .milvus_client import MilvusStore
from .query_rewrite import BaseQueryRewriter
from .query_router import QueryRouter
from .tokenizer import BaseTokenizer


async def get_milvus(request: Request) -> MilvusStore | None:
    """返回应用级 Milvus 客户端；不可用时允许 BM25 降级。"""
    return getattr(request.app.state, "milvus", None)


async def get_bm25(request: Request) -> BM25Retriever:
    """返回应用级 BM25 检索器。"""
    return request.app.state.bm25


async def get_tokenizer(request: Request) -> BaseTokenizer:
    """返回应用级中文分词器。"""
    return request.app.state.tokenizer


async def get_query_rewriter(request: Request) -> BaseQueryRewriter:
    """返回应用级规则查询重写器。"""
    return request.app.state.query_rewriter


async def get_query_router(request: Request) -> QueryRouter:
    """返回应用级查询意图路由器。"""
    return request.app.state.query_router


async def get_context_builder(request: Request) -> ContextBuilder:
    """返回应用级 Prompt Context 构建器。"""
    return request.app.state.context_builder
