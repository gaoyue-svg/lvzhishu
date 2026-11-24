<!-- Run 追踪详情抽屉：意图 / Plan DAG / 执行步骤时间线 / 审查结论 / 最终答案 / 引用 / 评估分。 -->
<template>
  <el-drawer
    v-model="visible"
    size="680px"
    :with-header="false"
    class="mc-drawer"
    modal-class="mc-modal"
  >
    <div
      v-loading="loading"
      element-loading-background="rgba(6, 10, 18, 0.7)"
      class="tdd"
    >
      <template v-if="detail">
        <header class="tdd-head">
          <div class="tdd-head__top">
            <span class="tdd-head__id mc-mono">{{ detail.trace_id }}</span>
            <StatusChip :status="detail.status" />
          </div>
          <div class="tdd-head__meta">
            <span>{{ formatDateTime(detail.created_at) }}</span>
            <span>·</span>
            <span class="mc-mono">{{ formatMs(detail.total_latency_ms) }}</span>
            <span>·</span>
            <span class="mc-mono">{{ detail.step_count }} 步</span>
            <span
              v-if="detail.experiment_variant"
              class="mc-chip st-violet"
            >AB {{ detail.experiment_variant }}</span>
            <span
              v-if="detail.needs_human_review"
              class="mc-chip st-amber"
            >需人工复核</span>
          </div>
        </header>

        <div class="tdd-scroll">
          <!-- 意图 -->
          <section class="tdd-sec">
            <h3 class="tdd-sec__title">意图识别</h3>
            <div
              v-if="intent"
              class="tdd-intent"
            >
              <span class="mc-chip st-cyan">{{ intentLabel(intent.name as string) }}</span>
              <span
                v-if="intent.confidence != null"
                class="mc-mono tdd-intent__conf"
              >置信度 {{ (Number(intent.confidence) * 100).toFixed(1) }}%</span>
            </div>
            <pre
              v-else
              class="tdd-pre"
            >{}（无意图信息）</pre>
          </section>

          <!-- Plan DAG -->
          <section
            v-if="planSteps.length"
            class="tdd-sec"
          >
            <h3 class="tdd-sec__title">计划 Plan DAG</h3>
            <div class="tdd-plan">
              <div
                v-for="step in planSteps"
                :key="step.step_id"
                class="tdd-plan-step"
              >
                <div class="tdd-plan-step__head">
                  <span class="tdd-plan-step__id mc-mono">{{ step.step_id }}</span>
                  <span class="tdd-plan-step__agent">{{ step.agent }}</span>
                  <span
                    v-if="step.deps?.length"
                    class="tdd-plan-step__deps"
                  >依赖 {{ step.deps.join(', ') }}</span>
                </div>
                <div class="tdd-plan-step__goal">{{ step.goal || '—' }}</div>
                <div
                  v-if="step.inputs || step.outputs"
                  class="tdd-plan-step__io"
                >
                  <div>
                    <span class="tdd-io-tag">IN</span>
                    <code>{{ JSON.stringify(step.inputs ?? {}) }}</code>
                  </div>
                  <div>
                    <span class="tdd-io-tag">OUT</span>
                    <code>{{ JSON.stringify(step.outputs ?? {}) }}</code>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <!-- 执行步骤时间线 -->
          <section
            v-if="detail.step_traces?.length"
            class="tdd-sec"
          >
            <h3 class="tdd-sec__title">执行步骤</h3>
            <div class="tdd-timeline">
              <div
                v-for="trace in detail.step_traces"
                :key="trace.step_id"
                class="tdd-tl"
              >
                <div class="tdd-tl__rail">
                  <span
                    class="tdd-tl__dot"
                    :style="{ background: dotColor(trace.status) }"
                  />
                </div>
                <div class="tdd-tl__body">
                  <div class="tdd-tl__head">
                    <span class="tdd-tl__id mc-mono">{{ trace.step_id }}</span>
                    <span class="tdd-tl__agent">{{ trace.agent }}</span>
                    <StatusChip :status="trace.status" />
                    <span class="tdd-tl__latency mc-mono">{{ formatMs(trace.latency_ms) }}</span>
                  </div>
                  <div
                    v-if="trace.goal"
                    class="tdd-tl__goal"
                  >{{ trace.goal }}</div>
                  <div
                    v-if="trace.output_summary"
                    class="tdd-tl__sum"
                  >{{ trace.output_summary }}</div>
                  <div
                    v-if="trace.error"
                    class="tdd-tl__err"
                  >{{ trace.error }}</div>
                  <div
                    v-if="trace.chunks_count || trace.citations_count"
                    class="tdd-tl__counts mc-mono"
                  >chunks {{ trace.chunks_count ?? 0 }} · cites {{ trace.citations_count ?? 0 }}</div>
                </div>
              </div>
            </div>
          </section>

          <!-- 审查结论 -->
          <section
            v-if="review"
            class="tdd-sec"
          >
            <h3 class="tdd-sec__title">审查结论</h3>
            <div class="tdd-review">
              <div class="tdd-review__verdict">
                <StatusLed
                  :tone="review.passed ? 'green' : 'red'"
                  pulse
                />
                <b>{{ review.passed ? '审查通过' : '审查未通过' }}</b>
              </div>
              <div
                v-if="review.failed_steps?.length"
                class="tdd-review__failed"
              >
                失败步骤：<span class="mc-mono">{{ review.failed_steps.join(', ') }}</span>
              </div>
              <div
                v-for="issue in review.issues ?? []"
                :key="issue.step_id"
                class="tdd-review__issue"
              >
                <span class="mc-chip st-red">{{ issue.level }}</span>
                <span class="mc-mono">{{ issue.step_id }}</span>
                <span class="mc-dim">{{ (issue.issues ?? []).join('；') || '—' }}</span>
              </div>
              <div
                v-if="review.l2"
                class="tdd-review__l2"
              >
                <span class="mc-faint">L2 落地抽查：</span>
                {{ review.l2.reason }}
                <span
                  v-if="review.l2.checked"
                  class="mc-mono"
                >[{{ review.l2.passed ? 'PASS' : 'FAIL' }}]</span>
              </div>
            </div>
          </section>

          <!-- 最终答案 -->
          <section
            v-if="detail.final_answer"
            class="tdd-sec"
          >
            <h3 class="tdd-sec__title">最终答案</h3>
            <pre class="tdd-answer">{{ detail.final_answer }}</pre>
          </section>

          <!-- 引用 -->
          <section
            v-if="detail.final_citations?.length"
            class="tdd-sec"
          >
            <h3 class="tdd-sec__title">
              引用
              <span class="mc-faint">· {{ detail.final_citations.length }} 条</span>
            </h3>
            <div class="tdd-cites">
              <div
                v-for="(cite, index) in detail.final_citations"
                :key="`${String(cite.index)}-${index}`"
                class="tdd-cite"
              >
                <span class="tdd-cite__idx mc-mono">[{{ cite.index ?? index + 1 }}]</span>
                <div class="tdd-cite__body">
                  <div class="tdd-cite__title">{{ cite.title || cite.text || '未命名来源' }}</div>
                  <div class="tdd-cite__meta mc-mono">
                    {{ cite.source_type || 'law' }}<span
                      v-if="cite.from_agent"
                    > · {{ cite.from_agent }}</span>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <!-- 评估 -->
          <section class="tdd-sec">
            <h3 class="tdd-sec__title">质量评估</h3>
            <div
              v-if="online || offline"
              class="tdd-eval"
            >
              <div
                v-if="online"
                class="tdd-eval__block"
              >
                <div class="tdd-eval__head">
                  <StatusLed
                    tone="cyan"
                    pulse
                  />
                  在线确定性评估
                </div>
                <ScoreBar :scores="onlineScores" />
              </div>
              <div
                v-if="offline"
                class="tdd-eval__block"
              >
                <div class="tdd-eval__head">
                  <StatusLed
                    tone="violet"
                    pulse
                  />
                  离线 LLM 评审
                </div>
                <ScoreBar :scores="offlineScores" />
              </div>
            </div>
            <div
              v-else
              class="mc-empty"
            >该 run 暂无评估记录</div>
          </section>
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
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { getHarnessTraceDetail } from '@/api/harness'
import type { PlanStep, TraceDetail, TraceEvaluation } from '@/types/harness'

import ScoreBar from './ScoreBar.vue'
import StatusChip from './StatusChip.vue'
import StatusLed from './StatusLed.vue'
import { formatDateTime, formatMs, intentLabel } from '../utils'

const props = defineProps<{
  traceId: string
}>()

const visible = defineModel<boolean>({ required: true })

const detail = ref<TraceDetail | null>(null)
const loading = ref(false)
const error = ref('')

const intent = computed(() => detail.value?.intent ?? null)
const review = computed(() => detail.value?.review ?? null)
const planSteps = computed<PlanStep[]>(() => detail.value?.plan?.steps ?? [])
const online = computed<TraceEvaluation | null>(() => detail.value?.evaluation.online ?? null)
const offline = computed<TraceEvaluation | null>(() => detail.value?.evaluation.offline ?? null)

const onlineScores = computed(() => {
  const scores = online.value
  return [
    { label: '综合', value: scores?.overall ?? null },
    { label: '引用完整', value: scores?.citation_score ?? null },
    { label: '覆盖度', value: scores?.coverage ?? null },
  ]
})

const offlineScores = computed(() => {
  const scores = offline.value
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

const DOT_COLOR: Record<string, string> = {
  green: '#53e6a0',
  red: '#ff6b81',
  amber: '#ffc94d',
  cyan: '#3ee0ff',
  gray: '#46587a',
}

function dotColor(status: string): string {
  const tones: Record<string, keyof typeof DOT_COLOR> = {
    success: 'green',
    failed: 'red',
    hitl: 'amber',
    running: 'cyan',
    pending: 'cyan',
    skipped: 'gray',
  }
  return DOT_COLOR[tones[status] ?? 'gray']
}

async function load() {
  if (!props.traceId) return
  loading.value = true
  error.value = ''
  detail.value = null
  try {
    detail.value = await getHarnessTraceDetail(props.traceId)
  } catch (currentError) {
    error.value = currentError instanceof Error ? currentError.message : '加载失败'
  } finally {
    loading.value = false
  }
}

watch(
  () => props.traceId,
  () => {
    if (props.traceId && visible.value) load()
  },
)

watch(
  visible,
  (open) => {
    if (open && props.traceId) load()
  },
  { immediate: true },
)
</script>

<style scoped>
.tdd {
  display: flex;
  flex-direction: column;
  height: 100%;
  color: #c9d8f2;
}

.tdd-head {
  flex: none;
  padding: 20px 22px 16px;
  border-bottom: 1px solid #1b2a45;
  background: rgb(3 9 18 / 55%);
}

.tdd-head__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.tdd-head__id {
  font-size: 15px;
  color: #eaf6ff;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tdd-head__meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
  font-size: 12px;
  color: #6d82a8;
}

.tdd-head__meta .mc-chip.st-violet {
  color: #a9a1ff;
  border-color: rgb(169 161 255 / 32%);
  background: rgb(169 161 255 / 8%);
}

.tdd-scroll {
  flex: 1;
  overflow: auto;
  padding: 4px 22px 30px;
}

.tdd-sec {
  padding: 18px 0;
  border-bottom: 1px dashed #1b2a45;
}

.tdd-sec:last-child {
  border-bottom: 0;
}

.tdd-sec__title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 12px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: #6d82a8;
}

.tdd-sec__title::before {
  content: '';
  width: 3px;
  height: 11px;
  border-radius: 2px;
  background: linear-gradient(180deg, #3ee0ff, transparent);
}

.tdd-intent {
  display: flex;
  align-items: center;
  gap: 10px;
}

.tdd-intent__conf {
  font-size: 12px;
  color: #6d82a8;
}

.tdd-pre {
  margin: 0;
  padding: 12px;
  border: 1px solid #1b2a45;
  border-radius: 10px;
  background: rgb(3 9 18 / 55%);
  font-family: ui-monospace, Menlo, Consolas, monospace;
  font-size: 11px;
  line-height: 1.7;
  color: #46587a;
  overflow: auto;
}

/* Plan */
.tdd-plan {
  display: grid;
  gap: 10px;
}

.tdd-plan-step {
  padding: 12px 14px;
  border: 1px solid #1b2a45;
  border-radius: 10px;
  background: rgb(3 9 18 / 45%);
}

.tdd-plan-step__head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.tdd-plan-step__id {
  font-size: 12px;
  color: #3ee0ff;
}

.tdd-plan-step__agent {
  font-size: 12px;
  color: #c9d8f2;
}

.tdd-plan-step__deps {
  font-size: 11px;
  color: #46587a;
}

.tdd-plan-step__goal {
  margin-top: 7px;
  font-size: 12px;
  color: #6d82a8;
}

.tdd-plan-step__io {
  display: grid;
  gap: 5px;
  margin-top: 9px;
}

.tdd-plan-step__io > div {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.tdd-plan-step__io code {
  font-family: ui-monospace, Menlo, Consolas, monospace;
  font-size: 10.5px;
  color: #8ea4c8;
  word-break: break-all;
}

.tdd-io-tag {
  flex: none;
  margin-top: 1px;
  padding: 0 5px;
  border-radius: 4px;
  font-family: ui-monospace, Menlo, Consolas, monospace;
  font-size: 9px;
  color: #04121c;
  background: #3ee0ff;
}

/* Timeline */
.tdd-timeline {
  display: grid;
  gap: 0;
}

.tdd-tl {
  display: grid;
  grid-template-columns: 22px 1fr;
  gap: 4px;
}

.tdd-tl__rail {
  position: relative;
  display: flex;
  justify-content: center;
}

.tdd-tl__dot {
  width: 9px;
  height: 9px;
  margin-top: 5px;
  border-radius: 50%;
  box-shadow: 0 0 8px currentColor;
}

.tdd-tl__rail::after {
  content: '';
  position: absolute;
  top: 16px;
  bottom: -2px;
  width: 1px;
  background: #1b2a45;
}

.tdd-tl:last-child .tdd-tl__rail::after {
  display: none;
}

.tdd-tl__body {
  padding: 2px 0 16px 6px;
}

.tdd-tl__head {
  display: flex;
  align-items: center;
  gap: 9px;
  flex-wrap: wrap;
}

.tdd-tl__id {
  font-size: 12px;
  color: #3ee0ff;
}

.tdd-tl__agent {
  font-size: 12px;
  color: #c9d8f2;
}

.tdd-tl__latency {
  margin-left: auto;
  font-size: 11px;
  color: #6d82a8;
}

.tdd-tl__goal {
  margin-top: 6px;
  font-size: 12px;
  color: #6d82a8;
}

.tdd-tl__sum {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.7;
  color: #c9d8f2;
  white-space: pre-wrap;
}

.tdd-tl__err {
  margin-top: 6px;
  font-size: 11px;
  color: #ff6b81;
}

.tdd-tl__counts {
  margin-top: 6px;
  font-size: 11px;
  color: #46587a;
}

/* Review */
.tdd-review {
  display: grid;
  gap: 10px;
}

.tdd-review__verdict {
  display: flex;
  align-items: center;
  gap: 9px;
  font-size: 13px;
  color: #c9d8f2;
}

.tdd-review__failed {
  font-size: 12px;
  color: #ff6b81;
}

.tdd-review__issue {
  display: flex;
  align-items: center;
  gap: 9px;
  font-size: 12px;
  flex-wrap: wrap;
}

.tdd-review__l2 {
  font-size: 12px;
  color: #6d82a8;
}

/* Answer */
.tdd-answer {
  margin: 0;
  padding: 14px;
  border: 1px solid #1b2a45;
  border-radius: 10px;
  background: rgb(3 9 18 / 45%);
  font-size: 13px;
  line-height: 1.8;
  color: #c9d8f2;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
}

/* Citations */
.tdd-cites {
  display: grid;
  gap: 8px;
}

.tdd-cite {
  display: flex;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid #1b2a45;
  border-radius: 10px;
  background: rgb(3 9 18 / 45%);
}

.tdd-cite__idx {
  flex: none;
  font-size: 12px;
  color: #3ee0ff;
}

.tdd-cite__body {
  min-width: 0;
}

.tdd-cite__title {
  font-size: 12px;
  line-height: 1.6;
  color: #c9d8f2;
  word-break: break-word;
}

.tdd-cite__meta {
  margin-top: 3px;
  font-size: 10.5px;
  color: #46587a;
}

/* Eval */
.tdd-eval {
  display: grid;
  gap: 14px;
}

.tdd-eval__block {
  display: grid;
  gap: 10px;
}

.tdd-eval__head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #6d82a8;
}

.mc-err {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  height: 100%;
  min-height: 240px;
}

.mc-err__msg {
  margin: 0;
  font-size: 13px;
  color: #ff6b81;
}

.mc-err__btn {
  padding: 7px 16px;
  border: 1px solid #1b2a45;
  border-radius: 9px;
  cursor: pointer;
  font-size: 12px;
  color: #c9d8f2;
  background: rgb(255 255 255 / 4%);
}

.mc-err__btn:hover {
  border-color: #3ee0ff;
  color: #3ee0ff;
}
</style>
