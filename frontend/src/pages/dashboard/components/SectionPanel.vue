<!-- 通用面板组件，为 Dashboard 各信息区块提供一致标题与容器样式。 -->
<template>
  <section class="section-panel">
    <header class="panel-header">
      <div>
        <h2>{{ title }}</h2>
        <p v-if="description">
          {{ description }}
        </p>
      </div>
      <slot name="action" />
    </header>
    <slot />
  </section>
</template>

<script setup lang="ts">
defineProps<{
  title: string
  description?: string
}>()
</script>

<style scoped>
.section-panel {
  min-width: 0;
  padding: 18px;
  border: 1px solid var(--law-border);
  border-radius: 16px;
  background: var(--law-card);
  box-shadow: var(--law-shadow);
}

.panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 16px;
}

.panel-header h2 {
  margin: 0;
  color: var(--law-text);
  font-size: 16px;
  font-weight: 800;
  line-height: 1.35;
}

.panel-header p {
  margin: 4px 0 0;
  color: var(--law-muted);
  font-size: 13px;
  line-height: 1.5;
}
</style>
