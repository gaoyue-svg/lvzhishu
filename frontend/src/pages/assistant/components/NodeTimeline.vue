<!--
  节点时间线组件:展示 Agent SSE 流中 node_start/node_end 事件的执行进度。
  - intent / retrieve / retrieve_judge / tool_decide / tool_exec / reason / citation / validate
  - 当前节点显示脉冲点,已完成节点显示对勾,未开始节点灰显
-->
<template>
  <div class="node-timeline">
    <div
      v-for="node in orderedNodes"
      :key="node.key"
      class="node-chip"
      :class="stateOf(node.key)"
    >
      <span class="node-dot">
        <Check
          v-if="stateOf(node.key) === 'done'"
          :size="10"
        />
        <Loader2
          v-else-if="stateOf(node.key) === 'running'"
          :size="10"
          class="spin"
        />
        <span
          v-else
          class="node-num"
        >{{ node.order }}</span>
      </span>
      <span class="node-label">{{ node.label }}</span>
      <span
        v-if="node.key === 'retrieve' && chunkCount !== null"
        class="node-meta"
      >{{ chunkCount }} 段</span>
      <span
        v-if="node.key === 'tool_exec' && toolCount !== null && toolCount > 0"
        class="node-meta"
      >{{ toolCount }} 工具</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Check, Loader2 } from 'lucide-vue-next'

// 节点定义顺序,对齐 agent_service.agents.BaseAgent.astream 的执行流。
interface NodeDef {
  key: string
  label: string
  order: number
}

const orderedNodes: NodeDef[] = [
  { key: 'intent', label: '分析意图', order: 1 },
  { key: 'retrieve', label: '检索依据', order: 2 },
  { key: 'tool_exec', label: '调用工具', order: 3 },
  { key: 'reason', label: '组织答复', order: 4 },
  { key: 'citation', label: '整理引用', order: 5 },
  { key: 'validate', label: '风险校验', order: 6 },
]

// 节点状态:pending / running / done。
type NodeState = 'pending' | 'running' | 'done'

const props = defineProps<{
  // 已结束的节点集合(node_end 触发时加入)。
  finishedNodes: Set<string>
  // 当前正在执行的节点(node_start 触发时设置)。
  currentNode: string | null
  // retrieve 节点命中的 chunk 数。
  chunkCount: number | null
  // tool_exec 节点执行的工具数。
  toolCount: number | null
}>()

// 计算单个节点的运行状态。
function stateOf(key: string): NodeState {
  if (props.finishedNodes.has(key)) return 'done'
  if (props.currentNode === key) return 'running'
  return 'pending'
}

// 是否有任何节点已启动,用于决定是否整体展开。
const hasStarted = computed(() => props.finishedNodes.size > 0 || props.currentNode !== null)
defineExpose({ hasStarted })
</script>

<style scoped>
.node-timeline {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  background: rgb(15 23 42 / 4%);
  border: 1px solid var(--law-border);
  border-radius: 10px;
  font-size: 12px;
  color: var(--law-muted);
}

:global(html.dark) .node-timeline {
  background: rgb(255 255 255 / 4%);
}

.node-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 9px 3px 4px;
  border-radius: 999px;
  background: var(--law-card);
  border: 1px solid var(--law-border);
  transition: all 220ms ease;
  white-space: nowrap;
}

.node-chip.running {
  border-color: rgb(37 99 235 / 50%);
  background: rgb(37 99 235 / 8%);
  color: var(--law-primary-strong);
  box-shadow: 0 0 0 3px rgb(37 99 235 / 8%);
}

.node-chip.done {
  border-color: rgb(16 185 129 / 40%);
  background: rgb(16 185 129 / 8%);
  color: rgb(5 122 85);
}

:global(html.dark) .node-chip.done {
  color: rgb(94 234 212);
}

.node-dot {
  width: 16px;
  height: 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--law-border);
  color: var(--law-muted);
  flex-shrink: 0;
}

.node-chip.running .node-dot {
  background: var(--law-primary);
  color: #fff;
}

.node-chip.done .node-dot {
  background: rgb(16 185 129);
  color: #fff;
}

.node-num {
  font-size: 10px;
  font-weight: 700;
  line-height: 1;
}

.node-label {
  font-weight: 600;
  letter-spacing: 0.02em;
}

.node-meta {
  margin-left: 2px;
  padding: 1px 6px;
  border-radius: 999px;
  background: rgb(245 158 11 / 16%);
  color: rgb(180 83 9);
  font-size: 10px;
  font-weight: 700;
}

:global(html.dark) .node-meta {
  color: rgb(252 211 77);
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
