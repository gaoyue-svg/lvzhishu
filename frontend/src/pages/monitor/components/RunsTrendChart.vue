<!-- 运行与成本趋势图：成功/失败/待复核堆叠柱 + 成本折线（右轴）。 -->
<template>
  <div
    ref="chartRef"
    class="runs-trend"
  />
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

import type { TrendPoint } from '@/types/harness'

import { monitorAxisStyle, monitorTooltip, useMonitorChart } from '../composables/useMonitorChart'
import { formatDateShort } from '../utils'

const props = defineProps<{
  trend: TrendPoint[]
}>()

const chartRef = ref<HTMLDivElement>()
const { setOption } = useMonitorChart(chartRef)

function renderChart() {
  const dates = props.trend.map((point) => formatDateShort(point.date))
  setOption({
    color: ['#53e6a0', '#ff6b81', '#ffc94d', '#3ee0ff'],
    tooltip: {
      trigger: 'axis',
      ...monitorTooltip(),
    },
    legend: {
      top: 0,
      right: 0,
      itemWidth: 10,
      itemHeight: 10,
      icon: 'roundRect',
      textStyle: { color: '#6d82a8', fontSize: 11 },
    },
    grid: { left: 8, right: 10, top: 42, bottom: 8, containLabel: true },
    xAxis: {
      type: 'category',
      boundaryGap: true,
      data: dates,
      ...monitorAxisStyle(),
      axisLine: { lineStyle: { color: '#1b2a45' } },
    },
    yAxis: [
      {
        type: 'value',
        name: '次',
        nameTextStyle: { color: '#46587a', fontSize: 10 },
        ...monitorAxisStyle(),
      },
      {
        type: 'value',
        name: '¥',
        nameTextStyle: { color: '#46587a', fontSize: 10 },
        splitLine: { show: false },
        axisLabel: { color: '#3ee0ff', fontFamily: 'ui-monospace, Menlo, Consolas, monospace', fontSize: 11 },
      },
    ],
    series: [
      {
        name: '成功',
        type: 'bar',
        stack: 'runs',
        barMaxWidth: 20,
        itemStyle: { borderRadius: [2, 2, 0, 0] },
        data: props.trend.map((point) => point.success),
      },
      {
        name: '失败',
        type: 'bar',
        stack: 'runs',
        barMaxWidth: 20,
        data: props.trend.map((point) => point.failed),
      },
      {
        name: '待复核',
        type: 'bar',
        stack: 'runs',
        barMaxWidth: 20,
        data: props.trend.map((point) => point.hitl),
      },
      {
        name: 'LLM 成本',
        type: 'line',
        yAxisIndex: 1,
        smooth: true,
        symbol: 'circle',
        symbolSize: 5,
        lineStyle: { width: 2 },
        itemStyle: { color: '#3ee0ff' },
        data: props.trend.map((point) => point.cost),
      },
    ],
  })
}

watch(() => props.trend, renderChart, { deep: true })
</script>

<style scoped>
.runs-trend {
  width: 100%;
  height: 288px;
}
</style>
