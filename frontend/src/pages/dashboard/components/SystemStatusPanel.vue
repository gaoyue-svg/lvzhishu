<!-- 系统状态组件，展示检索、向量化和解析链路健康度。 -->
<template>
  <SectionPanel
    title="系统状态"
    description="核心服务健康度与队列情况"
  >
    <div class="status-list">
      <article
        v-for="item in statuses"
        :key="item.label"
        class="status-item"
      >
        <div class="status-head">
          <span>{{ item.label }}</span>
          <strong>{{ item.hasData === false ? '—' : `${item.value}%` }}</strong>
        </div>
        <el-progress
          :percentage="item.value"
          :color="item.color"
          :stroke-width="8"
          :show-text="false"
        />
        <p>{{ item.description }}</p>
      </article>
    </div>
  </SectionPanel>
</template>

<script setup lang="ts">
import SectionPanel from './SectionPanel.vue'
import type { SystemStatus } from '@/types/dashboard'

defineProps<{
  statuses: SystemStatus[]
}>()
</script>

<style scoped>
.status-list {
  display: grid;
  gap: 16px;
}

.status-item {
  display: grid;
  gap: 9px;
}

.status-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.status-head span {
  color: var(--law-text);
  font-size: 14px;
  font-weight: 700;
}

.status-head strong {
  font-size: 14px;
}

.status-item p {
  margin: 0;
  color: var(--law-muted);
  font-size: 12px;
}
</style>
