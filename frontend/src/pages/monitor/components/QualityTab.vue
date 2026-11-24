<!-- 质量评估 Tab：在线/离线评分 KPI + 质量趋势图 + 最近评估明细。 -->
<template>
  <div
    v-loading="loading"
    element-loading-background="rgba(6, 10, 18, 0.7)"
    class="mc-q"
  >
    <template v-if="data">
      <div class="mc-q-kpis">
        <KpiTile
          label="在线评估条数"
          :value="formatInt(data.online.count)"
          tone="cyan"
          pulse
          :sub="`确定性评估`"
        />
        <KpiTile
          label="在线综合分"
          :value="formatPercent(data.online.overall)"
          tone="green"
          :sub="`引用完整 ${formatPercent(data.online.citation_score)} · 覆盖 ${formatPercent(data.online.coverage)}`"
        />
        <KpiTile
          label="离线评审条数"
          :value="formatInt(data.offline.count)"
          tone="violet"
          :sub="`LLM-as-Judge 抽样`"
        />
        <KpiTile
          label="离线落地分"
          :value="formatPercent(data.offline.grounded_score)"
          tone="blue"
          :sub="`幻觉 ${formatPercent(data.offline.hallucination)}`"
        />
      </div>

      <div class="mc-q-mid">
        <PanelFrame
          title="质量趋势"
          :meta="`最近 ${sinceDays} 天日均分`"
        >
          <div
            ref="trendRef"
            class="mc-q-trend"
          />
        </PanelFrame>

        <PanelFrame title="评分对比">
          <div class="mc-q-compare">
            <div class="mc-q-block">
              <div class="mc-q-block__title">
                <StatusLed
                  tone="cyan"
                  pulse
                />
                在线确定性评估
              </div>
              <ScoreBar :scores="onlineScores" />
            </div>
            <div class="mc-q-block">
              <div class="mc-q-block__title">
                <StatusLed
                  tone="violet"
                  pulse
                />
                离线 LLM 评审
              </div>
              <ScoreBar :scores="offlineScores" />
            </div>
          </div>
        </PanelFrame>
      </div>

      <PanelFrame
        title="最近评估"
        :meta="`${data.recent.length} 条`"
      >
        <div class="mc-table-wrap">
          <table class="mc-table">
            <thead>
              <tr>
                <th>TRACE</th>
                <th>模式</th>
                <th>引用完整</th>
                <th>覆盖度</th>
                <th>落地支撑</th>
                <th>幻觉</th>
                <th>综合</th>
                <th>时间</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(item, index) in data.recent"
                :key="`${item.trace_id}-${index}`"
              >
                <td class="mc-td-mono">{{ shortTraceId(item.trace_id) }}</td>
                <td>
                  <span
                    class="mc-chip"
                    :class="item.mode === 'online' ? 'st-cyan' : 'st-violet'"
                  >{{ item.mode === 'online' ? '在线' : '离线' }}</span>
                </td>
                <td class="mc-td-mono">{{ percent(item.citation_score) }}</td>
                <td class="mc-td-mono">{{ percent(item.coverage) }}</td>
                <td class="mc-td-mono">{{ percent(item.grounded_score) }}</td>
                <td class="mc-td-mono">{{ percent(item.hallucination) }}</td>
                <td class="mc-td-mono">{{ percent(item.overall) }}</td>
                <td class="mc-td-mono">{{ formatDateTime(item.created_at) }}</td>
              </tr>
              <tr v-if="data.recent.length === 0">
                <td
                  class="mc-td-empty"
                  colspan="8"
                >该范围内暂无评估记录</td>
              </tr>
            </tbody>
          </table>
        </div>
      </PanelFrame>
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
    >暂无评估数据</div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { getHarnessEvaluation } from '@/api/harness'
import type { EvaluationData } from '@/types/harness'

import KpiTile from './KpiTile.vue'
import PanelFrame from './PanelFrame.vue'
import ScoreBar from './ScoreBar.vue'
import StatusLed from './StatusLed.vue'
import { monitorAxisStyle, monitorTooltip, useMonitorChart } from '../composables/useMonitorChart'
import { formatDateShort, formatDateTime, formatInt, formatPercent, shortTraceId } from '../utils'

const props = defineProps<{
  active: boolean
  sinceDays: number
  refreshTick: number
}>()

const data = ref<EvaluationData | null>(null)
const loading = ref(false)
const error = ref('')

const trendRef = ref<HTMLDivElement>()
const trendChart = useMonitorChart(trendRef)

function percent(value: number | null): string {
  return value == null ? '—' : formatPercent(value)
}

const onlineScores = computed(() => {
  const scores = data.value?.online
  return [
    { label: '综合', value: scores?.overall ?? null },
    { label: '引用完整', value: scores?.citation_score ?? null },
    { label: '覆盖度', value: scores?.coverage ?? null },
  ]
})

const offlineScores = computed(() => {
  const scores = data.value?.offline
  return [
    { label: '综合', value: scores?.overall ?? null },
    { label: '落地支撑', value: scores?.grounded_score ?? null },
    {
      label: '无幻觉率',
      value: scores?.hallucination == null ? null : 1 - scores.hallucination,
      display: () =>
        scores?.hallucination == null ? '—' : `幻觉 ${(scores.hallucination * 100).toFixed(1)}%`,
    },
  ]
})

function renderTrend() {
  const trend = data.value?.trend ?? []
  trendChart.setOption({
    color: ['#3ee0ff', '#6aa8ff', '#53e6a0', '#a9a1ff', '#ff6b81'],
    tooltip: {
      trigger: 'axis',
      ...monitorTooltip(),
      valueFormatter: (value: unknown) => formatPercent(Number(value), 1),
    },
    legend: {
      top: 0,
      right: 0,
      itemWidth: 10,
      itemHeight: 10,
      icon: 'roundRect',
      textStyle: { color: '#6d82a8', fontSize: 11 },
    },
    grid: { left: 8, right: 8, top: 42, bottom: 8, containLabel: true },
    xAxis: {
      type: 'category',
      data: trend.map((point) => formatDateShort(point.date)),
      ...monitorAxisStyle(),
      axisLine: { lineStyle: { color: '#1b2a45' } },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 1,
      ...monitorAxisStyle(),
    },
    series: [
      { name: '引用完整', type: 'line', smooth: true, symbol: 'circle', symbolSize: 5, data: trend.map((p) => p.citation_score) },
      { name: '覆盖度', type: 'line', smooth: true, symbol: 'circle', symbolSize: 5, data: trend.map((p) => p.coverage) },
      { name: '在线综合', type: 'line', smooth: true, symbol: 'circle', symbolSize: 5, lineStyle: { width: 2.5 }, data: trend.map((p) => p.overall ?? 0) },
      { name: '落地支撑', type: 'line', smooth: true, symbol: 'circle', symbolSize: 5, data: trend.map((p) => p.grounded_score) },
      {
        name: '幻觉占比',
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 4,
        lineStyle: { width: 1.5, type: 'dashed' },
        data: trend.map((p) => p.hallucination),
      },
    ],
  })
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await getHarnessEvaluation(props.sinceDays)
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
.mc-q {
  display: grid;
  gap: 16px;
  min-height: 320px;
}

.mc-q-kpis {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.mc-q-mid {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(300px, 1fr);
  gap: 16px;
}

.mc-q-trend {
  width: 100%;
  height: 288px;
}

.mc-q-compare {
  display: grid;
  gap: 14px;
}

.mc-q-block {
  display: grid;
  gap: 8px;
}

.mc-q-block__title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--mc-dim);
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
  .mc-q-kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 1080px) {
  .mc-q-mid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 680px) {
  .mc-q-kpis {
    grid-template-columns: 1fr;
  }
}
</style>
