<!--
  多 Agent 步骤时间线组件:展示 v2 编排 pipeline 的 agent_start/agent_end 执行进度。
  与 NodeTimeline(v1 节点级)互补:这里展示"合同理解 / 规则检测 / 要素提取 / 法条检索 / 风险报告 / 报告合成"
  等 Agent 级步骤,让深度报告生成过程有可见进度,不再长时间静默。
-->
<template>
  <div class="agent-timeline">
    <div
      v-for="step in orderedSteps"
      :key="step.step_id"
      class="agent-step"
      :class="stateClass(step.agent)"
      :title="step.goal"
    >
      <span class="agent-dot">
        <Check
          v-if="isDone(step.agent)"
          :size="10"
        />
        <X
          v-else-if="isFailed(step.agent)"
          :size="10"
        />
        <Loader2
          v-else-if="isRunning(step.agent)"
          :size="10"
          class="spin"
        />
        <span
          v-else
          class="agent-num"
        >{{ step.order }}</span>
      </span>
      <span class="agent-label">{{ agentLabel(step.agent) }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Check, Loader2, X } from 'lucide-vue-next'

// v2 编排预置步骤,对齐 agent_service.orchestrator.workflow 的 Agent 名。
export interface AgentStep {
  step_id: string
  agent: string
  goal?: string
  order?: number
}

const props = defineProps<{
  steps: AgentStep[]
  // 当前正在执行的 Agent 名。
  currentAgent?: string | null
  // 已完成的 Agent 名集合。
  finishedAgents?: Set<string>
  // 执行失败的 Agent 名集合。
  failedAgents?: Set<string>
}>()

const agentMeta: Record<string, string> = {
  contract_clause: '合同理解',
  contract_rule: '规则检测',
  contract_elements: '要素提取',
  contract_rag: '法条检索',
  contract_risk_report: '风险报告',
  synthesize: '报告合成',
  law_qa: '法律咨询',
  article_locate: '法条定位',
  case_analysis: '案例分析',
}

// 按传入顺序补序号;同一 Agent 名在步骤里去重(重跑步不计入两次)。
const orderedSteps = computed<AgentStep[]>(() => {
  const seen = new Set<string>()
  const result: AgentStep[] = []
  for (const step of props.steps) {
    if (!step.agent || seen.has(step.agent)) continue
    seen.add(step.agent)
    result.push({ ...step, order: result.length + 1 })
  }
  return result
})

function agentLabel(agent: string): string {
  return agentMeta[agent] ?? agent
}

function isDone(agent: string): boolean {
  return Boolean(props.finishedAgents?.has(agent)) && !isFailed(agent)
}

function isFailed(agent: string): boolean {
  return Boolean(props.failedAgents?.has(agent))
}

function isRunning(agent: string): boolean {
  return props.currentAgent === agent && !props.finishedAgents?.has(agent)
}

function stateClass(agent: string): string {
  if (isFailed(agent)) return 'is-failed'
  if (isDone(agent)) return 'is-done'
  if (isRunning(agent)) return 'is-running'
  return ''
}
</script>

<style scoped>
.agent-timeline {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  padding: 10px 12px;
  border: 1px solid var(--law-border);
  border-radius: 10px;
  background: var(--law-bg);
}

.agent-step {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 9px;
  border-radius: 999px;
  background: var(--law-card);
  border: 1px solid var(--law-border);
  font-size: 11.5px;
  color: var(--law-muted);
  transition:
    border-color 160ms ease,
    background 160ms ease,
    color 160ms ease;
}

.agent-dot {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: rgb(37 99 235 / 8%);
  color: var(--law-primary-strong);
  font-size: 10px;
  flex-shrink: 0;
}

.agent-num {
  font-variant-numeric: tabular-nums;
  font-weight: 800;
  font-size: 10px;
}

.agent-label {
  font-weight: 700;
  white-space: nowrap;
}

.agent-step.is-running {
  border-color: var(--law-primary);
  background: rgb(37 99 235 / 8%);
  color: var(--law-primary-strong);
}

.agent-step.is-running .agent-dot {
  background: rgb(37 99 235 / 16%);
}

.agent-step.is-done {
  border-color: rgb(16 185 129 / 40%);
  background: rgb(16 185 129 / 8%);
  color: rgb(5 122 85);
}

.agent-step.is-done .agent-dot {
  background: rgb(16 185 129 / 14%);
}

:global(html.dark) .agent-step.is-done {
  color: rgb(94 234 212);
}

.agent-step.is-failed {
  border-color: rgb(239 68 68 / 40%);
  background: rgb(239 68 68 / 8%);
  color: rgb(185 28 28);
}

.agent-step.is-failed .agent-dot {
  background: rgb(239 68 68 / 14%);
}

:global(html.dark) .agent-step.is-failed {
  color: rgb(252 165 165);
}

.spin {
  animation: agent-spin 0.9s linear infinite;
}

@keyframes agent-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
