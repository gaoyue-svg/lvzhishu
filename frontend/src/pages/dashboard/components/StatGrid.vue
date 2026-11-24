<!-- 统计网格组件，组织今日核心指标卡片。 -->
<template>
  <div class="stat-grid">
    <StatCard
      v-for="stat in stats"
      :key="stat.key"
      :stat="stat"
    />
  </div>
</template>

<script setup lang="ts">
import StatCard from './StatCard.vue'
import type { StatItem } from '@/types/dashboard'

defineProps<{
  stats: StatItem[]
}>()
</script>

<style scoped>
.stat-grid {
  width: 100%;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

@media (max-width: 1180px) {
  .stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .stat-grid {
    grid-template-columns: 1fr;
  }
}
</style>
