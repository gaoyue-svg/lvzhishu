<!-- 评分条：0~1 数值的横向进度条，按好坏分级着色。 -->
<template>
  <div class="mc-score">
    <div
      v-for="item in items"
      :key="item.label"
      class="mc-score__row"
    >
      <span class="mc-score__name">{{ item.label }}</span>
      <div class="mc-score__track">
        <div
          class="mc-score__fill"
          :class="item.tone"
          :style="{ width: `${percent(item.value)}%` }"
        />
      </div>
      <span class="mc-score__value">{{ item.displayText }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import { scoreTone } from '../utils'

interface ScoreItem {
  label: string
  value: number | null
  display?: (value: number | null) => string
}

const props = defineProps<{
  scores: ScoreItem[]
}>()

const items = computed(() =>
  props.scores.map((item) => ({
    ...item,
    tone: scoreTone(item.value),
    displayText: item.display
      ? item.display(item.value)
      : item.value == null
        ? '—'
        : (item.value * 100).toFixed(0),
  })),
)

function percent(value: number | null): number {
  if (value == null) return 0
  return Math.max(0, Math.min(100, value * 100))
}
</script>
