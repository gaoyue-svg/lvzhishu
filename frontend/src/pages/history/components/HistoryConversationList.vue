<!--
  历史会话左侧档案列表组件:
  - 搜索框(按标题过滤) + Agent 类型筛选 chips
  - 按更新时间做日期分组(今天/昨天/本周/更早),形如翻阅案件卷宗
  - 每条会话卡片含标题、摘要、Agent 徽标、消息数与相对时间
  - 删除走二次确认,软删除后由父组件刷新列表
-->
<template>
  <aside class="history-list">
    <!-- 顶部档案标题 -->
    <div class="list-head">
      <span class="head-eyebrow">
        <Archive :size="12" />
        ARCHIVE
      </span>
      <h2 class="head-title">历史会话</h2>
      <p class="head-sub">共 {{ conversations.length }} 条会话记录</p>
    </div>

    <!-- 搜索框 -->
    <div class="list-search">
      <Search :size="13" />
      <input
        v-model="keyword"
        type="text"
        placeholder="搜索会话标题或摘要"
        class="search-input"
      >
    </div>

    <!-- Agent 类型筛选 -->
    <div class="list-filter">
      <button
        v-for="f in filters"
        :key="f.value"
        type="button"
        class="filter-chip"
        :class="[`chip-${f.value}`, { active: activeFilter === f.value }]"
        @click="activeFilter = f.value"
      >
        <component
          :is="f.icon"
          :size="11"
        />
        {{ f.label }}
      </button>
    </div>

    <!-- 列表主体 -->
    <div
      v-loading="loading"
      class="list-body"
    >
      <!-- 空态 -->
      <div
        v-if="!loading && groupedItems.length === 0"
        class="empty-state"
      >
        <FileQuestion :size="32" />
        <p>{{ keyword || activeFilter !== 'all' ? '没有匹配的会话' : '还没有会话记录' }}</p>
        <span>{{ keyword || activeFilter !== 'all' ? '换个条件试试' : '前往 AI 智能问答开始对话' }}</span>
      </div>

      <!-- 日期分组 -->
      <div
        v-for="group in groupedItems"
        :key="group.label"
        class="date-group"
      >
        <div class="group-head">
          <span class="group-label">{{ group.label }}</span>
          <span class="group-count">{{ group.items.length }}</span>
          <span class="group-line" />
        </div>

        <div
          v-for="conv in group.items"
          :key="conv.id"
          role="button"
          tabindex="0"
          class="conv-card"
          :class="[`agent-${conv.agent_type}`, { active: String(conv.id) === String(activeId) }]"
          @click="$emit('select', conv)"
          @keydown.enter="$emit('select', conv)"
          @keydown.space.prevent="$emit('select', conv)"
        >
          <span class="card-accent" />
          <div class="card-main">
            <div class="card-title-row">
              <span class="card-title">{{ conv.title || '新的对话' }}</span>
              <span class="card-badge">{{ agentLabel(conv.agent_type) }}</span>
            </div>
            <p
              v-if="conv.summary"
              class="card-summary"
            >{{ conv.summary }}</p>
            <div class="card-meta">
              <Clock3 :size="11" />
              <span>{{ relativeTime(conv.updated_at) }}</span>
              <span class="dot">·</span>
              <MessageSquareText :size="11" />
              <span>{{ conv.message_count }} 条</span>
            </div>
          </div>
          <button
            type="button"
            class="card-delete"
            title="删除会话"
            @click.stop="confirmDelete(conv)"
          >
            <Trash2 :size="13" />
          </button>
        </div>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import {
  Archive,
  BriefcaseBusiness,
  Clock3,
  FileQuestion,
  FileSearch,
  MessageSquareText,
  Scale,
  Search,
  Trash2,
} from 'lucide-vue-next'
import type { Component } from 'vue'

import type { AgentType, Conversation } from '@/types/conversation'

const props = defineProps<{
  conversations: Conversation[]
  activeId: string | number | null
  loading: boolean
}>()

const emit = defineEmits<{
  select: [conv: Conversation]
  delete: [conv: Conversation]
}>()

// Agent 筛选项,all 表示全部。
interface FilterOption {
  value: 'all' | AgentType
  label: string
  icon: Component
}

const filters: FilterOption[] = [
  { value: 'all', label: '全部', icon: Archive },
  { value: 'law_qa', label: '咨询', icon: Scale },
  { value: 'article_locate', label: '法条', icon: FileSearch },
  { value: 'contract_review', label: '合同', icon: BriefcaseBusiness },
  { value: 'case_analysis', label: '案例', icon: FileSearch },
]

const keyword = ref('')
const activeFilter = ref<'all' | AgentType>('all')

// Agent 类型中文映射。
const agentMeta: Record<AgentType, string> = {
  law_qa: '法律咨询',
  article_locate: '法条定位',
  contract_review: '合同审查',
  case_analysis: '案例分析',
}

function agentLabel(t: string): string {
  return agentMeta[t as AgentType] ?? t
}

// 关键词 + Agent 类型双重过滤。
const filteredList = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return props.conversations.filter((c) => {
    if (activeFilter.value !== 'all' && c.agent_type !== activeFilter.value) return false
    if (!kw) return true
    const inTitle = (c.title || '').toLowerCase().includes(kw)
    const inSummary = (c.summary || '').toLowerCase().includes(kw)
    return inTitle || inSummary
  })
})

// 按更新时间分组:今天 / 昨天 / 本周 / 更早。
const groupedItems = computed(() => {
  const now = new Date()
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const day = 86400000
  const startYesterday = startToday - day
  const startWeek = startToday - 6 * day // 含今天在内的近 7 天

  const groups: { label: string; items: Conversation[] }[] = [
    { label: '今天', items: [] },
    { label: '昨天', items: [] },
    { label: '本周', items: [] },
    { label: '更早', items: [] },
  ]
  for (const c of filteredList.value) {
    const t = new Date(c.updated_at).getTime()
    if (Number.isNaN(t)) {
      groups[3].items.push(c)
    } else if (t >= startToday) {
      groups[0].items.push(c)
    } else if (t >= startYesterday) {
      groups[1].items.push(c)
    } else if (t >= startWeek) {
      groups[2].items.push(c)
    } else {
      groups[3].items.push(c)
    }
  }
  return groups.filter((g) => g.items.length > 0)
})

// 相对时间:"刚刚 / n分钟前 / n小时前 / n天前 / MM-DD"。
function relativeTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const diff = Date.now() - d.getTime()
  const min = Math.floor(diff / 60000)
  if (min < 1) return '刚刚'
  if (min < 60) return `${min} 分钟前`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr} 小时前`
  const dayN = Math.floor(hr / 24)
  if (dayN < 7) return `${dayN} 天前`
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
.history-list {
  display: flex;
  flex-direction: column;
  width: 320px;
  flex-shrink: 0;
  background: var(--law-card);
  border: 1px solid var(--law-border);
  border-radius: var(--law-radius-card);
  box-shadow: var(--law-shadow);
  overflow: hidden;
}

/* ===== 顶部档案标题 ===== */
.list-head {
  padding: 18px 18px 14px;
  border-bottom: 1px solid var(--law-border);
  background: linear-gradient(180deg, var(--law-card) 0%, rgb(37 99 235 / 4%) 100%);
}

.head-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.16em;
  color: var(--law-primary-strong);
  text-transform: uppercase;
}

.head-title {
  margin: 4px 0 2px;
  font-family: 'Cormorant Garamond', 'Noto Serif SC', serif;
  font-size: 22px;
  font-weight: 700;
  color: var(--law-text);
  letter-spacing: 0.01em;
}

.head-sub {
  margin: 0;
  font-size: 12px;
  color: var(--law-muted);
}

/* ===== 搜索框 ===== */
.list-search {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 14px 14px 8px;
  padding: 8px 11px;
  border: 1px solid var(--law-border);
  border-radius: 10px;
  background: var(--law-bg);
  transition: border-color 160ms ease;
}

.list-search:focus-within {
  border-color: var(--law-primary);
  box-shadow: 0 0 0 3px rgb(37 99 235 / 10%);
}

.list-search :deep(svg) {
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
  font-size: 13px;
}

.search-input::placeholder {
  color: var(--law-muted);
}

/* ===== Agent 筛选 ===== */
.list-filter {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 0 14px 12px;
  border-bottom: 1px solid var(--law-border);
}

.filter-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border: 1px solid var(--law-border);
  border-radius: 999px;
  background: var(--law-card);
  color: var(--law-muted);
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
  transition: all 160ms ease;
}

.filter-chip:hover {
  border-color: var(--law-primary);
  color: var(--law-primary-strong);
}

.filter-chip.active {
  background: var(--law-primary);
  border-color: var(--law-primary);
  color: #fff;
  box-shadow: 0 4px 12px rgb(37 99 235 / 24%);
}

/* ===== 列表主体 ===== */
.list-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 6px 10px 10px;
}

.list-body::-webkit-scrollbar {
  width: 6px;
}

.list-body::-webkit-scrollbar-thumb {
  background: rgb(15 23 42 / 12%);
  border-radius: 3px;
}

:global(html.dark) .list-body::-webkit-scrollbar-thumb {
  background: rgb(255 255 255 / 12%);
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 56px 20px;
  color: var(--law-muted);
  text-align: center;
}

.empty-state :deep(svg) {
  margin-bottom: 10px;
  opacity: 0.4;
}

.empty-state p {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--law-text);
}

.empty-state span {
  font-size: 11.5px;
  color: var(--law-muted);
}

/* ===== 日期分组 ===== */
.date-group {
  margin-bottom: 4px;
}

.group-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 6px 8px;
}

.group-label {
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: var(--law-muted);
  text-transform: uppercase;
}

.group-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 16px;
  padding: 0 5px;
  border-radius: 999px;
  background: rgb(15 23 42 / 6%);
  color: var(--law-muted);
  font-size: 10px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

:global(html.dark) .group-count {
  background: rgb(255 255 255 / 8%);
}

.group-line {
  flex: 1;
  height: 1px;
  background: var(--law-border);
}

/* ===== 会话卡片 ===== */
.conv-card {
  position: relative;
  display: flex;
  align-items: stretch;
  gap: 0;
  width: 100%;
  padding: 10px 10px 10px 0;
  margin: 3px 0;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  color: inherit;
  cursor: pointer;
  text-align: left;
  overflow: hidden;
  transition: all 160ms ease;
}

.conv-card:hover {
  background: var(--law-bg);
  border-color: var(--law-border);
}

.conv-card.active {
  background: rgb(37 99 235 / 6%);
  border-color: rgb(37 99 235 / 24%);
}

.card-accent {
  width: 3px;
  flex-shrink: 0;
  background: var(--law-muted);
  opacity: 0.3;
  margin-right: 10px;
}

.conv-card.agent-law_qa .card-accent {
  background: #2563eb;
  opacity: 0.7;
}

.conv-card.agent-article_locate .card-accent {
  background: #3b82f6;
  opacity: 0.7;
}

.conv-card.agent-contract_review .card-accent {
  background: #a855f7;
  opacity: 0.7;
}

.conv-card.agent-case_analysis .card-accent {
  background: #10b981;
  opacity: 0.7;
}

.conv-card.active .card-accent {
  opacity: 1;
}

.card-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.card-title-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.card-title {
  flex: 1;
  min-width: 0;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--law-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-badge {
  padding: 1px 7px;
  border-radius: 5px;
  background: rgb(245 158 11 / 16%);
  color: rgb(180 83 9);
  font-size: 10px;
  font-weight: 700;
  flex-shrink: 0;
}

:global(html.dark) .card-badge {
  color: rgb(252 211 77);
}

.conv-card.agent-contract_review .card-badge {
  background: rgb(168 85 247 / 18%);
  color: rgb(126 34 206);
}

:global(html.dark) .conv-card.agent-contract_review .card-badge {
  color: rgb(216 180 254);
}

.conv-card.agent-case_analysis .card-badge {
  background: rgb(16 185 129 / 18%);
  color: rgb(5 122 85);
}

:global(html.dark) .conv-card.agent-case_analysis .card-badge {
  color: rgb(110 231 183);
}

.conv-card.agent-article_locate .card-badge {
  background: rgb(59 130 246 / 18%);
  color: rgb(29 78 216);
}

:global(html.dark) .conv-card.agent-article_locate .card-badge {
  color: rgb(147 197 253);
}

.card-summary {
  margin: 0;
  font-size: 11.5px;
  line-height: 1.5;
  color: var(--law-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
}

.card-meta {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 10.5px;
  color: var(--law-muted);
  font-variant-numeric: tabular-nums;
}

.card-meta .dot {
  opacity: 0.5;
}

.card-delete {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  align-self: center;
  width: 26px;
  height: 26px;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--law-muted);
  cursor: pointer;
  opacity: 0;
  transition: all 160ms ease;
  flex-shrink: 0;
}

.conv-card:hover .card-delete {
  opacity: 1;
}

.card-delete:hover {
  background: rgb(239 68 68 / 12%);
  color: rgb(220 38 38);
}

@media (max-width: 960px) {
  .history-list {
    width: 100%;
    max-height: 340px;
  }

  .list-body {
    max-height: 220px;
  }
}
</style>
