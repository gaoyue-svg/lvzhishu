<!-- LLM 用量 Tab：成本/Token 趋势图 + Provider/Model/用途 维度表。 -->
<template>
  <div
    v-loading="loading"
    element-loading-background="rgba(6, 10, 18, 0.7)"
    class="mc-llm"
  >
    <template v-if="data">
      <div class="mc-llm-kpis">
        <KpiTile
          label="总调用"
          :value="formatInt(data.total_calls)"
          tone="cyan"
          pulse
          :sub="`${data.by_provider.length} 个 provider`"
        />
        <KpiTile
          label="总 Token"
          :value="formatTokens(data.total_tokens)"
          tone="blue"
          :sub="`输入+输出合计`"
        />
        <KpiTile
          label="估算成本"
          :value="formatCost(data.total_cost)"
          tone="green"
          :sub="`近 ${sinceDays} 天`"
        />
        <KpiTile
          label="平均延迟"
          :value="formatMs(avgLatencyMs)"
          tone="violet"
          :sub="`按调用量加权`"
        />
      </div>

      <div class="mc-llm-charts">
        <PanelFrame
          title="成本分布 · Provider"
          meta="估算成本占比"
        >
          <div
            ref="donutRef"
            class="mc-llm-donut"
          />
        </PanelFrame>
        <PanelFrame
          title="Token 与成本趋势"
          :meta="`最近 ${sinceDays} 天`"
        >
          <div
            ref="trendRef"
            class="mc-llm-trend"
          />
        </PanelFrame>
      </div>

      <div class="mc-llm-tables">
        <PanelFrame title="Provider 维度">
          <div class="mc-dim-table">
            <div class="mc-dim-table__head">
              <span>PROVIDER</span>
              <span>调用</span>
              <span>TOKENS</span>
              <span>成本</span>
              <span>均延迟</span>
            </div>
            <div
              v-for="row in data.by_provider"
              :key="row.name"
              class="mc-dim-table__row"
            >
              <span class="mc-dim-table__name">{{ row.name }}</span>
              <span class="mc-mono">{{ formatInt(row.calls) }}</span>
              <span class="mc-mono">{{ formatTokens(row.tokens) }}</span>
              <span class="mc-mono cost">{{ formatCost(row.cost) }}</span>
              <span class="mc-mono">{{ formatMs(row.avg_latency_ms) }}</span>
            </div>
            <div
              v-if="data.by_provider.length === 0"
              class="mc-td-empty"
            >暂无调用</div>
          </div>
        </PanelFrame>

        <PanelFrame title="Model 维度">
          <div class="mc-dim-table">
            <div class="mc-dim-table__head">
              <span>MODEL</span>
              <span>调用</span>
              <span>TOKENS</span>
              <span>成本</span>
              <span>均延迟</span>
            </div>
            <div
              v-for="row in data.by_model"
              :key="row.name"
              class="mc-dim-table__row"
            >
              <span class="mc-dim-table__name">{{ row.name }}</span>
              <span class="mc-mono">{{ formatInt(row.calls) }}</span>
              <span class="mc-mono">{{ formatTokens(row.tokens) }}</span>
              <span class="mc-mono cost">{{ formatCost(row.cost) }}</span>
              <span class="mc-mono">{{ formatMs(row.avg_latency_ms) }}</span>
            </div>
            <div
              v-if="data.by_model.length === 0"
              class="mc-td-empty"
            >暂无调用</div>
          </div>
        </PanelFrame>

        <PanelFrame title="用途维度">
          <div class="mc-dim-table">
            <div class="mc-dim-table__head">
              <span>PURPOSE</span>
              <span>调用</span>
              <span>TOKENS</span>
              <span>成本</span>
              <span>均延迟</span>
            </div>
            <div
              v-for="row in data.by_purpose"
              :key="row.name"
              class="mc-dim-table__row"
            >
              <span class="mc-dim-table__name">{{ purposeLabel(row.name) }}</span>
              <span class="mc-mono">{{ formatInt(row.calls) }}</span>
              <span class="mc-mono">{{ formatTokens(row.tokens) }}</span>
              <span class="mc-mono cost">{{ formatCost(row.cost) }}</span>
              <span class="mc-mono">{{ formatMs(row.avg_latency_ms) }}</span>
            </div>
            <div
              v-if="data.by_purpose.length === 0"
              class="mc-td-empty"
            >暂无调用</div>
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
    >暂无 LLM 用量数据</div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { getHarnessLlm } from '@/api/harness'
import type { LlmUsageData } from '@/types/harness'

import KpiTile from './KpiTile.vue'
import PanelFrame from './PanelFrame.vue'
import { monitorAxisStyle, monitorTooltip, useMonitorChart } from '../composables/useMonitorChart'
import { formatCost, formatDateShort, formatInt, formatMs, formatTokens } from '../utils'

const props = defineProps<{
  active: boolean
  sinceDays: number
  refreshTick: number
}>()

const data = ref<LlmUsageData | null>(null)
const loading = ref(false)
const error = ref('')

const donutRef = ref<HTMLDivElement>()
const trendRef = ref<HTMLDivElement>()
const donutChart = useMonitorChart(donutRef)
const trendChart = useMonitorChart(trendRef)

const PURPOSE_LABELS: Record<string, string> = {
  router: '路由决策',
  agent: 'Agent 推理',
  synthesize: '答案合成',
  review: '审查核验',
  general: '通用',
}

function purposeLabel(name: string): string {
  return PURPOSE_LABELS[name] ?? name
}

const avgLatencyMs = computed(() => {
  const calls = data.value?.total_calls ?? 0
  if (!calls) return 0
  const total = (data.value?.by_provider ?? []).reduce(
    (sum, row) => sum + row.calls * row.avg_latency_ms,
    0,
  )
  return Math.round(total / calls)
})

function renderDonut() {
  const providers = data.value?.by_provider ?? []
  donutChart.setOption({
    color: ['#3ee0ff', '#53e6a0', '#ffc94d', '#ff6b81', '#a9a1ff', '#6aa8ff', '#2dd4bf'],
    tooltip: {
      trigger: 'item',
      ...monitorTooltip(),
      formatter: (params: any) => `${params.name}：${formatCost(Number(params.value))}（${params.percent}%）`,
    },
    legend: {
      type: 'scroll',
      bottom: 0,
      left: 'center',
      itemWidth: 9,
      itemHeight: 9,
      icon: 'circle',
      textStyle: { color: '#6d82a8', fontSize: 11 },
    },
    series: [
      {
        type: 'pie',
        radius: ['46%', '70%'],
        center: ['50%', '42%'],
        startAngle: 90,
        label: { show: false },
        labelLine: { show: false },
        itemStyle: { borderColor: '#0b1322', borderWidth: 3 },
        data: providers.map((row) => ({ name: row.name, value: row.cost })),
      },
    ],
  })
}

function renderTrend() {
  const trend = data.value?.trend ?? []
  trendChart.setOption({
    color: ['#53e6a0', '#3ee0ff'],
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
      data: trend.map((point) => formatDateShort(point.date)),
      ...monitorAxisStyle(),
      axisLine: { lineStyle: { color: '#1b2a45' } },
    },
    yAxis: [
      {
        type: 'value',
        name: 'tokens',
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
        name: 'Tokens',
        type: 'bar',
        barMaxWidth: 20,
        itemStyle: { borderRadius: [3, 3, 0, 0] },
        data: trend.map((point) => point.tokens),
      },
      {
        name: '成本',
        type: 'line',
        yAxisIndex: 1,
        smooth: true,
        symbol: 'circle',
        symbolSize: 5,
        lineStyle: { width: 2 },
        itemStyle: { color: '#3ee0ff' },
        data: trend.map((point) => point.cost),
      },
    ],
  })
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await getHarnessLlm(props.sinceDays)
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
  if (data.value) {
    renderDonut()
    renderTrend()
  }
})
</script>

<style scoped>
.mc-llm {
  display: grid;
  gap: 16px;
  min-height: 320px;
}

.mc-llm-kpis {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.mc-llm-charts {
  display: grid;
  grid-template-columns: minmax(300px, 1fr) minmax(0, 2fr);
  gap: 16px;
}

.mc-llm-donut {
  width: 100%;
  height: 288px;
}

.mc-llm-trend {
  width: 100%;
  height: 288px;
}

.mc-llm-tables {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.mc-dim-table__head,
.mc-dim-table__row {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) repeat(2, 0.7fr) 0.8fr 0.7fr;
  gap: 8px;
  align-items: center;
}

.mc-dim-table__head {
  padding: 0 0 9px;
  border-bottom: 1px solid var(--mc-line-soft);
  font-size: 10px;
  letter-spacing: 0.08em;
  color: var(--mc-faint);
  text-transform: uppercase;
}

.mc-dim-table__row {
  padding: 9px 0;
  border-bottom: 1px dashed var(--mc-line-soft);
  font-size: 12px;
  color: var(--mc-dim);
}

.mc-dim-table__row:last-child {
  border-bottom: 0;
}

.mc-dim-table__name {
  color: var(--mc-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mc-dim-table__row .cost {
  color: var(--mc-green);
}

.mc-td-empty {
  padding: 24px 0;
  text-align: center;
  color: var(--mc-faint);
  font-size: 12px;
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
  .mc-llm-kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .mc-llm-tables {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 1080px) {
  .mc-llm-charts {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 680px) {
  .mc-llm-kpis {
    grid-template-columns: 1fr;
  }
}
</style>
