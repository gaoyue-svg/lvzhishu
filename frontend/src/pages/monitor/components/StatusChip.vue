<!-- 状态胶囊：run / step 状态徽标，语义色由 status 映射。 -->
<template>
  <span
    class="mc-chip"
    :class="`st-${meta.tone}`"
  >
    <span class="mc-chip__dot" />
    {{ meta.label }}
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import { statusMeta } from '../utils'

const props = defineProps<{
  status: string
  label?: string
}>()

const meta = computed(() => statusMeta(props.status))
</script>
