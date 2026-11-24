<!-- 统计卡片组件，展示单个核心业务指标与趋势。 -->
<template>
  <article class="stat-card">
    <div
      class="stat-icon"
      :class="stat.status"
    >
      <component
        :is="icon"
        :size="21"
      />
    </div>
    <div class="stat-body">
      <span>{{ stat.label }}</span>
      <strong>{{ stat.value }}<em>{{ stat.unit }}</em></strong>
    </div>
    <el-tag
      :type="tagType"
      effect="light"
      round
    >
      {{ stat.trend }}
    </el-tag>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Bot, FileText, FolderOpen, Search } from 'lucide-vue-next'

import type { StatItem } from '@/types/dashboard'

const props = defineProps<{
  stat: StatItem
}>()

const iconMap = {
  aiCalls: Bot,
  knowledgeBases: FolderOpen,
  legalDocuments: FileText,
  legalSearches: Search,
}

const icon = computed(() => iconMap[props.stat.key as keyof typeof iconMap] ?? Bot)
const tagType = computed(() => (props.stat.status === 'up' ? 'success' : props.stat.status === 'down' ? 'danger' : 'info'))
</script>

<style scoped>
.stat-card {
  min-width: 0;
  display: grid;
  grid-template-columns: 48px minmax(0, 1fr) auto;
  gap: 14px;
  align-items: center;
  padding: 19px;
  border: 1px solid var(--law-border);
  border-radius: 20px;
  background: var(--law-card);
  box-shadow: var(--law-shadow);
  transition:
    transform 180ms ease,
    border-color 180ms ease;
}

.stat-card:hover {
  transform: translateY(-3px);
  border-color: rgba(30, 58, 95, 0.28);
  box-shadow: 0 15px 32px rgba(15, 38, 68, 0.1);
}

.stat-icon {
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  color: var(--law-primary);
  background: var(--law-primary-soft);
}

.stat-icon.up,
.stat-icon.stable {
  color: var(--law-primary);
  background: var(--law-primary-soft);
}

.stat-body {
  min-width: 0;
  display: grid;
  gap: 4px;
}

.stat-body span {
  color: var(--law-muted);
  font-size: 13px;
}

.stat-body strong {
  font-size: 24px;
  line-height: 1.1;
}

.stat-body em {
  margin-left: 3px;
  color: var(--law-muted);
  font-size: 13px;
  font-style: normal;
  font-weight: 600;
}
</style>
