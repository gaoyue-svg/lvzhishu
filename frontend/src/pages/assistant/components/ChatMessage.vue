<!--
  单条聊天消息组件:
  - 用户消息右侧气泡,Assistant 消息左侧法律意见卡片
  - Assistant 正文使用 markdown-it 渲染 Markdown,并用 DOMPurify 清洗 HTML
  - 支持流式光标、节点时间线、引用卡片和消息反馈操作
-->
<template>
  <div
    class="chat-message"
    :class="`role-${message.role}`"
  >
    <div class="msg-avatar">
      <component
        :is="message.role === 'user' ? UserRound : Scale"
        :size="16"
      />
    </div>
    <div class="msg-body">
      <div class="msg-head">
        <span class="msg-name">{{ message.role === 'user' ? '我' : '律智枢' }}</span>
        <span
          v-if="agentLabel"
          class="msg-agent"
        >{{ agentLabel }}</span>
        <span class="msg-time">{{ formattedTime }}</span>
      </div>

      <div
        v-if="message.role === 'assistant' && streaming && progressMessage"
        class="process-status"
      >
        <Loader2 :size="13" class="process-spin" />
        <span class="process-title">处理进度</span>
        <span>{{ progressMessage }}</span>
      </div>

      <!-- 多 Agent(Supervisor/v2):展示 Agent 步骤进度,避免生成过程静默。
           Supervisor 只发 agent_start/agent_end,由 Assistant.vue 动态登记 agentSteps 驱动。 -->
      <AgentTimeline
        v-if="isAgentTimelineVisible"
        :steps="agentSteps ?? []"
        :current-agent="currentAgent ?? null"
        :finished-agents="finishedAgents ?? new Set()"
        :failed-agents="failedAgents ?? new Set()"
      />
      <!-- 单 Agent:展示节点级时间线(意图/检索/工具/推理/引用/校验) -->
      <NodeTimeline
        v-else-if="isNodeTimelineVisible"
        :finished-nodes="finishedNodes ?? new Set()"
        :current-node="currentNode ?? null"
        :chunk-count="chunkCount ?? null"
        :tool-count="toolCount ?? null"
      />

      <div
        ref="contentRef"
        class="msg-content"
        @click="handleContentClick"
      >
        <p
          v-if="message.role === 'user'"
          class="msg-text"
        >{{ message.content }}</p>

        <div
          v-else
          class="msg-markdown"
          v-html="renderedContent"
        />

        <span
          v-if="streaming"
          class="stream-cursor"
          aria-hidden="true"
        />
      </div>

      <!-- 用户消息:已上传文件 chips -->
      <div
        v-if="message.role === 'user' && messageFiles.length > 0"
        class="msg-files"
      >
        <div
          v-for="(f, idx) in messageFiles"
          :key="idx"
          class="msg-file-chip"
        >
          <FileText :size="12" />
          <span class="msg-file-name">{{ f.filename }}</span>
          <span class="msg-file-badge">{{ fileTypeLabel(f.file_type) }}</span>
        </div>
      </div>

      <CitationPanel
        v-if="message.role === 'assistant' && visibleCitations.length > 0"
        :citations="visibleCitations"
      />

      <!-- 合同分析结构化结果卡片(要素 + 风险 + 导出报告) -->
      <ContractResultCard
        v-if="message.role === 'assistant' && contractResult && !streaming"
        :result="contractResult"
        :upload-id="contractUploadId"
      />

      <div
        v-if="riskAlerts.length > 0"
        class="msg-risk"
      >
        <AlertTriangle :size="13" />
        <span>{{ riskAlerts[0].message }}</span>
      </div>

      <div
        v-if="message.role === 'assistant' && !streaming && message.id"
        class="msg-actions"
      >
        <button
          v-if="canExportDocument"
          type="button"
          class="action-btn"
          @click="$emit('exportDocument', message.id)"
        >
          <Download :size="13" />
          导出 Word (.docx)
        </button>
        <button
          type="button"
          class="action-btn"
          :class="{ active: message.feedback === 'like' }"
          @click="$emit('feedback', 'like')"
        >
          <ThumbsUp :size="13" />
          有帮助
        </button>
        <button
          type="button"
          class="action-btn"
          :class="{ active: message.feedback === 'dislike' }"
          @click="$emit('feedback', 'dislike')"
        >
          <ThumbsDown :size="13" />
          需改进
        </button>
        <button
          v-if="message.retrieval_trace_id"
          type="button"
          class="action-btn"
          @click="$emit('trace', message.retrieval_trace_id)"
        >
          <Activity :size="13" />
          检索链路
        </button>
        <button
          type="button"
          class="action-btn"
          @click="$emit('copy', message.content)"
        >
          <Copy :size="13" />
          复制
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import {
  Activity,
  AlertTriangle,
  Copy,
  Download,
  FileText,
  Scale,
  ThumbsDown,
  ThumbsUp,
  UserRound,
} from 'lucide-vue-next'

import AgentTimeline from './AgentTimeline.vue'
import CitationPanel from './CitationPanel.vue'
import ContractResultCard from './ContractResultCard.vue'
import NodeTimeline from './NodeTimeline.vue'
import type {
  Citation,
  ContractAnalysisResult,
  ConversationMessage,
  MessageFeedback,
  UploadedFileRef,
} from '@/types/conversation'

const markdown = new MarkdownIt({
  breaks: true,
  html: false,
  linkify: true,
  typographer: false,
})

markdown.inline.ruler.before('emphasis', 'citation_ref', (state, silent) => {
  const match = state.src.slice(state.pos).match(/^\[(\d{1,3})\]/)
  if (!match) return false

  if (!silent) {
    const token = state.push('citation_ref', 'button', 0)
    token.content = match[1]
  }
  state.pos += match[0].length
  return true
})

markdown.renderer.rules.citation_ref = (tokens, idx) => {
  const citeNo = escapeAttr(tokens[idx].content)
  return `<button type="button" class="md-cite" data-cite="${citeNo}" aria-label="查看引用 ${citeNo}">[${citeNo}]</button>`
}

markdown.renderer.rules.table_open = () => '<div class="md-table-wrap"><table>'
markdown.renderer.rules.table_close = () => '</table></div>'
markdown.renderer.rules.fence = (tokens, idx) => {
  const token = tokens[idx]
  const info = token.info ? `<span class="md-code-lang">${escapeHtml(token.info.trim())}</span>` : ''
  return `<pre class="md-code">${info}<code>${escapeHtml(token.content)}</code></pre>`
}
markdown.renderer.rules.link_open = (tokens, idx, options, _env, self) => {
  const token = tokens[idx]
  token.attrSet('target', '_blank')
  token.attrSet('rel', 'noopener noreferrer')
  return self.renderToken(tokens, idx, options)
}

const props = defineProps<{
  message: ConversationMessage
  // 是否正在流式生成,仅对最后一条 Assistant 消息生效。
  streaming?: boolean
  // 节点时间线状态。
  finishedNodes?: Set<string>
  currentNode?: string | null
  chunkCount?: number | null
  toolCount?: number | null
  // 是否强制展示时间线,无节点事件时也展示占位。
  showTimeline?: boolean
  // 时间线模式:node=单 Agent 节点级;agent=Supervisor/v2 的 Agent 级。
  timelineMode?: 'node' | 'agent' | null
  // 安全的处理阶段摘要，不包含模型私有思维链。
  progressMessage?: string
  // 多 Agent 步骤进度(agent_start/agent_end 驱动)。
  agentSteps?: { step_id: string; agent: string; goal?: string; order?: number }[]
  currentAgent?: string | null
  finishedAgents?: Set<string>
  failedAgents?: Set<string>
}>()

defineEmits<{
  feedback: [feedback: Exclude<MessageFeedback, null>]
  trace: [traceId: string]
  copy: [text: string]
  exportDocument: [messageId: string]
}>()

const contentRef = ref<HTMLElement | null>(null)

// 原件模板答复即使经过历史消息恢复、旧 SSE 客户端或中间层丢失布尔标记，
// 仍应保留下载入口，避免用户只能看到“请点击下载”却没有按钮。
const canExportDocument = computed(
  () =>
    Boolean(props.message.exportable_document) ||
    (props.message.role === 'assistant' && props.message.content.includes('导出 Word (.docx)')),
)

// 时间线可见性:多 Agent 模式下展示 Agent 步骤(即使步骤尚未登记也占位切换,避免闪现节点时间线);
// 单 Agent 模式下展示节点级时间线。
const isAgentTimelineVisible = computed(
  () =>
    props.message.role === 'assistant' &&
    (props.showTimeline || props.streaming) &&
    (props.timelineMode === 'agent' || (props.agentSteps?.length ?? 0) > 0),
)
const isNodeTimelineVisible = computed(
  () =>
    props.message.role === 'assistant' &&
    (props.showTimeline || props.streaming) &&
    props.timelineMode === 'node',
)

const agentMeta: Record<string, string> = {
  law_qa: '法律咨询',
  article_locate: '法条定位',
  contract_review: '合同审查',
  case_analysis: '案例分析',
}

const agentLabel = computed(() => {
  const t = (props.message as ConversationMessage & { agent_type?: string }).agent_type
  return t ? agentMeta[t] ?? t : ''
})

const formattedTime = computed(() => {
  const d = new Date(props.message.created_at)
  if (Number.isNaN(d.getTime())) return ''
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${hh}:${mm}`
})

const visibleCitations = computed<Citation[]>(() => {
  const raw = props.message.citations
  if (!raw) return []
  if (Array.isArray(raw)) return raw
  if (Array.isArray(raw.items)) return raw.items
  return []
})

const riskAlerts = computed(() => {
  const extra = (props.message as ConversationMessage & { risk_alerts?: { level: string; message: string }[] }).risk_alerts
  return extra ?? []
})

const messageFiles = computed<UploadedFileRef[]>(() => props.message.uploaded_files ?? [])

const contractResult = computed<ContractAnalysisResult | undefined>(
  () => (props.message as ConversationMessage & { contract?: ContractAnalysisResult }).contract,
)

const contractUploadId = computed<string | undefined>(
  () => (props.message as ConversationMessage & { upload_ids?: string[] }).upload_ids?.[0],
)

function fileTypeLabel(fileType?: string): string {
  const image = ['jpg', 'jpeg', 'png', 'bmp', 'tiff', 'tif', 'webp']
  const t = fileType ?? ''
  if (image.includes(t)) return '图片'
  if (t === 'docx') return 'Word'
  if (t === 'pdf') return 'PDF'
  return (t || '文件').toUpperCase()
}

// 先解析 Markdown 再清洗 HTML,让标题、表格、代码块、列表和引用保持稳定结构。
const renderedContent = computed(() => {
  const raw = props.message.content || ''
  return renderMarkdown(raw)
})

function renderMarkdown(src: string): string {
  const html = markdown.render(src)
  return DOMPurify.sanitize(html, {
    ADD_ATTR: ['target', 'rel', 'data-cite', 'aria-label', 'type'],
  })
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function escapeAttr(s: string): string {
  return escapeHtml(s).replace(/"/g, '&quot;')
}

function handleContentClick(event: MouseEvent) {
  const target = event.target instanceof HTMLElement ? event.target.closest<HTMLElement>('.md-cite') : null
  if (!target?.dataset.cite) return

  const root = contentRef.value?.closest('.chat-message')
  const card = Array.from(root?.querySelectorAll<HTMLElement>('.citation-card') ?? []).find(
    (item) => item.dataset.citeIndex === target.dataset.cite,
  )
  if (!card) return

  card.scrollIntoView({ behavior: 'smooth', block: 'center' })
  card.classList.add('is-cite-highlight')
  window.setTimeout(() => card.classList.remove('is-cite-highlight'), 1400)
}
</script>

<style scoped>
.chat-message {
  display: flex;
  gap: 14px;
  align-items: flex-start;
  padding: 2px 0;
}

.chat-message.role-user {
  flex-direction: row-reverse;
}

.msg-avatar {
  width: 36px;
  height: 36px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  color: #ffffff;
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
  color: #fff;
  box-shadow: 0 6px 16px rgb(37 99 235 / 24%);
}

.role-user .msg-avatar {
  background: linear-gradient(135deg, #0b1f3d 0%, #1e293b 100%);
  box-shadow: 0 6px 16px rgb(15 23 42 / 28%);
}

.msg-body {
  min-width: 0;
  max-width: min(1060px, calc(100% - 58px));
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.role-user .msg-body {
  max-width: min(760px, 72%);
  align-items: flex-end;
}

.msg-head {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 22px;
  font-size: 12px;
  color: var(--law-muted);
}

.msg-name {
  font-weight: 700;
  color: var(--law-text);
  font-size: 13px;
}

.msg-agent {
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(59, 130, 246, 0.10);
  color: var(--law-primary-strong);
  font-size: 10.5px;
  font-weight: 700;
}

.msg-time {
  font-variant-numeric: tabular-nums;
  color: var(--law-muted-soft);
}

/* 消息卡片：浅色下纯白 + 6% 黑色描边 + 极轻阴影，深色保留渐变玻璃感。 */
.msg-content {
  position: relative;
  width: 100%;
  padding: 14px 17px;
  border-radius: 16px;
  background: var(--law-card);
  border: 1px solid rgba(0, 0, 0, 0.06);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  font-size: 14px;
  line-height: 1.75;
  color: var(--law-text);
  overflow-wrap: anywhere;
}

.role-user .msg-content {
  color: #ffffff;
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
  color: #fff;
  border-color: transparent;
  border-top-right-radius: 5px;
  box-shadow: 0 6px 16px rgb(37 99 235 / 24%);
}

.role-assistant .msg-content {
  padding: 18px 22px 20px;
  border-top-left-radius: 5px;
  background: var(--law-card);
}

:global(html.dark) .msg-content {
  background: var(--law-card);
  border-color: var(--law-border);
  box-shadow: 0 8px 24px rgb(0 0 0 / 22%);
}

:global(html.dark) .role-assistant .msg-content {
  background:
    linear-gradient(180deg, rgb(59 130 246 / 8%) 0%, rgb(17 24 39 / 0%) 170px),
    #101827;
  border-color: rgb(51 65 85 / 80%);
  box-shadow: 0 14px 34px rgb(0 0 0 / 22%);
}

.msg-text {
  margin: 0;
  white-space: pre-wrap;
}

.stream-cursor {
  display: inline-block;
  width: 7px;
  height: 16px;
  margin-left: 2px;
  vertical-align: -3px;
  background: var(--law-primary);
  border-radius: 2px;
  animation: blink 1s steps(2, start) infinite;
}

@keyframes blink {
  0%,
  50% {
    opacity: 1;
  }
  50.01%,
  100% {
    opacity: 0;
  }
}

.msg-risk {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 11px;
  border-radius: 8px;
  background: rgb(239 68 68 / 10%);
  color: rgb(185 28 28);
  font-size: 12px;
  font-weight: 700;
}

.process-status {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 9px 12px;
  border: 1px solid rgb(37 99 235 / 24%);
  border-radius: 10px;
  background: rgb(37 99 235 / 6%);
  color: var(--law-muted);
  font-size: 12px;
}

.process-title {
  color: var(--law-primary-strong);
  font-weight: 800;
}

.process-spin {
  color: var(--law-primary);
  animation: process-spin 0.9s linear infinite;
}

@keyframes process-spin {
  to {
    transform: rotate(360deg);
  }
}

:global(html.dark) .msg-risk {
  color: rgb(252 165 165);
}

.msg-files {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.role-user .msg-files {
  justify-content: flex-end;
}

.msg-file-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 260px;
  padding: 6px 10px;
  border: 1px solid var(--law-border);
  border-radius: 9px;
  background: var(--law-card);
  font-size: 12px;
  color: var(--law-text);
}

.role-user .msg-file-chip {
  background: rgb(255 255 255 / 14%);
  border-color: rgb(255 255 255 / 28%);
  color: #fff;
}

.msg-file-chip :deep(svg) {
  color: var(--law-primary);
  flex-shrink: 0;
}

.role-user .msg-file-chip :deep(svg) {
  color: #fff;
}

.msg-file-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.msg-file-badge {
  padding: 1px 6px;
  border-radius: 5px;
  background: rgb(37 99 235 / 10%);
  color: var(--law-primary-strong);
  font-size: 10px;
  font-weight: 800;
  flex-shrink: 0;
}

.role-user .msg-file-badge {
  background: rgb(255 255 255 / 22%);
  color: #fff;
}

.msg-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 2px;
}

.action-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 10px;
  border: 1px solid var(--law-border);
  border-radius: 8px;
  background: var(--law-card);
  color: var(--law-muted);
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  transition:
    border-color 160ms ease,
    background 160ms ease,
    color 160ms ease,
    transform 160ms ease;
}

.action-btn:hover {
  border-color: var(--law-primary);
  color: var(--law-primary-strong);
  background: rgb(37 99 235 / 6%);
  transform: translateY(-1px);
}

.action-btn.active {
  background: rgb(16 185 129 / 12%);
  border-color: rgb(16 185 129 / 50%);
  color: rgb(5 122 85);
}

:global(html.dark) .action-btn.active {
  color: rgb(94 234 212);
}

.msg-markdown {
  font-size: 14.5px;
  line-height: 1.9;
  color: var(--law-text);
}

.msg-markdown :deep(*) {
  letter-spacing: 0;
}

.msg-markdown :deep(p) {
  margin: 0 0 13px;
}

.msg-markdown :deep(p:last-child),
.msg-markdown :deep(li:last-child) {
  margin-bottom: 0;
}

.msg-markdown :deep(h1),
.msg-markdown :deep(h2),
.msg-markdown :deep(h3),
.msg-markdown :deep(h4) {
  color: var(--law-text);
  line-height: 1.35;
  font-weight: 850;
}

.msg-markdown :deep(h1) {
  margin: 0 0 14px;
  font-size: 24px;
}

.msg-markdown :deep(h2) {
  margin: 28px 0 9px;
  padding-top: 16px;
  border-top: 1px solid var(--law-border);
  font-size: 19px;
}

.msg-markdown :deep(h2:first-child) {
  margin-top: 0;
  padding-top: 0;
  border-top: 0;
}

.msg-markdown :deep(h3) {
  margin: 18px 0 8px;
  font-size: 16px;
  color: var(--law-primary-strong);
}

:global(html.dark) .msg-markdown :deep(h3) {
  color: rgb(147 197 253);
}

.msg-markdown :deep(h4) {
  margin: 14px 0 6px;
  font-size: 14.5px;
}

.msg-markdown :deep(strong) {
  color: var(--law-text);
  font-weight: 850;
}

.msg-markdown :deep(ul),
.msg-markdown :deep(ol) {
  margin: 8px 0 14px;
  padding-left: 24px;
}

.msg-markdown :deep(li) {
  margin: 5px 0;
  padding-left: 2px;
}

.msg-markdown :deep(li::marker) {
  color: var(--law-primary);
  font-weight: 800;
}

.msg-markdown :deep(blockquote) {
  margin: 14px 0;
  padding: 12px 14px;
  border-left: 3px solid var(--law-primary);
  border-radius: 0 8px 8px 0;
  background: rgb(37 99 235 / 7%);
  color: var(--law-muted);
}

.msg-markdown :deep(blockquote > :first-child) {
  margin-top: 0;
}

.msg-markdown :deep(blockquote > :last-child) {
  margin-bottom: 0;
}

.msg-markdown :deep(a) {
  color: var(--law-primary);
  font-weight: 700;
  text-decoration: none;
  border-bottom: 1px solid rgb(37 99 235 / 35%);
}

.msg-markdown :deep(a:hover) {
  border-bottom-color: currentColor;
}

.msg-markdown :deep(code:not(.md-code code)) {
  padding: 2px 6px;
  border-radius: 5px;
  background: rgb(15 23 42 / 7%);
  font-family: "JetBrains Mono", Consolas, ui-monospace, monospace;
  font-size: 12.5px;
}

:global(html.dark) .msg-markdown :deep(code:not(.md-code code)) {
  background: rgb(255 255 255 / 10%);
}

.msg-markdown :deep(.md-code) {
  position: relative;
  margin: 13px 0;
  padding: 15px 16px;
  border: 1px solid var(--law-border);
  border-radius: 8px;
  background: rgb(15 23 42 / 5%);
  overflow-x: auto;
}

:global(html.dark) .msg-markdown :deep(.md-code) {
  background: rgb(2 6 23 / 45%);
}

.msg-markdown :deep(.md-code code) {
  font-family: "JetBrains Mono", Consolas, ui-monospace, monospace;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--law-text);
}

.msg-markdown :deep(.md-code-lang) {
  display: block;
  margin-bottom: 8px;
  color: var(--law-muted);
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
}

.msg-markdown :deep(.md-table-wrap) {
  width: 100%;
  margin: 14px 0 18px;
  overflow-x: auto;
  border: 1px solid var(--law-border);
  border-radius: 8px;
  background: var(--law-card);
}

:global(html.dark) .msg-markdown :deep(.md-table-wrap) {
  background: rgb(15 23 42 / 46%);
}

.msg-markdown :deep(table) {
  width: 100%;
  min-width: 620px;
  border-collapse: collapse;
  font-size: 13px;
  line-height: 1.75;
}

.msg-markdown :deep(th),
.msg-markdown :deep(td) {
  padding: 10px 12px;
  border-bottom: 1px solid var(--law-border);
  vertical-align: top;
}

.msg-markdown :deep(th) {
  background: rgb(37 99 235 / 7%);
  color: var(--law-text);
  font-weight: 850;
  white-space: nowrap;
}

.msg-markdown :deep(tr:last-child td) {
  border-bottom: 0;
}

.msg-markdown :deep(hr) {
  height: 1px;
  margin: 24px 0;
  border: 0;
  background: var(--law-border);
}

.msg-markdown :deep(.md-cite) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 22px;
  height: 18px;
  padding: 0 5px;
  margin: 0 2px;
  border: 1px solid rgb(245 158 11 / 24%);
  border-radius: 5px;
  background: rgb(245 158 11 / 16%);
  color: rgb(180 83 9);
  font: inherit;
  font-size: 11px;
  font-weight: 850;
  font-variant-numeric: tabular-nums;
  line-height: 1;
  cursor: pointer;
  vertical-align: 1px;
  transition:
    background 140ms ease,
    border-color 140ms ease,
    color 140ms ease,
    transform 140ms ease;
}

:global(html.dark) .msg-markdown :deep(.md-cite) {
  color: rgb(252 211 77);
}

.msg-markdown :deep(.md-cite:hover) {
  background: rgb(245 158 11 / 28%);
  border-color: rgb(245 158 11 / 45%);
  transform: translateY(-1px);
}

.role-user .msg-markdown :deep(.md-cite) {
  background: rgb(255 255 255 / 22%);
  color: #fff;
}

@media (max-width: 768px) {
  .chat-message {
    gap: 10px;
  }

  .msg-avatar {
    width: 34px;
    height: 34px;
    border-radius: 10px;
  }

  .msg-body,
  .role-user .msg-body {
    max-width: calc(100% - 44px);
  }

  .role-assistant .msg-content {
    padding: 17px 18px 19px;
  }

  .msg-markdown {
    font-size: 14px;
    line-height: 1.85;
  }

  .msg-markdown :deep(h1) {
    font-size: 20px;
  }

  .msg-markdown :deep(h2) {
    font-size: 17px;
  }
}
</style>
