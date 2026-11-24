<!-- 深色驾驶舱面板框架：带角标 + 头部标题 + 可选操作区。 -->
<template>
  <section class="mc-panel">
    <header
      v-if="title || $slots.actions"
      class="mc-panel__head"
    >
      <div class="mc-panel__title">
        <span class="mc-panel__tag" />
        <span>{{ title }}</span>
        <span
          v-if="meta"
          class="mc-panel__meta"
        >{{ meta }}</span>
      </div>
      <div class="mc-panel__actions">
        <slot name="actions" />
      </div>
    </header>
    <div class="mc-panel__body">
      <slot />
    </div>
  </section>
</template>

<script setup lang="ts">
defineProps<{
  title?: string
  meta?: string
}>()
</script>
