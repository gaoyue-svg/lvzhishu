<!--
  引用面板组件:展示 assistant 消息的法律引用列表。
  - 每条引用显示编号、法律名称、条号、层级路径、版本/生效日期
  - 点击引用卡片弹出大号详情弹窗，展示完整元信息 + 原文全文(full_text)
  - 设计为"法律脚注"风格,琥珀色编号呼应法律卷宗的视觉语言
-->
<template>
  <div class="citation-panel">
    <div class="panel-head">
      <span class="head-icon">
        <Quote :size="13" />
      </span>
      <span class="head-title">法律引用</span>
      <span class="head-count">{{ citations.length }}</span>
    </div>
    <div class="citation-list">
      <button
        v-for="(item, idx) in citations"
        :key="(item.chunk_id || '') + idx"
        type="button"
        class="citation-card"
        :data-cite-index="item.index ?? idx + 1"
        @click="openDetail(item)"
      >
        <div class="card-head">
          <span class="card-index">[{{ item.index ?? idx + 1 }}]</span>
          <span class="card-title">
            <Scale :size="12" />
            <span>{{ citationTitle(item) }}</span>
          </span>
          <span
            v-if="item.version"
            class="card-version"
          >{{ item.version }}</span>
          <span class="card-open-hint">
            <Expand :size="13" />
            查看全文
          </span>
        </div>
        <div class="card-meta">
          <span v-if="item.article_no">第 {{ item.article_no }} 条</span>
          <span v-if="item.hierarchy_path">{{ item.hierarchy_path }}</span>
          <span v-if="effectiveLabel(item)">{{ effectiveLabel(item) }}</span>
          <span
            v-if="item.page_start"
            class="card-page"
          >P.{{ item.page_start }}{{ item.page_end ? `-${item.page_end}` : '' }}</span>
        </div>
      </button>
    </div>

    <!-- 引用详情弹窗:大号展示完整元信息 + 原文全文 -->
    <el-dialog
      :model-value="detail != null"
      width="min(760px, 92vw)"
      top="8vh"
      append-to-body
      destroy-on-close
      class="cite-detail-dialog"
      @update:model-value="(v: boolean) => { if (!v) detail = null }"
      @closed="detail = null"
    >
      <template #header>
        <div
          v-if="detail"
          class="detail-head"
        >
          <span class="detail-index">[{{ detail.index ?? '' }}]</span>
          <span class="detail-title">{{ citationTitle(detail) }}</span>
          <span
            v-if="detail.version"
            class="card-version"
          >{{ detail.version }}</span>
        </div>
      </template>

      <div
        v-if="detail"
        class="detail-body"
      >
        <div class="detail-meta">
          <span v-if="detail.article_no">第 {{ detail.article_no }} 条</span>
          <span v-if="detail.hierarchy_path">{{ detail.hierarchy_path }}</span>
          <span v-if="effectiveLabel(detail)">{{ effectiveLabel(detail) }}</span>
          <span
            v-if="detail.page_start"
            class="card-page"
          >P.{{ detail.page_start }}{{ detail.page_end ? `-${detail.page_end}` : '' }}</span>
          <span
            v-if="detail.source_type === 'web' && detail.title"
            class="detail-source"
          >网络来源</span>
        </div>

        <div class="detail-text">
          {{ detail.full_text || detail.text || '（未提供原文片段）' }}
        </div>

        <div
          v-if="detail.source_type === 'web' && detail.url"
          class="detail-foot"
        >
          <a
            :href="detail.url"
            target="_blank"
            rel="noopener noreferrer"
            class="detail-link"
          >
            <ExternalLink :size="13" />
            查看原文
          </a>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { Expand, ExternalLink, Quote, Scale } from 'lucide-vue-next'

import type { Citation } from '@/types/conversation'

defineProps<{
  citations: Citation[]
}>()

// 当前弹窗展示的引用，null 表示关闭。
const detail = ref<Citation | null>(null)

function openDetail(item: Citation) {
  detail.value = item
}

// 引用标题:优先法律名,其次 hierarchy_path,最后回退为"网络来源"或"参考"。
function citationTitle(item: Citation): string {
  if (item.law_name) return item.law_name
  if (item.source_type === 'web' && item.title) return item.title
  if (item.hierarchy_path) return item.hierarchy_path
  return item.source_type === 'web' ? '网络来源' : '法律参考'
}

// 生效日期标签,后端 effective_date 是时间戳(秒或毫秒),统一兼容。
function effectiveLabel(item: Citation): string {
  if (!item.effective_date) return ''
  const ts = item.effective_date > 1e12 ? item.effective_date : item.effective_date * 1000
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ''
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 生效`
}
</script>

<style scoped>
.citation-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 12px;
}

.panel-head {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  font-weight: 700;
  color: rgb(180 83 9);
  letter-spacing: 0.04em;
}

:global(html.dark) .panel-head {
  color: rgb(252 211 77);
}

.head-icon {
  display: inline-flex;
  width: 20px;
  height: 20px;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  background: rgb(245 158 11 / 14%);
}

.head-count {
  padding: 1px 7px;
  border-radius: 999px;
  background: rgb(245 158 11 / 14%);
  color: rgb(180 83 9);
  font-size: 11px;
}

.citation-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 8px;
}

.citation-card {
  text-align: left;
  cursor: pointer;
  padding: 10px 12px;
  border: 1px solid var(--law-border);
  border-left: 3px solid rgb(245 158 11 / 60%);
  border-radius: 8px;
  background: var(--law-card);
  font: inherit;
  color: inherit;
  transition: all 180ms ease;
}

.citation-card:hover {
  border-left-color: rgb(245 158 11);
  box-shadow: 0 4px 14px rgb(245 158 11 / 12%);
  transform: translateY(-1px);
}

.citation-card.is-cite-highlight {
  border-color: rgb(245 158 11 / 70%);
  border-left-color: rgb(245 158 11);
  background: rgb(245 158 11 / 10%);
  box-shadow: 0 0 0 3px rgb(245 158 11 / 14%);
}

.card-head {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 13px;
  font-weight: 600;
  color: var(--law-text);
}

.card-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 26px;
  height: 20px;
  padding: 0 6px;
  border-radius: 6px;
  background: rgb(245 158 11 / 16%);
  color: rgb(180 83 9);
  font-size: 11px;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
}

:global(html.dark) .card-index {
  color: rgb(252 211 77);
}

.card-title {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-version {
  padding: 1px 6px;
  border-radius: 5px;
  background: rgb(37 99 235 / 10%);
  color: var(--law-primary-strong);
  font-size: 10px;
  font-weight: 700;
  white-space: nowrap;
}

.card-open-hint {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  flex-shrink: 0;
  color: rgb(180 83 9);
  font-size: 10.5px;
  font-weight: 700;
  opacity: 0.75;
  transition: opacity 160ms ease;
}

:global(html.dark) .card-open-hint {
  color: rgb(252 211 77);
}

.citation-card:hover .card-open-hint {
  opacity: 1;
}

.card-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  margin-top: 6px;
  font-size: 11px;
  color: var(--law-muted);
}

.card-page {
  margin-left: auto;
  padding: 0 6px;
  border-radius: 4px;
  background: rgb(15 23 42 / 6%);
  font-variant-numeric: tabular-nums;
}

:global(html.dark) .card-page {
  background: rgb(255 255 255 / 8%);
}

/* ---- 弹窗内部样式 ---- */
.detail-head {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding-right: 28px;
}

.detail-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 30px;
  height: 24px;
  padding: 0 7px;
  border-radius: 6px;
  background: rgb(245 158 11 / 16%);
  color: rgb(180 83 9);
  font-size: 12px;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
}

:global(html.dark) .detail-index {
  color: rgb(252 211 77);
}

.detail-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 15px;
  font-weight: 800;
  color: var(--law-text);
}

.detail-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.detail-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
  padding: 8px 12px;
  border-radius: 8px;
  background: rgb(245 158 11 / 7%);
  font-size: 12px;
  color: var(--law-muted);
}

.detail-source {
  padding: 0 6px;
  border-radius: 4px;
  background: rgb(37 99 235 / 10%);
  color: var(--law-primary-strong);
  font-weight: 700;
}

.detail-text {
  max-height: 60vh;
  overflow-y: auto;
  padding: 14px 16px;
  border: 1px solid var(--law-border);
  border-radius: 8px;
  background: var(--law-card);
  font-size: 13.5px;
  line-height: 1.9;
  color: var(--law-text);
  white-space: pre-wrap;
  word-break: break-word;
}

:global(html.dark) .detail-text {
  background: rgb(15 23 42 / 40%);
}

.detail-foot {
  display: flex;
  justify-content: flex-end;
}

.detail-link {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 12px;
  border: 1px solid rgb(37 99 235 / 35%);
  border-radius: 8px;
  color: var(--law-primary);
  font-size: 12px;
  font-weight: 700;
  text-decoration: none;
  transition: background 160ms ease, border-color 160ms ease;
}

.detail-link:hover {
  background: rgb(37 99 235 / 8%);
  border-color: var(--law-primary);
}
</style>
