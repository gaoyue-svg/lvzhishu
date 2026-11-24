"""本文件封装单一 lawrag_chunks Collection 的创建、写入、检索与删除操作。"""

from __future__ import annotations

from typing import Any

class MilvusStore:
    """仅保存检索过滤所需标量字段的 Milvus 客户端门面。"""

    collection_name = "lawrag_chunks"
    default_output_fields = [
        "chunk_id", "tenant_id", "kb_id", "document_id", "doc_type", "chunk_type",
        "chunk_subtype", "chunk_level", "legal_level", "version", "is_latest",
        "page_start", "page_end", "law_name", "article_no", "content_hash",
    ]

    def __init__(self, host: str = "localhost", port: int = 19530):
        """连接 Milvus HTTP 服务。"""
        from pymilvus import MilvusClient

        self.client = MilvusClient(uri=f"http://{host}:{port}")

    def init_collection(self, embedding_dim: int) -> None:
        """幂等创建使用 COSINE + HNSW 的精简标量 Collection。"""
        from pymilvus import DataType

        if self.client.has_collection(self.collection_name):
            return
        schema = self.client.create_schema(auto_id=True, enable_dynamic_field=False)
        schema.add_field("id", DataType.INT64, is_primary=True, auto_id=True)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=embedding_dim)
        for name, length in (
            ("chunk_id", 128), ("tenant_id", 50), ("kb_id", 100), ("document_id", 100),
            ("doc_type", 30), ("chunk_type", 30), ("chunk_subtype", 64),
            ("chunk_level", 20), ("legal_level", 40), ("version", 20),
            ("content_hash", 96), ("law_name", 200), ("article_no", 40),
        ):
            schema.add_field(name, DataType.VARCHAR, max_length=length)
        schema.add_field("is_latest", DataType.BOOL)
        schema.add_field("page_start", DataType.INT32)
        schema.add_field("page_end", DataType.INT32)
        index_params = self.client.prepare_index_params()
        index_params.add_index(
            field_name="embedding",
            index_type="HNSW",
            metric_type="COSINE",
            params={"M": 16, "efConstruction": 200},
        )
        self.client.create_collection(
            collection_name=self.collection_name,
            schema=schema,
            index_params=index_params,
            consistency_level="Bounded",
        )

    def insert(self, vectors: list[dict[str, Any]]) -> list[str]:
        """分批写入不超过 1000 条向量并返回 Milvus 主键。"""
        ids: list[str] = []
        for start in range(0, len(vectors), 1000):
            result = self.client.insert(
                collection_name=self.collection_name,
                data=vectors[start : start + 1000],
            )
            ids.extend(str(item) for item in result.get("ids", result.get("primary_keys", [])))
        if vectors:
            self.flush()
        return ids

    def upsert(self, vectors: list[dict[str, Any]]) -> list[str]:
        """按业务 chunk_id 删除旧数据后插入，实现稳定业务 ID 幂等更新。"""
        chunk_ids = [str(item["chunk_id"]) for item in vectors if item.get("chunk_id")]
        self.delete_by_chunk_ids(chunk_ids)
        return self.insert(vectors)

    def search(
        self,
        query_vector: list[float],
        top_k: int = 20,
        filter_expr: str | None = None,
        output_fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """执行向量检索并返回 Milvus 原始命中列表。"""
        result = self.client.search(
            collection_name=self.collection_name,
            data=[query_vector],
            limit=top_k,
            filter=filter_expr or "",
            output_fields=output_fields or self.default_output_fields,
            search_params={"metric_type": "COSINE", "params": {"ef": max(64, top_k * 2)}},
        )
        return list(result[0]) if result else []

    def delete_by_chunk_ids(self, chunk_ids: list[str]) -> None:
        """按业务 Chunk ID 批量删除向量，空列表时不执行。"""
        if not chunk_ids:
            return
        for start in range(0, len(chunk_ids), 500):
            values = ", ".join(f'"{self._escape(item)}"' for item in chunk_ids[start : start + 500])
            self.client.delete(
                collection_name=self.collection_name,
                filter=f"chunk_id in [{values}]",
            )

    def flush(self) -> None:
        """立即刷写 Collection 数据。"""
        self.client.flush(collection_name=self.collection_name)

    def get_collection_dim(self) -> int | None:
        """返回当前 Collection 的向量维度;Collection 不存在时返回 None。

        用于 embedding 配置校验:Collection 已删除时允许保存任意维度配置,
        下次启动会按新维度重建 Collection,避免维度保护把用户彻底卡死。
        """
        if not self.client.has_collection(self.collection_name):
            return None
        desc = self.client.describe_collection(self.collection_name)
        for field in desc.get("fields", []):
            if field.get("name") == "embedding":
                params = field.get("params") or {}
                dim = params.get("dim")
                return int(dim) if dim is not None else None
        return None

    @staticmethod
    def _escape(value: str) -> str:
        """转义 Milvus 字符串过滤表达式中的反斜杠与双引号。"""
        return str(value).replace("\\", "\\\\").replace('"', '\\"')
