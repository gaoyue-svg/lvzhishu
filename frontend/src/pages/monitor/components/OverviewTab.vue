<!-- 总览 Tab：核心 KPI 磁贴 + 状态分布 + 运行/成本趋势 + LLM/质量/检索/护栏四联面板。 -->
<template>
  <div
    v-loading="loading"
    element-loading-background="rgba(6, 10, 18, 0.7)"
    class="mc-ov"
  >
    <template v-if="data">
      <div class="mc-ov-kpis">
        <KpiTile
          label="Pipeline 运行"
          :value="formatInt(pipeline.total_runs)"
          tone="cyan"
          pulse
          :sub="`成功率 ${formatPercent(pipeline.success_rate)}`"
        />
        <KpiTile
          label="平均延迟"
          :value="formatMs(pipeline.avg_latency_ms)"
          tone="violet"
          :sub="`P95 ${formatMs(pipeline.p95_latency_ms)} · 失败 ${formatInt(pipeline.failed)}`"
        />
        <KpiTile
          label="LLM 成本"
          :value="formatCost(llm.total_cost)"
          tone="green"
          :sub="`${formatTokens(llm.total_tokens)} tokens · ${formatInt(llm.total_calls)} 调用`"
        />
        <KpiTile
          label="检索引用率"
          :value="formatPercent(rag.citation_rate)"
          tone="blue"
          :sub="`precision_proxy ${formatPercent(rag.precision_proxy)}`"
        />
      </div>

      <div class="mc-ov-mid">
        <PanelFrame
          title="运行状态分布"
          :meta="`成功 ${formatInt(pipeline.success)}`"
        >
          <StatusDonut
            :success="pipeline.success"
            :failed="pipeline.failed"
            :hitl="pipeline.hitl"
          />
        </PanelFrame>

        <PanelFrame
          title="运行与成本趋势"
          :meta="`最近 ${sinceDays} 天`"
        >
          <RunsTrendChart :trend="data.trend" />
        </PanelFrame>
      </div>

      <div class="mc-ov-bottom">
        <PanelFrame title="LLM 用量">
          <div class="mc-llm-head">
            <div class="mc-llm-cost">{{ formatCost(llm.total_cost) }}</div>
            <div class="mc-llm-sub">
              {{ formatTokens(llm.total_tokens) }} tokens · {{ formatInt(llm.total_calls) }} 调用
            </div>
          </div>
          <div
            v-for="provider in topProviders"
            :key="provider.name"
            class="mc-bar-row"
          >
            <div class="mc-bar-row__top">
              <span>{{ provider.name }}</span>
              <span class="mc-mono">{{ formatCost(provider.cost) }}</span>
            </div>
            <div class="mc-bar-row__track">
              <div
                class="mc-bar-row__fill"
                :style="{ width: `${providerShare(provider.cost)}%` }"
              />
            </div>
          </div>
          <div
            v-if="llm.by_provider.length === 0"
            class="mc-empty"
          >暂无 LLM 调用</div>
        </PanelFrame>

        <PanelFrame title="质量评估">
          <div class="mc-q-block">
            <div class="mc-q-block__title">
              <StatusLed
                tone="cyan"
                pulse
              />
              在线确定性评估
              <span class="mc-faint">· {{ evaluation.online.count }} 条</span>
            </div>
            <ScoreBar
              :scores="[
                { label: '综合', value: evaluation.online.overall },
                { label: '引用完整', value: evaluation.online.citation_score },
                { label: '覆盖度', value: evaluation.online.coverage },
              ]"
            />
          </div>
          <div class="mc-q-block">
            <div class="mc-q-block__title">
              <StatusLed
                tone="violet"
                pulse
              />
              离线 LLM 评审
              <span class="mc-faint">· {{ evaluation.offline.count }} 条</span>
            </div>
            <ScoreBar
              :scores="[
                { label: '综合', value: evaluation.offline.overall },
                { label: '落地支撑', value: evaluation.offline.grounded_score },
              ]"
            />
          </div>
        </PanelFrame>

        <PanelFrame title="检索健康">
          <div class="mc-stat-list">
            <div class="mc-stat-row">
              <span class="mc-stat-row__label">检索次数</span>
              <span class="mc-stat-row__value">{{ formatInt(rag.total_retrievals) }}</span>
            </div>
            <div class="mc-stat-row">
              <span class="mc-stat-row__label">引用率</span>
              <span class="mc-stat-row__value">{{ formatPercent(rag.citation_rate) }}</span>
            </div>
            <div class="mc-stat-row">
              <span class="mc-stat-row__label">平均总延迟</span>
              <span class="mc-stat-row__value">{{ formatMs(rag.avg_total_latency_ms) }}</span>
            </div>
            <div class="mc-stat-row">
              <span class="mc-stat-row__label">平均检索延迟</span>
              <span class="mc-stat-row__value">{{ formatMs(rag.avg_retrieval_latency_ms) }}</span>
            </div>
            <div class="mc-stat-row">
              <span class="mc-stat-row__label">precision_proxy</span>
              <span class="mc-stat-row__value">{{ formatPercent(rag.precision_proxy, 2) }}</span>
            </div>
          </div>
        </PanelFrame>

        <PanelFrame title="护栏 · 降级">
          <div class="mc-guard">
            <div class="mc-guard__total">
              <span class="mc-guard__num">{{ formatInt(runtime.guard.total_blocked) }}</span>
              <span class="mc-guard__cap">拦截</span>
            </div>
            <div class="mc-guard__chips">
              <span
                v-for="(count, check) in runtime.guard.by_check"
                :key="check"
                class="mc-guard__chip"
              >
                <span class="mc-faint">{{ check }}</span>
                <b class="mc-mono">{{ formatInt(count) }}</b>
              </span>
              <span
                v-if="guardChecks.length === 0"
                class="mc-faint"
              >暂无拦截</span>
            </div>
          </div>
          <div class="mc-stat-list">
            <div class="mc-stat-row">
              <span class="mc-stat-row__label">Milvus 降级 BM25</span>
              <span class="mc-stat-row__value">{{ formatInt(runtime.milvus_fallback) }}</span>
            </div>
            <div class="mc-stat-row">
              <span class="mc-stat-row__label">联网搜索降级</span>
              <span class="mc-stat-row__value">{{ formatInt(webFallbackTotal) }}</span>
            </div>
            <div class="mc-stat-row">
              <span class="mc-stat-row__label">Guard 总开关</span>
              <span class="mc-stat-row__value">{{ guardEnabledLabel }}</span>
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
    >暂无监控数据</div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { getHarnessOverview } from '@/api/harness'
import type { HarnessOverview, LlmDimension } from '@/types/harness'

import KpiTile from './KpiTile.vue'
import PanelFrame from './PanelFrame.vue'
import RunsTrendChart from './RunsTrendChart.vue'
import ScoreBar from './ScoreBar.vue'
import StatusDonut from './StatusDonut.vue'
import StatusLed from './StatusLed.vue'
import { formatCost, formatInt, formatMs, formatPercent, formatTokens } from '../utils'

const props = defineProps<{
  active: boolean
  sinceDays: number
  refreshTick: number
}>()

const data = ref<HarnessOverview | null>(null)
const loading = ref(false)
const error = ref('')

const pipeline = computed(() => data.value!.pipeline)
const llm = computed(() => data.value!.llm)
const evaluation = computed(() => data.value!.evaluation)
const rag = computed(() => data.value!.rag)
const runtime = computed(() => data.value!.runtime)

const topProviders = computed<LlmDimension[]>(() => llm.value.by_provider.slice(0, 3))

const guardChecks = computed(() => Object.keys(runtime.value.guard.by_check))
const webFallbackTotal = computed(() =>
  Object.values(runtime.value.web_search_fallback).reduce((sum, count) => sum + count, 0),
)
const guardEnabledLabel = computed(() => (guardChecks.value.length > 0 ? '已生效' : '无拦截记录'))

function providerShare(cost: number): number {
  const max = Math.max(...llm.value.by_provider.map((item) => item.cost), 0.0001)
  return Math.max(6, Math.min(100, (cost / max) * 100))
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await getHarnessOverview(props.sinceDays)
  } catch (currentError) {
    error.value = currentError instanceof Error ? currentError.message : '加载失败'
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.active, props.sinceDays, props.refreshTick],
  () => {
    if (props.active) load()
  },
  { immediate: true },
)
</script>

<style scoped>
.mc-ov {
  display: grid;
  gap: 16px;
  min-height: 320px;
}

.mc-ov-kpis {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.mc-ov-mid {
  display: grid;
  grid-template-columns: minmax(300px, 1fr) minmax(0, 2fr);
  gap: 16px;
}

.mc-ov-bottom {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

/* LLM 用量面板 */
.mc-llm-head {
  margin-bottom: 12px;
}

.mc-llm-cost {
  font-size: 24px;
  font-weight: 700;
  color: #53e6a0;
  text-shadow: 0 0 20px rgb(83 230 160 / 30%);
}

.mc-llm-sub {
  margin-top: 4px;
  font-size: 11px;
  color: var(--mc-faint);
}

.mc-bar-row {
  margin-top: 10px;
}

.mc-bar-row__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: var(--mc-dim);
  margin-bottom: 5px;
}

.mc-bar-row__track {
  height: 5px;
  border-radius: 4px;
  background: rgb(255 255 255 / 5%);
  overflow: hidden;
}

.mc-bar-row__fill {
  height: 100%;
  border-radius: 4px;
  background: linear-gradient(90deg, #1f8ea9, var(--mc-cyan));
  box-shadow: 0 0 10px rgb(62 224 255 / 40%);
  transition: width 500ms cubic-bezier(0.22, 1, 0.36, 1);
}

/* 质量评估面板 */
.mc-q-block {
  display: grid;
  gap: 8px;
}

.mc-q-block + .mc-q-block {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px dashed var(--mc-line-soft);
}

.mc-q-block__title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--mc-dim);
}

/* 检索健康 / 护栏 */
.mc-stat-list {
  display: grid;
  gap: 2px;
}

.mc-guard {
  margin-bottom: 10px;
}

.mc-guard__total {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.mc-guard__num {
  font-family: var(--mc-mono);
  font-size: 24px;
  font-weight: 700;
  color: var(--mc-amber);
  text-shadow: 0 0 18px rgb(255 201 77 / 26%);
}

.mc-guard__cap {
  font-size: 11px;
  color: var(--mc-faint);
}

.mc-guard__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.mc-guard__chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border: 1px solid var(--mc-line);
  border-radius: 7px;
  font-size: 11px;
  background: rgb(255 255 255 / 3%);
}

.mc-guard__chip b {
  color: var(--mc-text);
}

/* 错误态 */
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
  transition:
    border-color 160ms ease,
    color 160ms ease;
}

.mc-err__btn:hover {
  border-color: var(--mc-cyan);
  color: var(--mc-cyan);
}

@media (max-width: 1280px) {
  .mc-ov-kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .mc-ov-bottom {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 1080px) {
  .mc-ov-mid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 680px) {
  .mc-ov-kpis,
  .mc-ov-bottom {
    grid-template-columns: 1fr;
  }
}
</style>
