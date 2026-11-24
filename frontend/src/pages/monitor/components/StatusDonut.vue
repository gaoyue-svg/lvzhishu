<!-- 运行状态分布环形图：成功/失败/待复核占比，中心显示总数。 -->
<template>
  <div
    ref="chartRef"
    class="status-donut"
  />
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

import { monitorTooltip, useMonitorChart } from '../composables/useMonitorChart'

const props = defineProps<{
  success: number
  failed: number
  hitl: number
}>()

const chartRef = ref<HTMLDivElement>()
const { setOption } = useMonitorChart(chartRef)

function renderChart() {
  const total = props.success + props.failed + props.hitl
  const slices = [
    { name: '成功', value: props.success, itemStyle: { color: '#53e6a0' } },
    { name: '失败', value: props.failed, itemStyle: { color: '#ff6b81' } },
    { name: '待复核', value: props.hitl, itemStyle: { color: '#ffc94d' } },
  ].filter((slice) => slice.value > 0)

  setOption({
    color: ['#53e6a0', '#ff6b81', '#ffc94d'],
    tooltip: {
      trigger: 'item',
      ...monitorTooltip(),
      formatter: (params: any) => `${params.name}：${params.value} 次（${params.percent}%）`,
    },
    legend: {
      bottom: 0,
      left: 'center',
      itemWidth: 9,
      itemHeight: 9,
      icon: 'circle',
      textStyle: { color: '#6d82a8', fontSize: 11 },
    },
    title: {
      text: String(total),
      subtext: '总运行',
      left: 'center',
      top: '34%',
      textStyle: {
        color: '#eaf6ff',
        fontFamily: 'ui-monospace, Menlo, Consolas, monospace',
        fontSize: 28,
        fontWeight: 700,
      },
      subtextStyle: { color: '#46587a', fontSize: 11, letterSpacing: 2 },
    },
    series: [
      {
        type: 'pie',
        radius: ['52%', '74%'],
        center: ['50%', '42%'],
        startAngle: 90,
        label: { show: false },
        labelLine: { show: false },
        itemStyle: { borderColor: '#0b1322', borderWidth: 3 },
        emphasis: { scaleSize: 6 },
        data: slices,
      },
    ],
  })
}

watch(() => [props.success, props.failed, props.hitl], renderChart, { deep: true })
</script>

<style scoped>
.status-donut {
  width: 100%;
  height: 288px;
}
</style>
