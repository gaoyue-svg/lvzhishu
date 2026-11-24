<!-- 状态指示灯：可呼吸闪烁的圆点，用于面板/行首/标题旁的状态标识。 -->
<template>
  <span
    class="mc-led"
    :class="[`tone-${tone}`, { 'is-pulse': pulse }]"
  />
</template>

<script setup lang="ts">
type LedTone = 'green' | 'red' | 'amber' | 'cyan' | 'violet' | 'blue' | 'gray'

withDefaults(
  defineProps<{
    tone?: LedTone
    pulse?: boolean
  }>(),
  { tone: 'gray', pulse: false },
)
</script>
