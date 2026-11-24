<!-- 运营监控控制台：深色驾驶舱外壳，承载总览 / 链路追踪 / LLM 用量 / 质量评估 / 检索健康 五个 Tab。 -->
<template>
  <div class="monitor-console">
    <header class="mc-console-head">
      <div class="mc-console-title">
        <h1>运营监控</h1>
        <p>HARNESS CONSOLE · doc 21 · 全链路可观测 / 护栏 / 评估 / A/B</p>
      </div>
      <div class="mc-console-tools">
        <div
          class="mc-range"
          role="group"
          aria-label="时间范围"
        >
          <button
            v-for="days in RANGES"
            :key="days"
            type="button"
            :class="{ active: sinceDays === days }"
            @click="setRange(days)"
          >
            {{ days }}D
          </button>
        </div>
        <button
          class="mc-refresh"
          :class="{ spinning: refreshing }"
          type="button"
          aria-label="刷新"
          @click="refresh"
        >
          <RefreshCw :size="15" />
        </button>
        <span
          v-if="syncedAt"
          class="mc-synced"
        >SYNC {{ syncedAt }}</span>
      </div>
    </header>

    <nav
      class="mc-tabs"
      aria-label="监控视图"
    >
      <button
        v-for="item in TABS"
        :key="item.key"
        type="button"
        :class="{ active: tab === item.key }"
        @click="switchTab(item.key)"
      >
        <span class="mc-tabs__num">{{ item.num }}</span>
        {{ item.label }}
      </button>
    </nav>

    <div class="mc-tab-body">
      <OverviewTab
        v-show="tab === 'overview'"
        :active="tab === 'overview'"
        :since-days="sinceDays"
        :refresh-tick="refreshTick"
      />
      <QuestionsTab
        v-show="tab === 'questions'"
        :active="tab === 'questions'"
        :since-days="sinceDays"
        :refresh-tick="refreshTick"
      />
      <TracesTab
        v-show="tab === 'traces'"
        :active="tab === 'traces'"
        :since-days="sinceDays"
        :refresh-tick="refreshTick"
      />
      <LlmTab
        v-show="tab === 'llm'"
        :active="tab === 'llm'"
        :since-days="sinceDays"
        :refresh-tick="refreshTick"
      />
      <QualityTab
        v-show="tab === 'quality'"
        :active="tab === 'quality'"
        :since-days="sinceDays"
        :refresh-tick="refreshTick"
      />
      <RagTab
        v-show="tab === 'rag'"
        :active="tab === 'rag'"
        :since-days="sinceDays"
        :refresh-tick="refreshTick"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { RefreshCw } from 'lucide-vue-next'

import LlmTab from './components/LlmTab.vue'
import OverviewTab from './components/OverviewTab.vue'
import QualityTab from './components/QualityTab.vue'
import QuestionsTab from './components/QuestionsTab.vue'
import RagTab from './components/RagTab.vue'
import TracesTab from './components/TracesTab.vue'
import './monitor.css'

const RANGES = [7, 14, 30, 90]
const TABS = [
  { key: 'overview', num: '01', label: '总览' },
  { key: 'questions', num: '02', label: '执行链路' },
  { key: 'traces', num: '03', label: '链路追踪' },
  { key: 'llm', num: '04', label: 'LLM 用量' },
  { key: 'quality', num: '05', label: '质量评估' },
  { key: 'rag', num: '06', label: '检索健康' },
] as const

type TabKey = (typeof TABS)[number]['key']

const tab = ref<TabKey>('overview')
const sinceDays = ref(30)
const refreshTick = ref(0)
const refreshing = ref(false)
const syncedAt = ref('')

function setRange(days: number) {
  if (sinceDays.value !== days) sinceDays.value = days
}

function switchTab(key: TabKey) {
  tab.value = key
}

function refresh() {
  refreshTick.value += 1
  refreshing.value = true
  syncedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
  window.setTimeout(() => {
    refreshing.value = false
  }, 700)
}

// 初始同步一次时间
syncedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })

watch(refreshTick, () => {
  syncedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
})
</script>
