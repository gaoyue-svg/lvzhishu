<!-- KPI 磁贴：单行标签 + 大号等宽数值 + 副文案，用于总览核心指标。 -->
<template>
  <div
    class="mc-kpi"
    :class="`tone-${tone}`"
  >
    <div class="mc-kpi__top">
      <span class="mc-kpi__label">{{ label }}</span>
      <StatusLed
        :tone="tone"
        :pulse="pulse"
      />
    </div>
    <div class="mc-kpi__value">
      {{ valueText }}
      <span
        v-if="unit"
        class="mc-kpi__unit"
      >{{ unit }}</span>
    </div>
    <div
      v-if="sub"
      class="mc-kpi__sub"
    >{{ sub }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import StatusLed from './StatusLed.vue'

type KpiTone = 'cyan' | 'green' | 'red' | 'amber' | 'violet' | 'blue'

const props = withDefaults(
  defineProps<{
    label: string
    value: string | number
    unit?: string
    sub?: string
    tone?: KpiTone
    pulse?: boolean
  }>(),
  { unit: '', sub: '', tone: 'cyan', pulse: false },
)

const valueText = computed(() => String(props.value))
</script>
