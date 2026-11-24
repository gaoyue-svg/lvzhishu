<!-- 折线图组件，使用 ECharts 展示各类法律 AI 能力的使用趋势。 -->
<template>
  <div ref="chartRef" class="chart-box" />
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { useResizeObserver } from '@vueuse/core'

import type { ChartPoint } from '@/types/dashboard'

const props = defineProps<{
  points: ChartPoint[]
}>()

const chartRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

function renderChart() {
  if (!chartRef.value) return
  chart ??= echarts.init(chartRef.value)
  chart.setOption({
    color: ['#1e3a5f', '#2c5282', '#28a06a', '#c9a96e'],
    tooltip: { trigger: 'axis' },
    legend: {
      top: 0,
      right: 0,
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { color: '#5b6b85' },
    },
    grid: { left: 8, right: 8, top: 42, bottom: 10, containLabel: true },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: props.points.map((item) => item.day),
      axisLine: { lineStyle: { color: '#dce3ee' } },
      axisTick: { show: false },
      axisLabel: { color: '#7a899b' },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: '#eef1f6' } },
      axisLabel: { color: '#7a899b' },
    },
    series: [
      {
        name: 'AI问答',
        type: 'line',
        smooth: true,
        symbolSize: 7,
        areaStyle: { color: 'rgba(30, 58, 95, 0.08)' },
        data: props.points.map((item) => item.qa),
      },
      {
        name: '法规检索',
        type: 'line',
        smooth: true,
        symbolSize: 7,
        data: props.points.map((item) => item.retrieval),
      },
      {
        name: '合同审查',
        type: 'line',
        smooth: true,
        symbolSize: 7,
        data: props.points.map((item) => item.contract),
      },
      {
        name: '文书生成',
        type: 'line',
        smooth: true,
        symbolSize: 7,
        data: props.points.map((item) => item.document),
      },
    ],
  })
}

onMounted(renderChart)
watch(() => props.points, renderChart, { deep: true })
useResizeObserver(chartRef, () => chart?.resize())

onBeforeUnmount(() => {
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.chart-box {
  width: 100%;
  height: 292px;
}
</style>
