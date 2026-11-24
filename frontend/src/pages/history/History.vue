<!--
  历史会话页面:翻阅与 AI 的历史对话。
  - 左侧:会话档案列表(搜索、Agent 筛选、日期分组)
  - 右侧:选中会话的完整消息流,复用 ChatMessage 渲染引用与反馈
  - 顶部"加载更早消息"分页,沿用 getConversation(最近 50 条) + listMessages(更早)
  - 支持消息点赞/点踩、复制、检索链路跳转、软删除会话
-->
<template>
  <div class="history-page">
    <HistoryConversationList
      :conversations="conversations"
      :active-id="selectedId"
      :loading="listLoading"
      @select="selectConversation"
      @delete="handleDelete"
    />

    <main class="history-detail">
      <!-- 空态:未选中会话 -->
      <div
        v-if="!detail && !detailLoading"
        class="detail-empty"
      >
        <div class="empty-mark">
          <Archive :size="36" />
        </div>
        <h2 class="empty-title">选择左侧会话查看对话历史</h2>
        <p class="empty-sub">所有与 AI 的问答记录均会归档于此,支持按 Agent 类型筛选与关键词检索。</p>
      </div>

      <!-- 加载骨架 -->
      <div
        v-else-if="detailLoading && messages.length === 0"
        class="detail-loading"
      >
        <div
          v-for="i in 4"
          :key="i"
          class="skeleton-row"
        >
          <div class="skel-avatar" />
          <div class="skel-lines">
            <div
              class="skel-line"
              :style="{ width: `${50 + (i % 3) * 16}%` }"
            />
            <div
              class="skel-line short"
              :style="{ width: `${30 + (i % 2) * 20}%` }"
            />
          </div>
        </div>
      </div>

      <!-- 会话详情 -->
      <template v-else-if="detail">
        <!-- 卷宗头:标题 + Agent + 元信息 + 操作 -->
        <header class="dossier-head">
          <div class="dossier-left">
            <span class="dossier-eyebrow">
              <component
                :is="agentIcon"
                :size="12"
              />
              {{ agentLabel }}
            </span>
            <h1 class="dossier-title">{{ detail.title || '新的对话' }}</h1>
            <div class="dossier-meta">
              <span class="meta-item">
                <Clock3 :size="12" />
                创建于 {{ formatDateTime(detail.created_at) }}
              </span>
              <span class="meta-dot">·</span>
              <span class="meta-item">
                <MessageSquareText :size="12" />
                {{ detail.message_count }} 条消息
              </span>
              <span
                v-if="detail.summary"
                class="meta-dot"
              >·</span>
              <span
                v-if="detail.summary"
                class="meta-item summary"
              >{{ detail.summary }}</span>
            </div>
          </div>
          <div class="dossier-actions">
            <el-tooltip
              content="在 AI 问答中继续"
              placement="bottom"
            >
              <button
                type="button"
                class="icon-btn"
                @click="continueInAssistant"
              >
                <MessagesSquare :size="15" />
              </button>
            </el-tooltip>
            <el-tooltip
              content="删除会话"
              placement="bottom"
            >
              <button
                type="button"
                class="icon-btn danger"
                :disabled="deleting"
                @click="handleDelete(detail)"
              >
                <Trash2 :size="15" />
              </button>
            </el-tooltip>
          </div>
        </header>

        <!-- 消息流 -->
        <div
          ref="streamRef"
          class="dossier-stream"
        >
          <!-- 加载更早消息 -->
          <div
            v-if="hasMore"
            class="load-more"
          >
            <button
              type="button"
              class="load-more-btn"
              :disabled="loadingMore"
              @click="loadEarlier"
            >
              <ChevronsUp :size="14" />
              {{ loadingMore ? '加载中…' : '加载更早消息' }}
            </button>
          </div>

          <div
            v-if="messages.length === 0"
            class="no-messages"
          >
            <MessageCircleDashed :size="28" />
            <p>该会话暂无消息记录</p>
          </div>

          <div
            v-else
            class="stream-inner"
          >
            <ChatMessage
              v-for="(msg, idx) in messages"
              :key="msg.id || `msg-${idx}`"
              :message="msg"
              @feedback="(fb) => handleFeedback(msg, fb)"
              @trace="handleTrace"
              @copy="handleCopy"
            />
          </div>
        </div>
      </template>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Archive,
  BriefcaseBusiness,
  ChevronsUp,
  Clock3,
  FileSearch,
  MessageCircleDashed,
  MessagesSquare,
  Scale,
  MessageSquareText,
  Search,
  Trash2,
} from 'lucide-vue-next'

import HistoryConversationList from './components/HistoryConversationList.vue'
import ChatMessage from '@/pages/assistant/components/ChatMessage.vue'
import {
  deleteConversation,
  feedbackMessage,
  getConversation,
  listConversations,
  listMessages,
} from '@/api/conversation'
import { formatDateTime } from '@/utils/format'
import type {
  AgentType,
  Citation,
  Conversation,
  ConversationDetail,
  ConversationMessage,
  MessageFeedback,
} from '@/types/conversation'

const router = useRouter()

// ===== 会话列表状态 =====
const conversations = ref<Conversation[]>([])
const listLoading = ref(false)

// ===== 当前会话详情状态 =====
const selectedId = ref<string | null>(null)
const detail = ref<ConversationDetail | null>(null)
const messages = ref<ConversationMessage[]>([])
const detailLoading = ref(false)
const deleting = ref(false)

// ===== 更早消息分页状态 =====
const loadingMore = ref(false)
const nextPage = ref(1)
const loadedIds = ref<Set<string>>(new Set())

// ===== DOM 引用 =====
const streamRef = ref<HTMLDivElement | null>(null)

// ===== 计算属性 =====
// Agent 类型中文映射。
const agentMeta: Record<AgentType, { label: string; icon: typeof Scale }> = {
  law_qa: { label: '法律咨询', icon: Scale },
  article_locate: { label: '法条定位', icon: Search },
  contract_review: { label: '合同审查', icon: BriefcaseBusiness },
  case_analysis: { label: '案例分析', icon: FileSearch },
}

const agentLabel = computed(() =>
  detail.value ? agentMeta[detail.value.agent_type]?.label ?? detail.value.agent_type : '',
)

const agentIcon = computed(() =>
  detail.value ? agentMeta[detail.value.agent_type]?.icon ?? Scale : Scale,
)

// 是否还有更早消息可加载。
const hasMore = computed(() => {
  if (!detail.value) return false
  return messages.value.length < detail.value.message_count
})

// ===== 生命周期 =====
onMounted(async () => {
  await loadConversations()
})

// ===== 数据加载 =====
async function loadConversations() {
  listLoading.value = true
  try {
    const data = await listConversations({ page: 1, page_size: 100 })
    conversations.value = data.items
    // 默认选中最近一条会话,提升首屏可读性。
    if (data.items.length > 0 && !selectedId.value) {
      await selectConversation(data.items[0])
    }
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '会话列表加载失败')
  } finally {
    listLoading.value = false
  }
}

async function selectConversation(conv: Conversation) {
  if (String(conv.id) === String(selectedId.value)) return
  selectedId.value = conv.id
  detail.value = null
  messages.value = []
  loadedIds.value = new Set()
  nextPage.value = 1
  detailLoading.value = true

  try {
    const data = await getConversation(conv.id)
    detail.value = data
    // getConversation 返回最近 50 条(按时间正序),直接渲染。
    messages.value = data.messages.map(normalizeMessage)
    messages.value.forEach((m) => loadedIds.value.add(m.id))
    // getConversation 给出最近 50 条,listMessages 从最旧开始翻页,故从第 2 页起才有未加载内容。
    nextPage.value = 2
    nextTick(() => streamRef.value?.scrollTo({ top: streamRef.value.scrollHeight }))
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '会话详情加载失败')
  } finally {
    detailLoading.value = false
  }
}

// 加载更早消息:翻 listMessages 页,按 id 去重后前置插入。
async function loadEarlier() {
  if (!selectedId.value || loadingMore.value || !hasMore.value) return
  loadingMore.value = true
  const prevScrollHeight = streamRef.value?.scrollHeight ?? 0
  try {
    const data = await listMessages(selectedId.value, { page: nextPage.value, page_size: 50 })
    const fresh = data.items
      .filter((m) => !loadedIds.value.has(m.id))
      .map(normalizeMessage)
    if (fresh.length > 0) {
      messages.value = [...fresh, ...messages.value]
      fresh.forEach((m) => loadedIds.value.add(m.id))
    }
    nextPage.value += 1
    // 保持视觉位置:加载后回滚到原底部锚点。
    nextTick(() => {
      if (streamRef.value) {
        const delta = streamRef.value.scrollHeight - prevScrollHeight
        streamRef.value.scrollTop = delta
      }
    })
    if (fresh.length === 0) {
      ElMessage.info('没有更早的消息了')
    }
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '加载更早消息失败')
  } finally {
    loadingMore.value = false
  }
}

// ===== 消息反馈 =====
async function handleFeedback(msg: ConversationMessage, feedback: Exclude<MessageFeedback, null>) {
  if (!msg.id) return
  // 乐观更新,失败回滚。
  const prev = msg.feedback
  msg.feedback = feedback
  try {
    await feedbackMessage(msg.conversation_id, msg.id, feedback)
    ElMessage.success(feedback === 'like' ? '感谢反馈' : '已记录改进建议')
  } catch (err) {
    msg.feedback = prev
    ElMessage.error(err instanceof Error ? err.message : '反馈失败')
  }
}

// ===== 删除会话 =====
async function handleDelete(conv: Conversation) {
  deleting.value = true
  try {
    await deleteConversation(conv.id)
    ElMessage.success('会话已删除')
    // 若删除的是当前选中会话,清空右侧并尝试选中下一条。
    if (String(conv.id) === String(selectedId.value)) {
      selectedId.value = null
      detail.value = null
      messages.value = []
      loadedIds.value = new Set()
    }
    await loadConversations()
    // 列表刷新后若右侧为空且有剩余会话,自动选中第一条。
    if (!selectedId.value && conversations.value.length > 0) {
      await selectConversation(conversations.value[0])
    }
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '删除失败')
  } finally {
    deleting.value = false
  }
}

// ===== 复制与检索链路 =====
async function handleCopy(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.error('复制失败,请手动选择文本')
  }
}

function handleTrace(traceId: string) {
  const url = `/api/retrieve/trace/${traceId}`
  window.open(url, '_blank')
}

// 跳转到 AI 问答页继续该会话。
function continueInAssistant() {
  if (!selectedId.value) return
  router.push({ path: '/assistant', query: { conversation_id: selectedId.value } })
}

// ===== 工具函数 =====
// 后端消息的 citations 可能是 {"items": [...]}、[...] 或 null,统一规整。
function normalizeMessage(msg: ConversationMessage): ConversationMessage {
  if (msg.citations && Array.isArray((msg.citations as { items?: Citation[] }).items)) {
    return msg
  }
  if (Array.isArray(msg.citations)) {
    return { ...msg, citations: { items: msg.citations as Citation[] } }
  }
  return msg
}
</script>

<style scoped>
.history-page {
  display: flex;
  gap: 16px;
  height: calc(100vh - 120px);
}

/* ===== 右侧详情区 ===== */
.history-detail {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: var(--law-card);
  border: 1px solid var(--law-border);
  border-radius: var(--law-radius-card);
  box-shadow: var(--law-shadow);
  overflow: hidden;
}

/* 空态 */
.detail-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px 20px;
  text-align: center;
}

.empty-mark {
  width: 76px;
  height: 76px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 22px;
  background: linear-gradient(135deg, rgb(37 99 235 / 10%) 0%, rgb(30 64 175 / 6%) 100%);
  color: var(--law-primary-strong);
  margin-bottom: 12px;
}

.empty-title {
  margin: 0;
  font-family: 'Cormorant Garamond', 'Noto Serif SC', serif;
  font-size: 24px;
  font-weight: 700;
  color: var(--law-text);
  letter-spacing: 0.01em;
}

.empty-sub {
  max-width: 420px;
  margin: 0;
  font-size: 13px;
  line-height: 1.8;
  color: var(--law-muted);
}

/* 加载骨架 */
.detail-loading {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 22px;
  padding: 28px 28px;
}

.skeleton-row {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.skel-avatar {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  background: rgb(15 23 42 / 6%);
  flex-shrink: 0;
}

:global(html.dark) .skel-avatar {
  background: rgb(255 255 255 / 6%);
}

.skel-lines {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-top: 4px;
}

.skel-line {
  height: 12px;
  border-radius: 6px;
  background: rgb(15 23 42 / 6%);
  animation: skel-pulse 1.6s ease-in-out infinite;
}

:global(html.dark) .skel-line {
  background: rgb(255 255 255 / 6%);
}

.skel-line.short {
  height: 10px;
}

@keyframes skel-pulse {
  0%,
  100% {
    opacity: 0.55;
  }
  50% {
    opacity: 0.9;
  }
}

/* ===== 卷宗头 ===== */
.dossier-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 24px;
  border-bottom: 1px solid var(--law-border);
  background: linear-gradient(180deg, var(--law-card) 0%, rgb(37 99 235 / 4%) 100%);
}

.dossier-left {
  flex: 1;
  min-width: 0;
}

.dossier-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgb(37 99 235 / 10%);
  color: var(--law-primary-strong);
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.dossier-title {
  margin: 8px 0 6px;
  font-family: 'Cormorant Garamond', 'Noto Serif SC', serif;
  font-size: 24px;
  font-weight: 700;
  color: var(--law-text);
  letter-spacing: 0.01em;
  line-height: 1.3;
  word-break: break-word;
}

.dossier-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--law-muted);
}

.meta-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.meta-item.summary {
  max-width: 420px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.meta-dot {
  opacity: 0.5;
}

.dossier-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: 1px solid var(--law-border);
  border-radius: 10px;
  background: var(--law-card);
  color: var(--law-muted);
  cursor: pointer;
  transition: all 160ms ease;
}

.icon-btn:hover:not(:disabled) {
  border-color: var(--law-primary);
  color: var(--law-primary-strong);
  background: rgb(37 99 235 / 6%);
}

.icon-btn.danger:hover:not(:disabled) {
  border-color: rgb(239 68 68 / 50%);
  color: rgb(220 38 38);
  background: rgb(239 68 68 / 8%);
}

.icon-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ===== 消息流 ===== */
.dossier-stream {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 20px 24px 12px;
  scroll-behavior: smooth;
}

.dossier-stream::-webkit-scrollbar {
  width: 8px;
}

.dossier-stream::-webkit-scrollbar-thumb {
  background: rgb(15 23 42 / 12%);
  border-radius: 4px;
}

:global(html.dark) .dossier-stream::-webkit-scrollbar-thumb {
  background: rgb(255 255 255 / 12%);
}

.load-more {
  display: flex;
  justify-content: center;
  padding: 4px 0 18px;
}

.load-more-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 16px;
  border: 1px solid var(--law-border);
  border-radius: 999px;
  background: var(--law-card);
  color: var(--law-muted);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 160ms ease;
}

.load-more-btn:hover:not(:disabled) {
  border-color: var(--law-primary);
  color: var(--law-primary-strong);
  background: rgb(37 99 235 / 6%);
}

.load-more-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.no-messages {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 60px 20px;
  color: var(--law-muted);
}

.no-messages :deep(svg) {
  opacity: 0.4;
}

.no-messages p {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
}

.stream-inner {
  display: flex;
  flex-direction: column;
  gap: 22px;
  max-width: 980px;
  margin: 0 auto;
}

/* ===== 响应式 ===== */
@media (max-width: 960px) {
  .history-page {
    flex-direction: column;
    height: auto;
    min-height: calc(100vh - 120px);
  }

  .history-detail {
    min-height: 520px;
  }

  .dossier-head {
    padding: 14px 16px;
  }

  .dossier-title {
    font-size: 20px;
  }

  .dossier-stream {
    padding: 16px 12px 12px;
  }
}
</style>
