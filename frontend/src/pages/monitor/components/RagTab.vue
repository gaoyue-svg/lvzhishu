<!-- 检索健康 Tab：引用率趋势 + 检索链路指标明细。 -->
<template>
  <div
    v-loading="loading"
    element-loading-background="rgba(6, 10, 18, 0.7)"
    class="mc-rag"
  >
    <template v-if="data">
      <div class="mc-rag-kpis">
        <KpiTile
          label="检索次数"
          :value="formatInt(data.total_retrievals)"
          tone="cyan"
          pulse
          :sub="`近 ${sinceDays} 天`"
        />
        <KpiTile
          label="引用率"
          :value="formatPercent(data.citation_rate)"
          tone="green"
          :sub="`平均引用 ${data.avg_citation_count} 条`"
        />
        <KpiTile
          label="平均总延迟"
          :value="formatMs(data.avg_total_latency_ms)"
          tone="violet"
          :sub="`检索 ${formatMs(data.avg_retrieval_latency_ms)}`"
        />
        <KpiTile
          label="precision_proxy"
          :value="formatPercent(data.precision_proxy, 2)"
          tone="blue"
          :sub="`平均返回 ${formatInt(data.avg_retrieved_count)} 条`"
        />
      </div>

      <div class="mc-rag-mid">
        <PanelFrame
          title="引用率趋势"
          :meta="`最近 ${sinceDays} 天`"
        >
          <div
            ref="trendRef"
            class="mc-rag-trend"
          />
        </PanelFrame>

        <PanelFrame title="检索链路指标">
          <div class="mc-stat-list">
            <div class="mc-stat-row">
              <span class="mc-stat-row__label">
                <StatusLed tone="cyan" />
                检索次数
              </span>
              <span class="mc-stat-row__value">{{ formatInt(data.total_retrievals) }}</span>
            </div>
            <div class="mc-stat-row">
              <span class="mc-stat-row__label">
                <StatusLed tone="green" />
                引用率
              </span>
              <span class="mc-stat-row__value">{{ formatPercent(data.citation_rate) }}</span>
            </div>
            <div class="mc-stat-row">
              <span class="mc-stat-row__label">
                <StatusLed tone="violet" />
                平均引用数
              </span>
              <span class="mc-stat-row__value">{{ data.avg_citation_count }}</span>
            </div>
            <div class="mc-stat-row">
              <span class="mc-stat-row__label">
                <StatusLed tone="blue" />
                平均返回数
              </span>
              <span class="mc-stat-row__value">{{ data.avg_retrieved_count }}</span>
            </div>
            <div class="mc-stat-row">
              <span class="mc-stat-row__label">
                <StatusLed tone="amber" />
                precision_proxy
              </span>
              <span class="mc-stat-row__value">{{ formatPercent(data.precision_proxy, 2) }}</span>
            </div>
            <div class="mc-stat-row">
              <span class="mc-stat-row__label">
                <StatusLed tone="red" />
                平均总延迟
              </span>
              <span class="mc-stat-row__value">{{ formatMs(data.avg_total_latency_ms) }}</span>
            </div>
            <div class="mc-stat-row">
              <span class="mc-stat-row__label">
                <StatusLed tone="red" />
                平均检索延迟
              </span>
              <span class="mc-stat-row__value">{{ formatMs(data.avg_retrieval_latency_ms) }}</span>
            </div>
          </div>
        </PanelFrame>
      </div>
    </template>

    <div
      v-else-if="error"
      class="mc-err"
    >
      <p class="mc-err__msg">{{ error }}</p>
      <button
        class="mc-err__btn"
        type="button"
        @click="load"
      >
        重新加载
      </button>
    </div>

    <div
      v-else
      class="mc-empty"
    >暂无检索数据</div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

import { getHarnessRag } from '@/api/harness'
import type { RagData } from '@/types/harness'

import KpiTile from './KpiTile.vue'
import PanelFrame from './PanelFrame.vue'
import StatusLed from './StatusLed.vue'
import { monitorAxisStyle, monitorTooltip, useMonitorChart } from '../composables/useMonitorChart'
import { formatDateShort, formatInt, formatMs, formatPercent } from '../utils'

const props = defineProps<{
  active: boolean
  sinceDays: number
  refreshTick: number
}>()

const data = ref<RagData | null>(null)
const loading = ref(false)
const error = ref('')

const trendRef = ref<HTMLDivElement>()
const trendChart = useMonitorChart(trendRef)

function renderTrend() {
  const trend = data.value?.trend ?? []
  trendChart.setOption({
    color: ['#53e6a0', '#3ee0ff'],
    tooltip: {
      trigger: 'axis',
      ...monitorTooltip(),
      valueFormatter: (value: unknown) => String(value),
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
      data: trend.map((point) => formatDateShort(point.date)),
      ...monitorAxisStyle(),
      axisLine: { lineStyle: { color: '#1b2a45' } },
    },
    yAxis: [
      {
        type: 'value',
        name: '次数',
        nameTextStyle: { color: '#46587a', fontSize: 10 },
        ...monitorAxisStyle(),
      },
      {
        type: 'value',
        name: '引用率',
        min: 0,
        max: 1,
        nameTextStyle: { color: '#46587a', fontSize: 10 },
        splitLine: { show: false },
        axisLabel: {
          color: '#53e6a0',
          fontFamily: 'ui-monospace, Menlo, Consolas, monospace',
          fontSize: 11,
          formatter: (value: unknown) => `${Math.round(Number(value) * 100)}%`,
        },
      },
    ],
    series: [
      {
        name: '检索次数',
        type: 'bar',
        barMaxWidth: 20,
        itemStyle: { borderRadius: [3, 3, 0, 0] },
        data: trend.map((point) => point.total),
      },
      {
        name: '引用率',
        type: 'line',
        yAxisIndex: 1,
        smooth: true,
        symbol: 'circle',
        symbolSize: 5,
        lineStyle: { width: 2 },
        itemStyle: { color: '#53e6a0' },
        data: trend.map((point) => point.citation_rate),
      },
    ],
  })
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await getHarnessRag(props.sinceDays)
  } catch (currentError) {
    error.value = currentError instanceof Error ? currentError.message : '加载失败'
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.active, props.sinceDays, props.refreshTick],
  () => {
    if (!props.active) return
    load()
  },
  { immediate: true },
)

watch(data, () => {
  if (data.value) renderTrend()
})
</script>

<style scoped>
.mc-rag {
  display: grid;
  gap: 16px;
  min-height: 320px;
}

.mc-rag-kpis {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.mc-rag-mid {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(300px, 1fr);
  gap: 16px;
}

.mc-rag-trend {
  width: 100%;
  height: 288px;
}

.mc-stat-list {
  display: grid;
  gap: 2px;
}

.mc-err {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  min-height: 260px;
}

.mc-err__msg {
  margin: 0;
  font-size: 13px;
  color: var(--mc-red);
}

.mc-err__btn {
  padding: 7px 16px;
  border: 1px solid var(--mc-line);
  border-radius: 9px;
  cursor: pointer;
  font-size: 12px;
  color: var(--mc-text);
  background: rgb(255 255 255 / 4%);
}

.mc-err__btn:hover {
  border-color: var(--mc-cyan);
  color: var(--mc-cyan);
}

@media (max-width: 1280px) {
  .mc-rag-kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 1080px) {
  .mc-rag-mid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 680px) {
  .mc-rag-kpis {
    grid-template-columns: 1fr;
  }
}
</style>
