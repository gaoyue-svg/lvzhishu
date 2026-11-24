// Harness 运营监控接口模块：封装后端 /api/harness/* 只读聚合查询。
import { httpGet } from './request'

import type {
  EvaluationData,
  HarnessOverview,
  IntentsData,
  LlmUsageData,
  QuestionDetail,
  QuestionsResponse,
  RagData,
  RuntimeStats,
  TraceDetail,
  TracesResponse,
} from '@/types/harness'

export interface TraceQuery {
  page?: number
  page_size?: number
  status?: string
  intent?: string
  q?: string
  since_days?: number
}

/** 运营总览：pipeline / LLM / 质量 / 检索 / 运行时 + 逐日趋势。 */
export const getHarnessOverview = (sinceDays = 7) =>
  httpGet<HarnessOverview>('/harness/overview', { params: { since_days: sinceDays } })

/** run 追踪分页列表，支持状态 / 意图 / 关键词过滤。 */
export const getHarnessTraces = (query: TraceQuery = {}) =>
  httpGet<TracesResponse>('/harness/traces', {
    params: { page: 1, page_size: 20, since_days: 7, ...query },
  })

/** run 追踪详情（含 plan / 步骤 / review / 最终答案 / 评估分）。 */
export const getHarnessTraceDetail = (traceId: string) =>
  httpGet<TraceDetail>(`/harness/traces/${encodeURIComponent(traceId)}`)

/** 时间窗内出现过的意图候选，供追踪页筛选下拉使用。 */
export const getHarnessIntents = (sinceDays = 7) =>
  httpGet<IntentsData>('/harness/traces/intents', { params: { since_days: sinceDays } })

/** LLM 用量聚合（provider/model/purpose + 逐日趋势）。 */
export const getHarnessLlm = (sinceDays = 7) =>
  httpGet<LlmUsageData>('/harness/llm', { params: { since_days: sinceDays } })

/** 质量评估聚合（online/offline + 最近评估）。 */
export const getHarnessEvaluation = (sinceDays = 7) =>
  httpGet<EvaluationData>('/harness/evaluation', { params: { since_days: sinceDays } })

/** 检索健康聚合（引用率 / 延迟 / precision_proxy）。 */
export const getHarnessRag = (sinceDays = 7) =>
  httpGet<RagData>('/harness/rag', { params: { since_days: sinceDays } })

/** 进程内 Prometheus 计数器快照（护栏 / 降级 / LLM / Agent）。 */
export const getHarnessRuntime = () => httpGet<RuntimeStats>('/harness/runtime')

export interface QuestionQuery {
  page?: number
  page_size?: number
  engine?: string
  status?: string
  q?: string
  since_days?: number
}

/** 提问级执行链路分页列表（每个提问一行：query/engine/agent/工具摘要）。 */
export const getHarnessQuestions = (query: QuestionQuery = {}) =>
  httpGet<QuestionsResponse>('/harness/questions', {
    params: { page: 1, page_size: 20, since_days: 7, ...query },
  })

/** 提问级执行链路详情（完整 agents JSON，含嵌套 tools）。 */
export const getHarnessQuestionDetail = (traceId: string) =>
  httpGet<QuestionDetail>(`/harness/questions/${encodeURIComponent(traceId)}`)
