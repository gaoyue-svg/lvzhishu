<!--
  本文件是知识库卡片组件:
  - 展示单个知识库的类型徽章、名称、描述与文档/Chunk 统计
  - 承载点击进入详情的跳转,并提供删除入口(通过 emit 交由父组件确认)
-->
<template>
  <article
    class="kb-card"
    :class="{ disabled: kb.status === 'disabled' }"
    @click="goDetail"
  >
    <header class="card-top">
      <div
        class="type-badge"
        :style="{ color: meta.color, background: meta.soft }"
      >
        <component
          :is="meta.icon"
          :size="20"
        />
      </div>
      <!-- 卡片操作区:重命名与删除,均阻止冒泡避免触发卡片跳转;具体确认与调用由父组件处理 -->
      <div class="card-actions">
        <el-tooltip
          content="重命名"
          placement="top"
        >
          <el-button
            class="rename-btn"
            circle
            text
            :icon="Pencil"
            @click.stop="emit('rename', kb)"
          />
        </el-tooltip>
        <el-tooltip
          content="删除知识库"
          placement="top"
        >
          <el-button
            class="delete-btn"
            circle
            text
            :icon="Trash2"
            @click.stop="emit('delete', kb)"
          />
        </el-tooltip>
      </div>
    </header>

    <div class="card-body">
      <div class="card-title-row">
        <h3>{{ kb.name }}</h3>
        <span
          class="status-dot"
          :class="kb.status"
        />
      </div>
      <p class="card-desc">
        {{ kb.description || '暂无描述' }}
      </p>

      <div class="card-meta">
        <span class="meta-tag">{{ meta.label }}</span>
        <span class="meta-divider" />
        <span>{{ formatFileSize(kb.total_size) }}</span>
      </div>

      <div class="card-stats">
        <div class="stat-cell">
          <strong>{{ kb.doc_count }}</strong>
          <small>文档</small>
        </div>
        <div class="stat-cell">
          <strong>{{ kb.chunk_count }}</strong>
          <small>Chunk</small>
        </div>
      </div>
    </div>

    <footer class="card-foot">
      <span class="foot-date">
        <Calendar :size="13" />
        {{ formatDate(kb.created_at) }}
      </span>
      <span class="foot-enter">
        进入
        <ArrowRight :size="14" />
      </span>
    </footer>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, Calendar, Pencil, Trash2 } from 'lucide-vue-next'

import { getKBTypeMeta } from '../kb-meta'
import { formatDate, formatFileSize } from '@/utils/format'
import type { KnowledgeBase } from '@/types/kb'

const props = defineProps<{
  kb: KnowledgeBase
}>()

// 暴露 delete / rename 事件给父组件,由父组件负责确认弹窗与 API 调用。
const emit = defineEmits<{
  (event: 'delete', kb: KnowledgeBase): void
  (event: 'rename', kb: KnowledgeBase): void
}>()

const router = useRouter()
const meta = computed(() => getKBTypeMeta(props.kb.kb_type))

function goDetail() {
  if (props.kb.status === 'disabled') return
  router.push(`/knowledge/${props.kb.id}`)
}
</script>

<style scoped>
.kb-card {
  position: relative;
  display: flex;
  flex-direction: column;
  padding: 18px;
  border: 1px solid var(--law-border);
  border-radius: 18px;
  background: var(--law-card);
  box-shadow: var(--law-shadow);
  cursor: pointer;
  transition:
    transform 200ms ease,
    border-color 200ms ease,
    box-shadow 200ms ease;
}

.kb-card:hover {
  transform: translateY(-4px);
  border-color: rgb(37 99 235 / 32%);
  box-shadow: 0 26px 56px rgb(15 23 42 / 12%);
}

.kb-card.disabled {
  cursor: not-allowed;
  opacity: 0.78;
}

.kb-card.disabled:hover {
  transform: none;
  border-color: var(--law-border);
}

.card-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 14px;
}

/* 删除按钮:默认低对比度,卡片 hover 时高亮,避免误触 */
.delete-btn {
  color: var(--law-muted);
  opacity: 0.55;
  transition:
    opacity 180ms ease,
    color 180ms ease;
}

.delete-btn:hover {
  opacity: 1;
  color: var(--el-color-danger, #ef4444);
}

.kb-card:hover .delete-btn {
  opacity: 0.85;
}

/* 操作按钮容器:让重命名与删除按钮紧凑排列 */
.card-actions {
  display: flex;
  align-items: center;
  gap: 2px;
}

/* 重命名按钮:复用删除按钮的低对比度策略,hover 时改用主色 */
.rename-btn {
  color: var(--law-muted);
  opacity: 0.55;
  transition:
    opacity 180ms ease,
    color 180ms ease;
}

.rename-btn:hover {
  opacity: 1;
  color: var(--law-primary);
}

.kb-card:hover .rename-btn {
  opacity: 0.85;
}

.type-badge {
  width: 46px;
  height: 46px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 14px;
}

.card-body {
  flex: 1;
  min-width: 0;
}

.card-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.card-title-row h3 {
  flex: 1;
  min-width: 0;
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 16px;
  font-weight: 700;
  color: var(--law-text);
}

.status-dot {
  width: 8px;
  height: 8px;
  flex-shrink: 0;
  border-radius: 999px;
  background: #cbd5e1;
}

.status-dot.enabled {
  background: #22c55e;
  box-shadow: 0 0 0 3px rgb(34 197 94 / 18%);
}

.status-dot.disabled {
  background: #94a3b8;
}

.card-desc {
  margin: 6px 0 14px;
  color: var(--law-muted);
  font-size: 13px;
  line-height: 1.6;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  min-height: 42px;
}

.card-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  color: var(--law-muted);
  font-size: 12px;
}

.meta-tag {
  padding: 3px 10px;
  border-radius: 999px;
  background: #f1f5f9;
  color: var(--law-text);
  font-weight: 600;
}

:global(html.dark) .meta-tag {
  background: var(--law-card-soft);
}

.meta-divider {
  width: 4px;
  height: 4px;
  border-radius: 999px;
  background: #cbd5e1;
}

.card-stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  padding: 12px 0;
  border-top: 1px dashed var(--law-border);
  border-bottom: 1px dashed var(--law-border);
}

.stat-cell {
  display: grid;
  gap: 3px;
}

.stat-cell strong {
  font-size: 18px;
  font-weight: 700;
  color: var(--law-text);
  line-height: 1.1;
}

.stat-cell small {
  color: var(--law-muted);
  font-size: 11px;
}

.card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 14px;
  color: var(--law-muted);
  font-size: 12px;
}

.foot-date {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.foot-enter {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--law-primary);
  font-weight: 600;
  transition: gap 180ms ease;
}

.kb-card:hover .foot-enter {
  gap: 8px;
}
</style>
