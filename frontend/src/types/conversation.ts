// 会话、消息与 Agent SSE 事件相关类型定义,对齐后端 /api/conversation 与 /api/agent 接口。

// 业务 Agent 类型,与后端 AgentType Literal 对齐。
export type AgentType = 'law_qa' | 'article_locate' | 'contract_review' | 'case_analysis'

// 风险等级。
export type RiskLevel = 'low' | 'medium' | 'high'

// 消息角色。
export type MessageRole = 'user' | 'assistant' | 'system'

// 消息反馈。
export type MessageFeedback = 'like' | 'dislike' | null

// 单条法律引用,对齐 rag_service.retrieval.models.Citation.to_dict()。
export interface Citation {
  chunk_id: string
  law_name: string | null
  article_no: string | null
  hierarchy_path: string | null
  text: string
  // 完整 chunk 原文，弹窗展示全文用；text 为 200 字截断片段。
  full_text?: string | null
  score: number
  version: string | null
  effective_date: number | null
  page_start: number | null
  page_end: number | null
  char_start: number | null
  char_end: number | null
  source_uri: string | null
  // 引用编号,由 citation_node 注入,前端展示 [1][2] 时使用。
  index?: number
  // 工具产生的网络引用会带 source_type=web。
  source_type?: string
  url?: string | null
  title?: string | null
}

// 会话临时上传文件引用,对齐后端 POST /api/agent/upload 返回与 AgentChatRequest.uploaded_files。
export interface UploadedFileRef {
  upload_id: string
  filename: string
  file_type: string
  doc_type: string
  parse_status?: string
  char_count?: number
  clause_count?: number
  parse_warnings?: string[]
  error_message?: string | null
}

// 合同当事人要素。
export interface ContractParty {
  name: string
  role: string
}

// 合同关键要素,对齐 ContractElementsAgent 输出的 elements 对象。
export interface ContractElements {
  contract_name: string
  contract_type: string
  party_a: ContractParty | Record<string, string>
  party_b: ContractParty | Record<string, string>
  amount: string
  currency: string
  payment_terms: string
  payment_deadline: string
  contract_term: string
  effective_date: string
  governing_law: string
  jurisdiction: string
  breach_liability: string
  signing_requirements: string
  key_obligations: string[]
  important_clauses: string[]
  [key: string]: unknown
}

// 单条合同风险,对齐 contract_risk_report 输出的风险数组项。
export interface ContractRisk {
  clause: string
  level: 'high' | 'medium' | 'low' | string
  title: string
  description: string
  suggestion: string
  law_reference?: string[] | string
  [key: string]: unknown
}

// 合同分析结构化结果,对齐 v2 final 事件 payload.contract。
export interface ContractAnalysisResult {
  summary: string
  elements: ContractElements | Record<string, unknown>
  risks: ContractRisk[]
}

// 消息记录,对齐 backend.routers.conversation._message_payload。
export interface ConversationMessage {
  id: string
  conversation_id: string
  role: MessageRole
  content: string
  // 后端存 {"items": Citation[]},前端解包后直接展示。
  citations: { items: Citation[] } | Citation[] | null
  feedback: MessageFeedback
  retrieval_trace_id: string | null
  created_at: string
  // 以下为前端会话内附加字段,不进后端持久化。
  agent_type?: string
  risk_alerts?: { level: string; message: string }[]
  uploaded_files?: UploadedFileRef[]
  contract?: ContractAnalysisResult
  upload_ids?: string[]
  /** 正式法律文书草稿才允许显示 Word 导出入口。 */
  exportable_document?: boolean
}

// 会话记录,对齐 backend.routers.conversation._conversation_payload。
export interface Conversation {
  id: string
  title: string
  agent_type: AgentType
  kb_id: string | null
  summary: string | null
  message_count: number
  created_at: string
  updated_at: string
}

// 会话详情(含最近消息)。
export interface ConversationDetail extends Conversation {
  messages: ConversationMessage[]
}

// 分页返回结构。
export interface Paginated<T> {
  items: T[]
  total: number
}

// Router 决策,对齐 agent_service.router.models.RouterDecision。
export interface RouterDecision {
  task_type: string
  agent: AgentType
  confidence: number
  need_retrieval: boolean
  retrieval_scope: {
    domain: string
    category: string
    keywords: string[]
  }
  need_file: boolean
  file_requirement: { type: string; hint: string } | null
  legal_context: {
    law_name: string | null
    article_no: string | null
    cause_of_action: string | null
  }
  sub_questions: string[]
  time_context: { type: string; year: number | null }
  execution_mode: string
  risk_level: RiskLevel
  route_reason: string
  fallback: boolean
  needs_human_review: boolean
}

// Agent SSE 事件载荷联合类型,与 agent_service.agents.base.sse_event 对齐。
// 每条事件都是 {"event": "...", ...payload} 的 JSON 对象。
export interface AgentSseEvent {
  event: string
  [key: string]: unknown
}

// node_start / node_end 事件载荷。
export interface NodeEventPayload {
  event: 'node_start' | 'node_end'
  node: string
  agent?: string
  quality?: string
  chunk_count?: number
  tool_count?: number
  passed?: boolean
  reasons?: string[]
}

// token 事件载荷:流式生成的答案片段。
export interface TokenEventPayload {
  event: 'token'
  content: string
}

// router 事件载荷:Router 决策结果。
export interface RouterEventPayload {
  event: 'router'
  [key: string]: unknown
}

// citation 事件载荷:引用列表。
export interface CitationEventPayload {
  event: 'citation'
  citations: Citation[]
}

// final 事件载荷:Agent 闭环结束。
export interface FinalEventPayload {
  event: 'final'
  answer: string
  citations: Citation[]
  risk_alerts: { level: string; message: string }[]
  trace_id: string
  needs_human_review: boolean
  citation_validation: { passed: boolean; reasons?: string[] }
  // v2 合同分析场景:携带结构化摘要/要素/风险。
  contract?: ContractAnalysisResult
}

// done 事件载荷:会话与消息已落库。
export interface DoneEventPayload {
  event: 'done'
  conversation_id: string
  message_id: string
  trace_id: string
  // 会话上传合同分析:携带 upload_id 列表,前端绑定"导出报告"。
  upload_ids?: string[]
  /** 后端确认该回答属于正式文书，可显示 Word 导出按钮。 */
  exportable_document?: boolean
}
