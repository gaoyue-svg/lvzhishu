<!-- 执行链路 Tab：每个提问一行，展示其背后的 Agent 链与工具链，点击看详情。 -->
<template>
  <div
    v-loading="loading"
    element-loading-background="rgba(6, 10, 18, 0.7)"
    class="mc-qx"
  >
    <PanelFrame title="提问 → Agent → 工具">
      <template #actions>
        <div class="mc-filterbar">
          <div class="mc-field">
            <span class="mc-field__label">引擎</span>
            <select
              v-model="filters.engine"
              class="mc-select"
            >
              <option value="">全部</option>
              <option value="supervisor">Supervisor V1</option>
              <option value="pipeline_v2">Pipeline V2</option>
              <option value="single_agent">单 Agent</option>
            </select>
          </div>
          <div class="mc-field">
            <span class="mc-field__label">状态</span>
            <select
              v-model="filters.status"
              class="mc-select"
            >
              <option value="">全部</option>
              <option value="success">成功</option>
              <option value="failed">失败</option>
              <option value="hitl">待复核</option>
            </select>
          </div>
          <input
            v-model="filters.q"
            class="mc-input"
            placeholder="关键词搜索提问…"
            @keyup.enter="applyFilters"
          >
          <button
            class="mc-btn primary"
            type="button"
            @click="applyFilters"
          >
            <Search :size="14" />
            查询
          </button>
        </div>
      </template>

      <div
        v-if="error"
        class="mc-tr-error"
      >
        {{ error }}
        <button
          class="mc-btn"
          type="button"
          @click="load"
        >重试</button>
      </div>

      <div class="mc-table-wrap">
        <table class="mc-table">
          <thead>
            <tr>
              <th>TRACE</th>
              <th>时间</th>
              <th>提问</th>
              <th>引擎</th>
              <th>执行链路</th>
              <th>延迟</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in items"
              :key="item.trace_id"
              :class="{ 'is-hl': selectedId === item.trace_id }"
              @click="openDetail(item)"
            >
              <td class="mc-td-mono">{{ shortTraceId(item.trace_id) }}</td>
              <td class="mc-td-mono">{{ formatDateTime(item.created_at) }}</td>
              <td class="mc-td-query">{{ item.query || '—' }}</td>
              <td>
                <span
                  class="mc-chip"
                  :class="`st-${engineTone(item.engine)}`"
                >{{ engineLabel(item.engine) }}</span>
              </td>
              <td>
                <div class="mc-qx-chain">
                  <div class="mc-qx-chain__agents">
                    <template v-for="(agent, index) in item.agents" :key="`a-${index}`">
                      <span class="mc-qx-agent">{{ agentLabel(agent) }}</span>
                      <span
                        v-if="index < item.agents.length - 1"
                        class="mc-qx-arrow"
                      >→</span>
                    </template>
                  </div>
                  <div
                    v-if="item.tools.length"
                    class="mc-qx-chain__tools"
                  >
                    <span
                      v-for="(tool, index) in item.tools"
                      :key="`t-${index}`"
                      class="mc-qx-tool"
                    >⚒ {{ toolLabel(tool) }}</span>
                  </div>
                </div>
              </td>
              <td class="mc-td-mono">{{ formatMs(item.total_latency_ms) }}</td>
              <td>
                <ChevronRight
                  class="mc-row-arrow"
                  :size="15"
                />
              </td>
            </tr>
            <tr v-if="items.length === 0">
              <td
                class="mc-td-empty"
                colspan="7"
              >该范围内暂无提问执行记录</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="mc-pager">
        <span class="mc-pager__info">
          TOTAL {{ total.toLocaleString('en-US') }} · 第 {{ page }} / {{ totalPages }} 页
        </span>
        <div class="mc-pager__btns">
          <button
            class="mc-pager__btn"
            type="button"
            :disabled="page <= 1"
            @click="go(page - 1)"
          >‹</button>
          <button
            v-for="num in pageWindow"
            :key="num"
            class="mc-pager__btn"
            :class="{ active: num === page }"
            type="button"
            @click="go(num)"
          >{{ num }}</button>
          <button
            class="mc-pager__btn"
            type="button"
            :disabled="page >= totalPages"
            @click="go(page + 1)"
          >›</button>
        </div>
      </div>
    </PanelFrame>

    <QuestionDetailDrawer
      :trace-id="selectedId"
      v-model="drawerOpen"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ChevronRight, Search } from 'lucide-vue-next'

import { getHarnessQuestions } from '@/api/harness'
import type { QuestionItem } from '@/types/harness'

import PanelFrame from './PanelFrame.vue'
import QuestionDetailDrawer from './QuestionDetailDrawer.vue'
import { agentLabel, engineLabel, engineTone, formatDateTime, formatMs, shortTraceId, toolLabel } from '../utils'

const props = defineProps<{
  active: boolean
  sinceDays: number
  refreshTick: number
}>()

const items = ref<QuestionItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const error = ref('')
const drawerOpen = ref(false)
const selectedId = ref('')

const filters = ref<{ engine: string; status: string; q: string }>({ engine: '', status: '', q: '' })

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
const pageWindow = computed(() => {
  const current = page.value
  const range: number[] = []
  for (let num = Math.max(1, current - 2); num <= Math.min(totalPages.value, current + 2); num += 1) {
    range.push(num)
  }
  return range
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const response = await getHarnessQuestions({
      page: page.value,
      page_size: pageSize,
      engine: filters.value.engine || undefined,
      status: filters.value.status || undefined,
      q: filters.value.q || undefined,
      since_days: props.sinceDays,
    })
    items.value = response.items
    total.value = response.total
  } catch (currentError) {
    error.value = currentError instanceof Error ? currentError.message : '加载失败'
    items.value = []
  } finally {
    loading.value = false
  }
}

function applyFilters() {
  page.value = 1
  load()
}

function go(num: number) {
  if (num < 1 || num > totalPages.value || num === page.value) return
  page.value = num
  load()
}

function openDetail(item: QuestionItem) {
  selectedId.value = item.trace_id
  drawerOpen.value = true
}

watch(
  () => [props.active, props.sinceDays, props.refreshTick],
  () => {
    if (props.active) {
      page.value = 1
      load()
    }
  },
  { immediate: true },
)

watch(
  () => [filters.value.engine, filters.value.status],
  () => {
    if (props.active) {
      page.value = 1
      load()
    }
  },
)
</script>

<style scoped>
.mc-qx {
  display: grid;
  gap: 16px;
}

.mc-qx-chain {
  display: grid;
  gap: 6px;
  min-width: 260px;
}

.mc-qx-chain__agents {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px;
}

.mc-qx-agent {
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 11px;
  line-height: 18px;
  color: var(--mc-cyan);
  border: 1px solid rgb(62 224 255 / 30%);
  background: rgb(62 224 255 / 8%);
  white-space: nowrap;
}

.mc-qx-arrow {
  font-family: var(--mc-mono);
  font-size: 11px;
  color: var(--mc-faint);
}

.mc-qx-chain__tools {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px;
}

.mc-qx-tool {
  padding: 1px 7px;
  border-radius: 6px;
  font-size: 10.5px;
  color: var(--mc-dim);
  border: 1px dashed var(--mc-line);
  white-space: nowrap;
}

.mc-tr-error {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  margin-bottom: 10px;
  border: 1px solid rgb(255 107 129 / 30%);
  border-radius: 9px;
  font-size: 12px;
  color: var(--mc-red);
  background: rgb(255 107 129 / 7%);
}
</style>
