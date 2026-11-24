<!-- 链路追踪 Tab：可筛选的 run 追踪表 + 详情抽屉。 -->
<template>
  <div
    v-loading="loading"
    element-loading-background="rgba(6, 10, 18, 0.7)"
    class="mc-tr"
  >
    <PanelFrame title="Run 追踪">
      <template #actions>
        <div class="mc-filterbar">
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
          <div class="mc-field">
            <span class="mc-field__label">意图</span>
            <select
              v-model="filters.intent"
              class="mc-select"
            >
              <option value="">全部</option>
              <option
                v-for="intent in intents"
                :key="intent"
                :value="intent"
              >{{ intentLabel(intent) }}</option>
            </select>
          </div>
          <input
            v-model="filters.q"
            class="mc-input"
            placeholder="关键词搜索 query…"
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
              <th>QUERY</th>
              <th>意图</th>
              <th>状态</th>
              <th>延迟</th>
              <th>步数</th>
              <th>变体</th>
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
                <span class="mc-chip st-gray">{{ intentLabel(item.intent) }}</span>
              </td>
              <td>
                <StatusChip :status="item.status" />
              </td>
              <td class="mc-td-mono">{{ formatMs(item.total_latency_ms) }}</td>
              <td class="mc-td-mono">{{ item.step_count }}</td>
              <td class="mc-td-mono">{{ item.experiment_variant || '—' }}</td>
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
                colspan="9"
              >该范围内暂无 run 追踪记录</td>
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

    <TraceDetailDrawer
      :trace-id="selectedId"
      v-model="drawerOpen"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ChevronRight, Search } from 'lucide-vue-next'

import { getHarnessIntents, getHarnessTraces } from '@/api/harness'
import type { TraceItem } from '@/types/harness'

import PanelFrame from './PanelFrame.vue'
import StatusChip from './StatusChip.vue'
import TraceDetailDrawer from './TraceDetailDrawer.vue'
import { formatDateTime, formatMs, intentLabel, shortTraceId } from '../utils'

const props = defineProps<{
  active: boolean
  sinceDays: number
  refreshTick: number
}>()

const items = ref<TraceItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const error = ref('')
const intents = ref<string[]>([])
const drawerOpen = ref(false)
const selectedId = ref('')

const filters = ref<{ status: string; intent: string; q: string }>({ status: '', intent: '', q: '' })

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
    const response = await getHarnessTraces({
      page: page.value,
      page_size: pageSize,
      status: filters.value.status || undefined,
      intent: filters.value.intent || undefined,
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

async function loadIntents() {
  try {
    intents.value = (await getHarnessIntents(props.sinceDays)).intents
  } catch {
    intents.value = []
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

function openDetail(item: TraceItem) {
  selectedId.value = item.trace_id
  drawerOpen.value = true
}

watch(
  () => [props.active, props.sinceDays, props.refreshTick],
  () => {
    if (!props.active) return
    page.value = 1
    load()
    loadIntents()
  },
  { immediate: true },
)

watch(
  () => filters.value.status,
  () => {
    if (props.active) {
      page.value = 1
      load()
    }
  },
)

watch(
  () => props.sinceDays,
  () => {
    if (props.active) loadIntents()
  },
)
</script>

<style scoped>
.mc-tr {
  display: grid;
  gap: 16px;
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
