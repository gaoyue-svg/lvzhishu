// 检索相关类型定义,对齐后端 rag_service/schemas/retrieval.py 的响应契约。
// 这些类型用于法律法规页面的条文级混合检索与结果展示。

// 查询重写结果,对应后端 RewriteResult。
export interface RewriteResult {
  original_query: string
  legal_query: string
  keyword_query: string
  entity_list: string[]
}

// 查询意图与动态权重,对应后端 QueryIntent。
export interface QueryIntent {
  intent_type: string
  weights: Record<string, number>
  rerank_weights: Record<string, number>
  filters: Record<string, unknown>
}

// Chunk 结果项,对应后端 ChunkResultItem,包含检索分数与法律 metadata。
export interface ChunkResultItem {
  chunk_id: string
  text: string
  score: number
  bm25_score: number | null
  milvus_score: number | null
  chunk_type: string | null
  chunk_subtype: string | null
  chunk_level: string | null
  article_no: string | null
  law_name: string | null
  hierarchy_path: string | null
  legal_level: string | null
  version: string | null
  is_latest: boolean | null
  page_start: number | null
  page_end: number | null
  char_start: number | null
  char_end: number | null
  source_uri: string | null
  metadata: Record<string, unknown> | null
}

// 检索耗时汇总,按链路各阶段拆分。
export interface LatencySummary {
  rewrite: number
  router: number
  bm25: number
  milvus: number
  merge: number
  rerank: number
  context_build: number
  total: number
}

// 调试检索响应,对应后端 RetrieveDebugResponse。
export interface RetrieveDebugResponse {
  trace_id: string
  original_query: string
  rewritten_query: RewriteResult | null
  query_intent: QueryIntent | null
  bm25_results: ChunkResultItem[]
  milvus_results: ChunkResultItem[]
  merged_results: ChunkResultItem[]
  reranked_results: ChunkResultItem[]
  citations: Array<Record<string, unknown>>
  context_text: string | null
  latency_ms: LatencySummary
}

// 调试检索请求,对应后端 RetrieveDebugRequest。
export interface RetrieveDebugPayload {
  query: string
  kb_ids: string[]
  agent_type?: string
  top_k?: number
}

export interface RetrieveHistoryItem {
  trace_id: string
  query: string
  hit_count: number
  total_latency_ms: number
  intent_type: string | null
  created_at: string
}
