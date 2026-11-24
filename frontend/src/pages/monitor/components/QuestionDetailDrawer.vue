<!-- 提问执行链路详情抽屉：Agent 时间线 + 每个 Agent 嵌套的工具调用。 -->
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
      class="qdd"
    >
      <template v-if="detail">
        <header class="qdd-head">
          <div class="qdd-head__top">
            <span class="qdd-head__id mc-mono">{{ detail.trace_id }}</span>
            <div class="qdd-head__chips">
              <StatusChip :status="detail.status" />
              <span
                class="mc-chip"
                :class="`st-${engineTone(detail.engine)}`"
              >{{ engineLabel(detail.engine) }}</span>
            </div>
          </div>
          <div class="qdd-head__meta">
            <span>{{ formatDateTime(detail.created_at) }}</span>
            <span>·</span>
            <span class="mc-mono">{{ formatMs(detail.total_latency_ms) }}</span>
            <span>·</span>
            <span class="mc-mono">{{ detail.agent_count }} 个 Agent</span>
            <span>·</span>
            <span class="mc-mono">{{ detail.tool_count }} 次工具调用</span>
          </div>
        </header>

        <div class="qdd-scroll">
          <section class="qdd-sec">
            <h3 class="qdd-sec__title">提问</h3>
            <div class="qdd-query">{{ detail.query || '—' }}</div>
            <div
              v-if="detail.error"
              class="qdd-error"
            >{{ detail.error }}</div>
          </section>

          <section class="qdd-sec">
            <h3 class="qdd-sec__title">执行链路 · Agent → 工具</h3>
            <div
              v-if="agents.length"
              class="qdd-timeline"
            >
              <div
                v-for="agent in agents"
                :key="`${agent.agent}-${agent.round}`"
                class="qdd-agent"
              >
                <div class="qdd-agent__rail">
                  <span
                    class="qdd-agent__dot"
                    :style="{ background: dotColor(agent.status) }"
                  />
                </div>
                <div class="qdd-agent__body">
                  <div class="qdd-agent__head">
                    <span class="qdd-agent__name">{{ agentLabel(agent.agent) }}</span>
                    <span class="qdd-agent__key mc-mono">{{ agent.agent }}</span>
                    <span class="qdd-agent__round mc-mono">R{{ agent.round }}</span>
                    <StatusChip :status="agent.status" />
                    <span class="qdd-agent__latency mc-mono">{{ formatMs(agent.latency_ms) }}</span>
                  </div>

                  <div
                    v-if="agent.input_summary"
                    class="qdd-agent__sub"
                  ><span class="qdd-tag">子任务</span>{{ agent.input_summary }}</div>

                  <div
                    v-if="agent.output_summary"
                    class="qdd-agent__out"
                  ><span class="qdd-tag dim">产出</span>{{ agent.output_summary }}</div>

                  <div
                    v-if="agent.chunks_count || agent.citations_count"
                    class="qdd-agent__counts mc-mono"
                  >chunks {{ agent.chunks_count }} · cites {{ agent.citations_count }}</div>

                  <!-- 嵌套工具调用 -->
                  <div
                    v-if="agent.tools.length"
                    class="qdd-tools"
                  >
                    <div
                      v-for="(tool, index) in agent.tools"
                      :key="`${agent.agent}-t${index}`"
                      class="qdd-tool"
                    >
                      <div class="qdd-tool__head">
                        <span class="qdd-tool__icon">{{ tool.ok ? '●' : '✕' }}</span>
                        <span class="qdd-tool__name">{{ toolLabel(tool.name) }}</span>
                        <span class="qdd-tool__key mc-mono">{{ tool.name }}</span>
                        <span
                          class="mc-chip"
                          :class="tool.ok ? 'st-green' : 'st-red'"
                        >{{ tool.ok ? '成功' : '失败' }}</span>
                        <span class="qdd-tool__latency mc-mono">{{ formatMs(tool.latency_ms) }}</span>
                      </div>
                      <div
                        v-if="tool.input_summary"
                        class="qdd-tool__io"
                      ><span class="qdd-tag">入参</span><code>{{ tool.input_summary }}</code></div>
                      <div
                        v-if="tool.output_summary"
                        class="qdd-tool__io"
                      ><span class="qdd-tag dim">出参</span><code>{{ tool.output_summary }}</code></div>
                    </div>
                  </div>
                  <div
                    v-else
                    class="qdd-agent__no-tool"
                  >未调用工具</div>
                </div>
              </div>
            </div>
            <div
              v-else
              class="mc-empty"
            >该提问未产生 Agent 调用记录</div>
          </section>

          <section
            v-if="detail.answer_snippet"
            class="qdd-sec"
          >
            <h3 class="qdd-sec__title">回答摘要</h3>
            <pre class="qdd-answer">{{ detail.answer_snippet }}</pre>
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

import { getHarnessQuestionDetail } from '@/api/harness'
import type { ExecutionAgent, QuestionDetail } from '@/types/harness'

import StatusChip from './StatusChip.vue'
import { agentLabel, engineLabel, engineTone, formatDateTime, formatMs, toolLabel } from '../utils'

const props = defineProps<{
  traceId: string
}>()

const visible = defineModel<boolean>({ required: true })

const detail = ref<QuestionDetail | null>(null)
const loading = ref(false)
const error = ref('')

const agents = computed<ExecutionAgent[]>(() => detail.value?.agents ?? [])

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
    detail.value = await getHarnessQuestionDetail(props.traceId)
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
.qdd {
  display: flex;
  flex-direction: column;
  height: 100%;
  color: #c9d8f2;
}

.qdd-head {
  flex: none;
  padding: 20px 22px 16px;
  border-bottom: 1px solid #1b2a45;
  background: rgb(3 9 18 / 55%);
}

.qdd-head__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.qdd-head__id {
  font-size: 15px;
  color: #eaf6ff;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.qdd-head__chips {
  display: flex;
  align-items: center;
  gap: 7px;
  flex: none;
}

.qdd-head__meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
  font-size: 12px;
  color: #6d82a8;
}

.qdd-scroll {
  flex: 1;
  overflow: auto;
  padding: 4px 22px 30px;
}

.qdd-sec {
  padding: 18px 0;
  border-bottom: 1px dashed #1b2a45;
}

.qdd-sec:last-child {
  border-bottom: 0;
}

.qdd-sec__title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 12px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: #6d82a8;
}

.qdd-sec__title::before {
  content: '';
  width: 3px;
  height: 11px;
  border-radius: 2px;
  background: linear-gradient(180deg, #3ee0ff, transparent);
}

.qdd-query {
  font-size: 14px;
  line-height: 1.8;
  color: #eaf6ff;
  white-space: pre-wrap;
  word-break: break-word;
}

.qdd-error {
  margin-top: 10px;
  padding: 10px 12px;
  border: 1px solid rgb(255 107 129 / 32%);
  border-radius: 9px;
  font-size: 12px;
  color: #ff6b81;
  background: rgb(255 107 129 / 7%);
}

/* Agent 时间线 */
.qdd-timeline {
  display: grid;
  gap: 0;
}

.qdd-agent {
  display: grid;
  grid-template-columns: 22px 1fr;
  gap: 4px;
}

.qdd-agent__rail {
  position: relative;
  display: flex;
  justify-content: center;
}

.qdd-agent__dot {
  width: 10px;
  height: 10px;
  margin-top: 6px;
  border-radius: 50%;
  box-shadow: 0 0 9px currentColor;
}

.qdd-agent__rail::after {
  content: '';
  position: absolute;
  top: 18px;
  bottom: -2px;
  width: 1px;
  background: #1b2a45;
}

.qdd-agent:last-child .qdd-agent__rail::after {
  display: none;
}

.qdd-agent__body {
  padding: 2px 0 18px 8px;
}

.qdd-agent__head {
  display: flex;
  align-items: center;
  gap: 9px;
  flex-wrap: wrap;
}

.qdd-agent__name {
  font-size: 13px;
  font-weight: 600;
  color: #eaf6ff;
}

.qdd-agent__key {
  font-size: 10.5px;
  color: #3ee0ff;
}

.qdd-agent__round {
  font-size: 10.5px;
  color: #46587a;
}

.qdd-agent__latency {
  margin-left: auto;
  font-size: 11px;
  color: #6d82a8;
}

.qdd-agent__sub,
.qdd-agent__out {
  margin-top: 7px;
  display: flex;
  gap: 7px;
  align-items: flex-start;
  font-size: 12px;
  line-height: 1.7;
  color: #8ea4c8;
  word-break: break-word;
}

.qdd-agent__out {
  color: #c9d8f2;
}

.qdd-tag {
  flex: none;
  margin-top: 1px;
  padding: 0 5px;
  border-radius: 4px;
  font-family: ui-monospace, Menlo, Consolas, monospace;
  font-size: 9px;
  color: #04121c;
  background: #3ee0ff;
}

.qdd-tag.dim {
  background: #6d82a8;
}

.qdd-agent__counts {
  margin-top: 6px;
  font-size: 11px;
  color: #46587a;
}

.qdd-agent__no-tool {
  margin-top: 8px;
  font-size: 11px;
  color: #46587a;
}

/* 工具 */
.qdd-tools {
  display: grid;
  gap: 8px;
  margin-top: 10px;
}

.qdd-tool {
  padding: 10px 12px;
  border: 1px solid #1b2a45;
  border-radius: 9px;
  background: rgb(3 9 18 / 50%);
}

.qdd-tool__head {
  display: flex;
  align-items: center;
  gap: 9px;
  flex-wrap: wrap;
}

.qdd-tool__icon {
  font-size: 11px;
  color: #53e6a0;
}

.qdd-tool__name {
  font-size: 12px;
  color: #eaf6ff;
}

.qdd-tool__key {
  font-size: 10.5px;
  color: #6d82a8;
}

.qdd-tool__latency {
  margin-left: auto;
  font-size: 11px;
  color: #6d82a8;
}

.qdd-tool__io {
  margin-top: 6px;
  display: flex;
  gap: 7px;
  align-items: flex-start;
  font-size: 11px;
  line-height: 1.6;
  color: #8ea4c8;
}

.qdd-tool__io code {
  font-family: ui-monospace, Menlo, Consolas, monospace;
  word-break: break-all;
  white-space: pre-wrap;
}

.qdd-answer {
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
