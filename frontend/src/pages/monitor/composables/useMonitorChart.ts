// ECharts 深色驾驶舱封装：延迟初始化（容器可见才 init）、自适应与销毁。
import { onBeforeUnmount, type Ref } from 'vue'
import * as echarts from 'echarts'
import { useResizeObserver } from '@vueuse/core'

export const MONITOR_PALETTE = ['#3ee0ff', '#53e6a0', '#ffc94d', '#ff6b81', '#a9a1ff', '#6aa8ff', '#2dd4bf']

/** 返回深色主题的通用坐标轴样式。 */
export function monitorAxisStyle() {
  return {
    axisLine: { lineStyle: { color: '#1b2a45' } },
    axisTick: { show: false },
    axisLabel: { color: '#6d82a8', fontFamily: 'ui-monospace, Menlo, Consolas, monospace', fontSize: 11 },
    splitLine: { lineStyle: { color: '#111e33' } },
  }
}

/** 返回深色主题的通用 tooltip 样式。 */
export function monitorTooltip() {
  return {
    backgroundColor: 'rgba(7, 12, 21, 0.94)',
    borderColor: '#22314f',
    textStyle: {
      color: '#c9d8f2',
      fontFamily: 'ui-monospace, Menlo, Consolas, monospace',
      fontSize: 12,
    },
    extraCssText: 'box-shadow: 0 12px 30px rgba(0,0,0,.5); border-radius: 8px;',
  }
}

export function useMonitorChart(containerRef: Ref<HTMLElement | undefined>) {
  let chart: echarts.ECharts | null = null
  let lastOption: echarts.EChartsCoreOption | null = null

  function ensureChart(): echarts.ECharts | null {
    const el = containerRef.value
    if (!el) return null
    if (chart) return chart
    const width = el.clientWidth || el.getBoundingClientRect().width
    const height = el.clientHeight || el.getBoundingClientRect().height
    if (width < 10 || height < 10) return null // 容器不可见（v-show 隐藏），暂缓初始化
    chart = echarts.init(el)
    return chart
  }

  function setOption(option: echarts.EChartsCoreOption, notMerge = false) {
    lastOption = option
    const instance = ensureChart()
    if (!instance) return
    instance.setOption(option, notMerge)
  }

  function resize() {
    chart?.resize()
    if (!chart && lastOption) {
      const instance = ensureChart()
      if (instance) instance.setOption(lastOption)
    }
  }

  useResizeObserver(containerRef, resize)

  onBeforeUnmount(() => {
    chart?.dispose()
    chart = null
  })

  return { setOption, resize, instance: () => chart }
}
