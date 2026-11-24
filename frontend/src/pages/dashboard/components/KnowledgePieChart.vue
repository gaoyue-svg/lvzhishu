<!-- 饼图组件，展示知识库内容类型分布。 -->
<template>
  <div
    ref="chartRef"
    class="pie-box"
  />
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { useResizeObserver } from '@vueuse/core'

import type { PieSlice } from '@/types/dashboard'

const props = defineProps<{
  slices: PieSlice[]
}>()

const chartRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

function renderChart() {
  if (!chartRef.value) return
  chart ??= echarts.init(chartRef.value)
  chart.setOption({
    color: ['#1e3a5f', '#2c5282', '#c9a96e', '#28a06a'],
    tooltip: { trigger: 'item' },
    legend: {
      bottom: 0,
      left: 'center',
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { color: '#5b6b85' },
    },
    series: [
      {
        type: 'pie',
        radius: ['48%', '72%'],
        center: ['50%', '42%'],
        avoidLabelOverlap: true,
        label: {
          formatter: '{b}\n{d}%',
          color: '#4a5a6d',
          fontSize: 12,
        },
        itemStyle: {
          borderColor: '#ffffff',
          borderWidth: 3,
        },
        data: props.slices,
      },
    ],
  })
}

onMounted(renderChart)
watch(() => props.slices, renderChart, { deep: true })
useResizeObserver(chartRef, () => chart?.resize())

onBeforeUnmount(() => {
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.pie-box {
  width: 100%;
  height: 292px;
}
</style>
