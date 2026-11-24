// 检索接口模块,对齐后端 /api/retrieve 路由。
// 主要用于法律法规页面的条文级混合检索调试,调用 /api/retrieve/debug 获取完整链路结果。
import { httpDelete, httpGet, httpPost } from './request'

import type { RetrieveDebugPayload, RetrieveDebugResponse, RetrieveHistoryItem } from '@/types/retrieval'

// 执行一次可观察的混合检索,返回完整链路结果(重写、BM25、Milvus、合并、Rerank、引用、上下文)。
export const debugRetrieve = (payload: RetrieveDebugPayload) =>
  httpPost<RetrieveDebugResponse>('/retrieve/debug', payload, { timeout: 60_000 })

// 获取当前用户最近的法规检索历史，记录由后端 rag_trace 持久化。
export const listRetrieveHistory = (limit = 20) =>
  httpGet<RetrieveHistoryItem[]>('/retrieve/history', { params: { limit } })

// 删除当前用户的一条法规检索历史记录。
export const deleteRetrieveHistory = (traceId: string) =>
  httpDelete<null>(`/retrieve/history/${traceId}`)
