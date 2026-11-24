// 运营监控控制台通用格式化与映射工具。

export function formatMs(ms: number | null | undefined): string {
  if (ms == null || Number.isNaN(Number(ms))) return '—'
  const value = Number(ms)
  if (value >= 1000) return `${(value / 1000).toFixed(2)}s`
  return `${Math.round(value)}ms`
}

export function formatTokens(n: number | null | undefined): string {
  if (n == null || Number.isNaN(Number(n))) return '—'
  const value = Number(n)
  if (value >= 1e6) return `${(value / 1e6).toFixed(2)}M`
  if (value >= 1e3) return `${(value / 1e3).toFixed(1)}k`
  return String(Math.round(value))
}

export function formatCost(n: number | null | undefined): string {
  if (n == null || Number.isNaN(Number(n))) return '¥0.0000'
  const value = Number(n)
  if (value === 0) return '¥0'
  if (value < 0.01) return `¥${value.toFixed(4)}`
  return `¥${value.toFixed(2)}`
}

export function formatPercent(n: number | null | undefined, digits = 1): string {
  if (n == null || Number.isNaN(Number(n))) return '—'
  return `${(Number(n) * 100).toFixed(digits)}%`
}

export function formatInt(n: number | null | undefined): string {
  if (n == null || Number.isNaN(Number(n))) return '—'
  return Number(n).toLocaleString('en-US')
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const pad = (x: number) => String(x).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

export function formatDateShort(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const pad = (x: number) => String(x).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

export function shortTraceId(id: string): string {
  return id.length > 18 ? `${id.slice(0, 8)}…${id.slice(-8)}` : id
}

export const INTENT_LABELS: Record<string, string> = {
  law_qa: '法务问答',
  article_locate: '法条定位',
  case_analysis: '案例分析',
  contract_review: '合同审查',
  chitchat: '闲聊寒暄',
  contract_elements: '合同要素',
  contract_clause: '条款理解',
  contract_rule: '规则检测',
  contract_rag: '法条检索',
  contract_risk_report: '风险报告',
}

export function intentLabel(name: string | null | undefined): string {
  if (!name) return '未知意图'
  return INTENT_LABELS[name] ?? name
}

export const AGENT_LABELS: Record<string, string> = {
  law_qa: '法务问答',
  article_locate: '法条定位',
  case_analysis: '案例分析',
  contract_review: '合同审查',
  contract_rag: '法条检索',
  contract_clause: '条款理解',
  contract_elements: '要素提取',
  contract_rule: '规则检测',
  contract_risk_report: '风险报告',
  synthesize: '答案合成',
}

export function agentLabel(name: string | null | undefined): string {
  if (!name) return '未知'
  return AGENT_LABELS[name] ?? name
}

export const TOOL_LABELS: Record<string, string> = {
  web_search: '联网搜索',
  article_tree: '法条树',
  ocr_extract: 'OCR 识别',
  contract_clause_parser: '条款解析',
  contract_risk_rules: '风险规则',
}

export function toolLabel(name: string): string {
  return TOOL_LABELS[name] ?? name
}

export interface StatusMeta {
  label: string
  tone: 'green' | 'red' | 'amber' | 'cyan' | 'gray'
}

export const STATUS_META: Record<string, StatusMeta> = {
  success: { label: '成功', tone: 'green' },
  failed: { label: '失败', tone: 'red' },
  hitl: { label: '待复核', tone: 'amber' },
  pending: { label: '排队', tone: 'cyan' },
  running: { label: '执行中', tone: 'cyan' },
  skipped: { label: '跳过', tone: 'gray' },
}

export function statusMeta(status: string): StatusMeta {
  return STATUS_META[status] ?? { label: status || '未知', tone: 'gray' }
}

export const ENGINE_LABELS: Record<string, string> = {
  supervisor: 'Supervisor V1',
  pipeline_v2: 'Pipeline V2',
  single_agent: '单 Agent',
}

export function engineLabel(engine: string | null | undefined): string {
  if (!engine) return '未知引擎'
  return ENGINE_LABELS[engine] ?? engine
}

export function engineTone(engine: string | null | undefined): 'cyan' | 'violet' | 'green' | 'gray' {
  if (engine === 'supervisor') return 'cyan'
  if (engine === 'pipeline_v2') return 'violet'
  if (engine === 'single_agent') return 'green'
  return 'gray'
}

/** 根据 0~1 分值返回评分条等级（good/mid/bad）。 */
export function scoreTone(value: number | null | undefined): 'good' | 'mid' | 'bad' {
  if (value == null) return 'mid'
  if (value >= 0.75) return 'good'
  if (value >= 0.5) return 'mid'
  return 'bad'
}
