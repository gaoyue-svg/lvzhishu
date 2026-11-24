<!-- 最近检索组件，展示用户近期检索行为与命中数量。 -->
<template>
  <SectionPanel
    title="最近检索记录"
    description="可快速回到历史检索上下文"
  >
    <div class="record-list">
      <button
        v-for="record in records"
        :key="record.id"
        class="record-row"
        type="button"
        @click="copy(record.keyword)"
      >
        <span class="record-icon"><Search :size="16" /></span>
        <span class="record-main">
          <strong>{{ record.keyword }}</strong>
          <small>{{ record.scope }} · {{ record.count }} 条结果</small>
        </span>
        <time>{{ record.time }}</time>
      </button>
    </div>
  </SectionPanel>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { Search } from 'lucide-vue-next'

import SectionPanel from './SectionPanel.vue'
import type { SearchRecord } from '@/types/dashboard'

defineProps<{
  records: SearchRecord[]
}>()

function copy(keyword: string) {
  ElMessage.success(`已载入检索词：${keyword}`)
}
</script>

<style scoped>
.record-list {
  display: grid;
  gap: 10px;
}

.record-row {
  width: 100%;
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  padding: 11px 0;
  border: 0;
  border-bottom: 1px solid var(--law-border);
  color: var(--law-text);
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.record-row:last-child {
  border-bottom: 0;
}

.record-icon {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  color: var(--law-primary);
  background: var(--law-primary-soft);
}

.record-main {
  min-width: 0;
  display: grid;
  gap: 4px;
}

.record-main strong,
.record-main small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.record-main strong {
  font-size: 14px;
}

.record-main small,
.record-row time {
  color: var(--law-muted);
  font-size: 12px;
}
</style>
