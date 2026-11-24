<!--
  会话侧边栏组件:
  - 展示当前用户的会话列表,支持新建对话、切换、删除
  - 顶部固定品牌区,中间滚动会话列表,底部固定折叠/新建按钮
  - 删除走二次确认,软删除后从列表移除
-->
<template>
  <aside
    class="assistant-sidebar"
    :class="{ collapsed: props.collapsed }"
  >
    <!-- 顶部品牌 + 新建按钮 -->
    <div class="sidebar-top">
      <div class="brand-row">
        <div class="brand-mark">
          <img
            :src="brandLogo"
            alt="律智枢 天秤与法槌"
          />
        </div>
        <div class="brand-text">
          <span class="brand-title">律智枢</span>
          <span class="brand-sub">法律智能助手</span>
        </div>
      </div>
      <div class="top-actions">
        <button
          type="button"
          class="new-chat-btn"
          :disabled="loading"
          @click="$emit('new')"
        >
          <Plus :size="14" />
          新建对话
        </button>
        <button
          type="button"
          class="collapse-btn"
          title="收起会话侧栏"
          @click="emit('toggleCollapse')"
        >
          <PanelLeftClose :size="15" />
        </button>
      </div>
    </div>

    <!-- 搜索框 -->
    <div class="sidebar-search">
      <Search :size="13" />
      <input
        v-model="keyword"
        type="text"
        placeholder="搜索会话标题"
        class="search-input"
      >
    </div>

    <!-- 会话列表 -->
    <div
      v-loading="loading"
      class="sidebar-list"
    >
      <div
        v-if="!loading && filteredList.length === 0"
        class="empty-state"
      >
        <MessageCircleDashed :size="28" />
        <p>{{ keyword ? '没有匹配的会话' : '还没有会话记录' }}</p>
        <span>{{ keyword ? '换个关键词试试' : '点击上方按钮开始第一个对话' }}</span>
      </div>

      <div
        v-for="conv in filteredList"
        :key="conv.id"
        class="conv-item"
        role="button"
        tabindex="0"
        :class="{ active: String(conv.id) === String(activeId) }"
        @click="$emit('select', conv)"
        @keydown.enter.prevent="$emit('select', conv)"
        @keydown.space.prevent="$emit('select', conv)"
      >
        <div class="conv-icon">
          <MessageSquare :size="14" />
        </div>
        <div class="conv-main">
          <div class="conv-title-row">
            <span class="conv-title">{{ conv.title || '新的对话' }}</span>
            <span
              class="conv-agent"
              :class="conv.agent_type"
            >{{ agentLabel(conv.agent_type) }}</span>
          </div>
          <div class="conv-meta">
            <Clock3 :size="11" />
            <span>{{ relativeTime(conv.updated_at) }}</span>
            <span class="dot">·</span>
            <span>{{ conv.message_count }} 条</span>
          </div>
        </div>
        <button
          type="button"
          class="conv-delete"
          title="删除会话"
          @click.stop="confirmDelete(conv)"
        >
          <Trash2 :size="13" />
        </button>
      </div>
    </div>

    <!-- 底部信息 -->
    <div class="sidebar-foot">
      <div class="foot-tip">
        <Info :size="12" />
        <span>回答仅供参考,重大事项请咨询专业律师</span>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import {
  Clock3,
  Info,
  MessageCircleDashed,
  MessageSquare,
  PanelLeftClose,
  Plus,
  Search,
  Trash2,
} from 'lucide-vue-next'

import brandLogo from '@/assets/brand/lawagent-balance-gavel-v3.png'
import type { AgentType, Conversation } from '@/types/conversation'

const props = defineProps<{
  conversations: Conversation[]
  activeId: string | number | null
  loading: boolean
  collapsed?: boolean
}>()

const emit = defineEmits<{
  new: []
  select: [conv: Conversation]
  delete: [conv: Conversation]
  toggleCollapse: []
}>()

const keyword = ref('')

// 关键词过滤会话列表。
const filteredList = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return props.conversations
  return props.conversations.filter((c) => (c.title || '').toLowerCase().includes(kw))
})

const agentMeta: Record<AgentType, string> = {
  law_qa: '咨询',
  article_locate: '法条',
  contract_review: '合同',
  case_analysis: '案例',
}

function agentLabel(t: string): string {
  return agentMeta[t as AgentType] ?? t
}

// 相对时间:"刚刚 / n分钟前 / n小时前 / MM-DD"。
function relativeTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const now = Date.now()
  const diff = now - d.getTime()
  const min = Math.floor(diff / 60000)
  if (min < 1) return '刚刚'
  if (min < 60) return `${min} 分钟前`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr} 小时前`
  const day = Math.floor(hr / 24)
  if (day < 7) return `${day} 天前`
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${mm}-${dd}`
}

async function confirmDelete(conv: Conversation) {
  try {
    await ElMessageBox.confirm(
      `确定删除会话「${conv.title || '新的对话'}」吗?将归档不再显示,但消息记录保留以供审计。`,
      '删除会话',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
      },
    )
    emit('delete', conv)
  } catch {
    // 用户取消,不做处理。
  }
}
</script>

<style scoped>
/* 浅色：白底侧栏，与主侧栏风格统一（Linear/Notion 风格）。
   深色：保留原深空渐变面板。 */
.assistant-sidebar {
  display: flex;
  flex-direction: column;
  width: 280px;
  height: 100%;
  background: var(--law-card);
  color: var(--law-text);
  flex-shrink: 0;
  border-right: 1px solid rgba(0, 0, 0, 0.06);
}

:global(html.dark) .assistant-sidebar {
  background: var(--law-sidebar);
  color: var(--law-text);
  border-right: 1px solid var(--law-border);
}

.sidebar-top {
  padding: 18px 16px 14px;
  border-bottom: 1px solid var(--law-border);
}

:global(html.dark) .sidebar-top {
  border-bottom-color: var(--law-border);
}

.brand-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}

.brand-mark {
  width: 36px;
  height: 36px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  background: linear-gradient(160deg, #ffffff 0%, #f5f7fb 100%);
  border: 1px solid rgba(201, 169, 110, 0.55);
  box-shadow:
    0 4px 14px rgba(15, 38, 68, 0.10),
    inset 0 1px 0 rgba(255, 255, 255, 1);
}

.brand-mark img {
  width: 26px;
  height: 26px;
  display: block;
  object-fit: contain;
}

:global(html.dark) .brand-mark {
  background: linear-gradient(145deg, #1e3a5f 0%, #0f2644 100%);
  border-color: rgba(201, 169, 110, 0.45);
  box-shadow:
    0 4px 14px rgba(15, 38, 68, 0.25),
    inset 0 1px 0 rgba(201, 169, 110, 0.25);
}

.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
}

.brand-title {
  font-family: 'Cormorant Garamond', 'Noto Serif SC', serif;
  font-size: 19px;
  font-weight: 700;
  color: var(--law-text);
  letter-spacing: 0.02em;
}

:global(html.dark) .brand-title {
  color: var(--law-text);
}

.brand-sub {
  font-size: 11px;
  color: var(--law-muted-soft);
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

:global(html.dark) .brand-sub {
  color: var(--law-muted-soft);
}

.new-chat-btn {
  width: 100%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 9px 12px;
  border: 1px solid var(--law-border);
  border-radius: 10px;
  background: var(--law-card);
  color: var(--law-text);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 180ms ease;
}

.new-chat-btn:hover:not(:disabled) {
  border-color: var(--law-primary);
  color: var(--law-primary);
  background: rgba(59, 130, 246, 0.06);
}

:global(html.dark) .new-chat-btn {
  background: rgba(255, 255, 255, 0.05);
  border-color: var(--law-border);
  color: var(--law-text);
}

:global(html.dark) .new-chat-btn:hover:not(:disabled) {
  background: rgba(59, 130, 246, 0.12);
  border-color: rgba(59, 130, 246, 0.30);
  color: var(--law-text);
}

.new-chat-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.sidebar-search {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 12px 16px 8px;
  padding: 7px 10px;
  border: 1px solid var(--law-border);
  border-radius: 9px;
  background: var(--law-bg);
}

:global(html.dark) .sidebar-search {
  background: rgba(255, 255, 255, 0.04);
  border-color: var(--law-border);
}

.sidebar-search :deep(svg) {
  color: var(--law-muted);
  flex-shrink: 0;
}

.search-input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  color: var(--law-text);
  font-size: 12.5px;
}

:global(html.dark) .search-input {
  color: var(--law-text);
}

.search-input::placeholder {
  color: var(--law-muted-soft);
}

:global(html.dark) .search-input::placeholder {
  color: var(--law-disabled);
}

.sidebar-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 4px 10px 8px;
}

.sidebar-list::-webkit-scrollbar {
  width: 6px;
}

.sidebar-list::-webkit-scrollbar-thumb {
  background: rgba(15, 23, 42, 0.12);
  border-radius: 3px;
}

:global(html.dark) .sidebar-list::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.08);
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 48px 16px;
  color: var(--law-muted);
  text-align: center;
}

:global(html.dark) .empty-state {
  color: var(--law-disabled);
}

.empty-state :deep(svg) {
  margin-bottom: 8px;
  opacity: 0.5;
}

.empty-state p {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--law-muted);
}

:global(html.dark) .empty-state p {
  color: var(--law-muted-soft);
}

.empty-state span {
  font-size: 11px;
  color: var(--law-muted-soft);
}

:global(html.dark) .empty-state span {
  color: var(--law-disabled);
}

.conv-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 10px 10px;
  margin: 2px 0;
  border: none;
  border-radius: 10px;
  background: transparent;
  color: inherit;
  font: inherit;
  cursor: pointer;
  text-align: left;
  transition: all 160ms ease;
  position: relative;
}

.conv-item:hover {
  background: rgba(59, 130, 246, 0.08);
}

:global(html.dark) .conv-item:hover {
  background: rgba(59, 130, 246, 0.10);
}

.conv-item.active {
  background: rgba(59, 130, 246, 0.12);
  box-shadow: inset 3px 0 0 var(--law-primary);
}

:global(html.dark) .conv-item.active {
  background: linear-gradient(90deg, rgba(59, 130, 246, 0.18) 0%, rgba(59, 130, 246, 0.05) 100%);
  box-shadow: inset 3px 0 0 var(--law-primary);
}

.conv-icon {
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: var(--law-bg);
  color: var(--law-muted);
  flex-shrink: 0;
}

:global(html.dark) .conv-icon {
  background: rgba(255, 255, 255, 0.05);
  color: var(--law-muted-soft);
}

.conv-item.active .conv-icon {
  background: rgba(59, 130, 246, 0.15);
  color: var(--law-primary);
}

:global(html.dark) .conv-item.active .conv-icon {
  background: rgba(59, 130, 246, 0.25);
  color: rgb(147 197 253);
}

.conv-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.conv-title-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.conv-title {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--law-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:global(html.dark) .conv-title {
  color: var(--law-text);
}

.conv-agent {
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(245, 158, 11, 0.12);
  color: rgb(180 83 9);
  font-size: 10px;
  font-weight: 700;
  flex-shrink: 0;
}

:global(html.dark) .conv-agent {
  background: rgba(245, 158, 11, 0.12);
  color: rgb(252 211 77);
}

.conv-agent.contract_review {
  background: rgba(168, 85, 247, 0.12);
  color: rgb(126 34 206);
}

:global(html.dark) .conv-agent.contract_review {
  background: rgba(168, 85, 247, 0.16);
  color: rgb(216 180 254);
}

.conv-agent.case_analysis {
  background: rgba(16, 185, 129, 0.12);
  color: rgb(5 122 85);
}

:global(html.dark) .conv-agent.case_analysis {
  background: rgba(16, 185, 129, 0.16);
  color: rgb(110 231 183);
}

.conv-agent.article_locate {
  background: rgba(59, 130, 246, 0.12);
  color: var(--law-primary-strong);
}

:global(html.dark) .conv-agent.article_locate {
  background: rgb(59 130 246 / 18%);
  color: #93c5fd;
}

.conv-meta {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 10.5px;
  color: var(--law-muted-soft);
}

:global(html.dark) .conv-meta {
  color: #64748b;
}

.conv-meta .dot {
  opacity: 0.6;
}

.conv-delete {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--law-muted-soft);
  cursor: pointer;
  opacity: 0;
  transition: all 160ms ease;
  flex-shrink: 0;
}

.conv-item:hover .conv-delete {
  opacity: 1;
}

.conv-delete:hover {
  background: rgba(239, 68, 68, 0.12);
  color: rgb(185 28 28);
}

:global(html.dark) .conv-delete:hover {
  background: rgb(239 68 68 / 16%);
  color: #fca5a5;
}

.sidebar-foot {
  padding: 10px 16px 14px;
  border-top: 1px solid var(--law-border);
}

:global(html.dark) .sidebar-foot {
  border-top-color: rgb(255 255 255 / 6%);
}

.foot-tip {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 10.5px;
  color: var(--law-muted);
  line-height: 1.5;
}

:global(html.dark) .foot-tip {
  color: #64748b;
}

.foot-tip :deep(svg) {
  flex-shrink: 0;
  margin-top: 1px;
  color: #f59e0b;
}

@media (max-width: 960px) {
  .assistant-sidebar {
    width: 100%;
    height: auto;
    max-height: 280px;
  }

  .sidebar-list {
    max-height: 180px;
  }
}

/* 顶栏操作组:新建对话 + 收起按钮并排。 */
.top-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.top-actions .new-chat-btn {
  flex: 1;
  margin-bottom: 0;
}

.collapse-btn {
  width: 32px;
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--law-border);
  border-radius: 10px;
  background: transparent;
  color: var(--law-muted);
  cursor: pointer;
  transition: all 180ms ease;
  flex-shrink: 0;
}

.collapse-btn:hover {
  color: var(--law-primary);
  border-color: var(--law-primary);
  background: rgba(30, 58, 95, 0.06);
}

:global(html.dark) .collapse-btn {
  color: var(--law-muted-soft);
}

:global(html.dark) .collapse-btn:hover {
  color: var(--law-text);
  background: rgba(59, 130, 246, 0.14);
  border-color: rgba(59, 130, 246, 0.3);
}

/* 收起状态:整个侧边栏折叠为 0 宽度。 */
.assistant-sidebar.collapsed {
  width: 0;
  min-width: 0;
  overflow: hidden;
  padding: 0;
  border: none;
}
</style>
