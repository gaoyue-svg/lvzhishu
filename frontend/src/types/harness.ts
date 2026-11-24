// Harness 运营监控数据类型定义：约束后端 /api/harness/* 与前端监控组件之间的数据契约。

export interface PipelineStats {
  total_runs: number
  success: number
  failed: number
  hitl: number
  success_rate: number
  avg_latency_ms: number
  p95_latency_ms: number
}

export interface LlmDimension {
  name: string
  calls: number
  tokens: number
  cost: number
  avg_latency_ms: number
}

export interface LlmStats {
  total_calls: number
  total_tokens: number
  total_cost: number
  by_provider: LlmDimension[]
  by_model: LlmDimension[]
  by_purpose: LlmDimension[]
}

export interface EvalModeStats {
  count: number
  citation_score: number
  coverage: number
  grounded_score: number
  hallucination: number
  overall: number
}

export interface RecentEval {
  trace_id: string
  mode: 'online' | 'offline'
  citation_score: number | null
  coverage: number | null
  grounded_score: number | null
  hallucination: number | null
  overall: number | null
  created_at: string | null
}

export interface EvalStats {
  online: EvalModeStats
  offline: EvalModeStats
  recent: RecentEval[]
}

export interface RagStats {
  since_days: number
  total_retrievals: number
  avg_total_latency_ms: number
  avg_retrieval_latency_ms: number
  citation_rate: number
  avg_citation_count: number
  avg_retrieved_count: number
  precision_proxy: number
}

export interface RuntimeStats {
  since_process_start: boolean
  guard: { total_blocked: number; by_check: Record<string, number> }
  pipeline: Record<string, number>
  web_search_fallback: Record<string, number>
  milvus_fallback: number
  llm: { calls: number; tokens: number; cost: number }
  agent_calls: Record<string, number>
}

export interface TrendPoint {
  date: string
  runs: number
  success: number
  failed: number
  hitl: number
  llm_calls: number
  tokens: number
  cost: number
  citation_rate: number
  overall: number | null
}

export interface HarnessOverview {
  since_days: number
  generated_at: string
  pipeline: PipelineStats
  questions: QuestionStats
  llm: LlmStats
  evaluation: EvalStats
  rag: RagStats
  runtime: RuntimeStats
  trend: TrendPoint[]
}

export interface QuestionStats {
  total: number
  by_engine: Record<string, number>
  by_status: Record<string, number>
}

export interface ExecutionTool {
  name: string
  agent: string | null
  input_summary: string
  output_summary: string
  ok: boolean
  latency_ms: number
}

export interface ExecutionAgent {
  agent: string
  round: number
  status: string
  input_summary: string
  latency_ms: number
  chunks_count: number
  citations_count: number
  output_summary: string
  tools: ExecutionTool[]
}

export interface QuestionItem {
  trace_id: string
  conversation_id: number | null
  user_id: number | null
  query: string
  intent: string | null
  engine: string | null
  status: string
  agent_count: number
  tool_count: number
  agents: string[]
  tools: string[]
  total_latency_ms: number
  answer_snippet: string
  error: string | null
  created_at: string | null
}

export interface QuestionDetail
  extends Omit<QuestionItem, 'agents' | 'query' | 'answer_snippet' | 'error'> {
  query: string | null
  agents: ExecutionAgent[] | null
  answer_snippet: string | null
  error: string | null
}

export interface QuestionsResponse {
  total: number
  page: number
  page_size: number
  items: QuestionItem[]
}

export interface TraceItem {
  trace_id: string
  plan_id: string | null
  conversation_id: number | null
  user_id: number | null
  query: string
  intent: string | null
  intent_confidence: number | null
  status: string
  total_latency_ms: number
  step_count: number
  needs_human_review: boolean
  experiment_variant: string | null
  error: string | null
  created_at: string | null
}

export interface TracesResponse {
  total: number
  page: number
  page_size: number
  items: TraceItem[]
}

export interface StepTrace {
  step_id: string
  agent: string
  status: string
  goal?: string
  output_summary?: string
  chunks_count?: number
  citations_count?: number
  latency_ms?: number
  error?: string
}

export interface PlanStep {
  step_id: string
  agent: string
  goal?: string
  inputs?: Record<string, unknown>
  outputs?: Record<string, string>
  parallel_group?: string
  deps?: string[]
}

export interface AgentResultSummary {
  agent?: string
  _step_id?: string
  output_summary?: string
  answer?: string
}

export interface TraceEvaluation {
  citation_score: number | null
  coverage: number | null
  grounded_score: number | null
  hallucination: number | null
  overall: number | null
  detail: Record<string, unknown> | null
}

export interface ReviewIssue {
  step_id?: string
  agent?: string
  level?: string
  issues?: string[]
}

export interface ReviewL2 {
  passed?: boolean
  checked?: number
  reason?: string
  failed_claims?: string[]
}

export interface ReviewResult {
  passed: boolean
  failed_steps?: string[]
  issues?: ReviewIssue[]
  needs_human_review?: boolean
  l2?: ReviewL2
}

export interface TraceDetail {
  trace_id: string
  plan_id: string | null
  conversation_id: number | null
  user_id: number | null
  query: string | null
  intent: Record<string, unknown> | null
  plan: { plan_id?: string; query?: string; steps?: PlanStep[] } | null
  step_traces: StepTrace[] | null
  agent_results_summary: AgentResultSummary[] | null
  review: ReviewResult | null
  final_answer: string | null
  final_citations: Array<Record<string, unknown>> | null
  error: string | null
  status: string
  total_latency_ms: number
  step_count: number
  needs_human_review: boolean
  experiment_variant: string | null
  created_at: string | null
  evaluation: { online: TraceEvaluation | null; offline: TraceEvaluation | null }
}

export interface LlmUsageData {
  since_days: number
  total_calls: number
  total_tokens: number
  total_cost: number
  by_provider: LlmDimension[]
  by_model: LlmDimension[]
  by_purpose: LlmDimension[]
  trend: { date: string; calls: number; tokens: number; cost: number }[]
}

export interface EvalTrendPoint {
  date: string
  overall: number | null
  citation_score: number
  coverage: number
  grounded_score: number
  hallucination: number
}

export interface EvaluationData {
  since_days: number
  online: EvalModeStats
  offline: EvalModeStats
  recent: RecentEval[]
  trend: EvalTrendPoint[]
}

export interface RagData extends RagStats {
  trend: { date: string; citation_rate: number; total: number }[]
}

export interface IntentsData {
  intents: string[]
}
