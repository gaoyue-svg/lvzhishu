<template>
  <div class="law-search-page">
    <section class="search-hero">
      <div class="hero-copy">
        <div class="eyebrow"><Scale :size="16" /> 法律法规检索</div>
        <h1>快速定位法条与司法解释</h1>
        <p>从已入库的现行法律法规中检索，直接查看命中的条款原文与来源信息。</p>
      </div>

      <div class="search-box">
        <el-input
          v-model="query"
          size="large"
          clearable
          placeholder="输入法律名称、条款或问题，例如：民法典关于诉讼时效的规定"
          @keyup.enter="search"
        >
          <template #prefix><Search :size="19" /></template>
          <template #append>
            <el-button type="primary" :loading="searching" @click="search">检索法条</el-button>
          </template>
        </el-input>
        <div class="search-options">
          <span>检索范围</span>
          <el-select v-model="selectedKbIds" multiple collapse-tags placeholder="请选择知识库">
            <el-option v-for="kb in legalKnowledgeBases" :key="kb.id" :label="kb.name" :value="String(kb.id)" />
          </el-select>
          <span v-if="latency" class="latency">本次检索 {{ latency }} ms</span>
        </div>
      </div>
    </section>

    <section v-if="!hasSearched" class="guide-panel">
      <div class="guide-title"><Sparkles :size="19" /> 可以这样检索</div>
      <div class="query-chips">
        <button v-for="item in examples" :key="item" type="button" @click="useExample(item)">{{ item }}</button>
      </div>
      <div class="guide-grid">
        <div><BookOpen :size="20" /><strong>按法律名称</strong><span>民法典、劳动合同法、刑法</span></div>
        <div><Hash :size="20" /><strong>按具体条款</strong><span>民法典第一百八十八条</span></div>
        <div><MessageSquareText :size="20" /><strong>按法律问题</strong><span>拖欠工资可以主张哪些权利</span></div>
      </div>
    </section>

    <section v-else class="result-panel">
      <div class="result-header">
        <div>
          <h2>检索结果</h2>
          <p v-if="!searching">找到 {{ results.length }} 条与“{{ searchedQuery }}”相关的内容</p>
        </div>
        <el-tag v-if="intentLabel" effect="plain">{{ intentLabel }}</el-tag>
      </div>

      <div v-if="searching" class="loading-list">
        <el-skeleton v-for="item in 4" :key="item" animated :rows="3" />
      </div>
      <el-empty v-else-if="!results.length" description="未检索到相关条款，请更换关键词或扩大检索范围" />
      <div v-else class="result-list">
        <article v-for="(item, index) in results" :key="item.chunk_id" class="result-card">
          <div class="rank">{{ index + 1 }}</div>
          <div class="result-content">
            <div class="result-meta">
              <span class="law-name">{{ lawTitle(item) }}</span>
              <el-tag v-if="item.article_no" size="small" type="success" effect="light">{{ item.article_no }}</el-tag>
              <span v-if="item.hierarchy_path" class="hierarchy">{{ item.hierarchy_path }}</span>
            </div>
            <p>{{ formatResultText(item.text) }}</p>
            <div class="result-footer">
              <span><FileText :size="14" /> {{ sourceLabel(item) }}</span>
              <span v-if="item.version">版本 {{ item.version }}</span>
              <span v-if="item.page_start">第 {{ item.page_start }} 页</span>
              <el-button text type="primary" @click="openOriginal(item)">查看条款原文 <ArrowRight :size="15" /></el-button>
            </div>
          </div>
        </article>
      </div>
    </section>

    <section class="history-panel">
      <div class="history-header">
        <div>
          <div class="guide-title"><History :size="19" /> 历史检索记录</div>
          <p>保留最近 20 次法规检索，可点击记录再次查询</p>
        </div>
        <el-button text :loading="historyLoading" @click="loadHistory"><RefreshCw :size="15" /> 刷新</el-button>
      </div>
      <el-skeleton v-if="historyLoading && !history.length" animated :rows="3" />
      <el-empty v-else-if="!history.length" :image-size="70" description="暂无法规检索记录" />
      <div v-else class="history-list">
        <div
          v-for="item in history"
          :key="item.trace_id"
          class="history-item"
          role="button"
          tabindex="0"
          @click="repeatSearch(item.query)"
          @keyup.enter="repeatSearch(item.query)"
        >
          <span class="history-icon"><Search :size="17" /></span>
          <span class="history-query">{{ item.query }}</span>
          <span class="history-intent">{{ intentName(item.intent_type || undefined) }}</span>
          <span class="history-detail">命中 {{ item.hit_count }} 条 · {{ formatHistoryTime(item.created_at) }}</span>
          <span class="history-actions">
            <button type="button" class="delete-history" title="删除该记录" @click.stop="removeHistory(item)">
              <Trash2 :size="16" />
            </button>
            <ArrowRight :size="16" />
          </span>
        </div>
      </div>
    </section>

    <el-drawer v-model="drawerVisible" size="min(680px, 92vw)" class="original-drawer">
      <template #header>
        <div class="drawer-heading">
          <span>条款原文</span>
          <small>{{ selectedResult ? lawTitle(selectedResult) : '' }}</small>
        </div>
      </template>
      <template v-if="selectedResult">
        <div class="original-meta">
          <el-tag v-if="selectedResult.article_no" type="success">{{ selectedResult.article_no }}</el-tag>
          <span v-if="selectedResult.hierarchy_path">{{ selectedResult.hierarchy_path }}</span>
        </div>
        <div class="original-text">{{ selectedResult.text }}</div>
        <div class="source-card">
          <strong>来源信息</strong>
          <div><span>法律名称</span>{{ lawTitle(selectedResult) }}</div>
          <div><span>来源文档</span>{{ sourceLabel(selectedResult) }}</div>
          <div v-if="selectedResult.version"><span>版本</span>{{ selectedResult.version }}</div>
          <div v-if="selectedResult.page_start"><span>原文页码</span>第 {{ selectedResult.page_start }} 页</div>
        </div>
        <el-button class="copy-button" type="primary" plain @click="copyOriginal"><Copy :size="16" /> 复制条款原文</el-button>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowRight, BookOpen, Copy, FileText, Hash, History, MessageSquareText, RefreshCw, Scale, Search, Sparkles, Trash2 } from 'lucide-vue-next'

import { listKnowledgeBases } from '@/api/kb'
import { debugRetrieve, deleteRetrieveHistory, listRetrieveHistory } from '@/api/retrieval'
import type { KnowledgeBase } from '@/types/kb'
import type { ChunkResultItem, RetrieveHistoryItem } from '@/types/retrieval'
import { useRoute } from 'vue-router'

const examples = ['民法典关于诉讼时效的规定', '劳动合同解除有哪些法定情形', '未成年人保护法对网络保护的规定']
const query = ref('')
const searchedQuery = ref('')
const knowledgeBases = ref<KnowledgeBase[]>([])
const selectedKbIds = ref<string[]>([])
const results = ref<ChunkResultItem[]>([])
const searching = ref(false)
const hasSearched = ref(false)
const latency = ref(0)
const intentLabel = ref('')
const drawerVisible = ref(false)
const selectedResult = ref<ChunkResultItem>()
const history = ref<RetrieveHistoryItem[]>([])
const historyLoading = ref(false)
const route = useRoute()

const legalKnowledgeBases = computed(() =>
  knowledgeBases.value.filter((kb) => ['law', 'judicial', 'case'].includes(kb.kb_type) && kb.status === 'enabled'),
)

onMounted(async () => {
  try {
    knowledgeBases.value = await listKnowledgeBases()
    selectedKbIds.value = legalKnowledgeBases.value.map((kb) => String(kb.id))
    await loadHistory()
    const routeQuery = typeof route.query.q === 'string' ? route.query.q.trim() : ''
    if (routeQuery) {
      query.value = routeQuery
      await search()
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '知识库加载失败')
  }
})

async function search() {
  const value = query.value.trim()
  if (!value) return ElMessage.warning('请输入要检索的法律名称、条款或问题')
  if (!selectedKbIds.value.length) return ElMessage.warning('请至少选择一个法规知识库')
  searching.value = true
  hasSearched.value = true
  searchedQuery.value = value
  try {
    const response = await debugRetrieve({
      query: value,
      kb_ids: selectedKbIds.value,
      agent_type: 'legal_search',
      // 这是候选上限，后端会按相关性动态返回 1~10 条，不再固定凑满。
      top_k: 10,
    })
    results.value = response.reranked_results
    latency.value = response.latency_ms.total
    intentLabel.value = intentName(response.query_intent?.intent_type)
    await loadHistory()
  } catch (error) {
    results.value = []
    ElMessage.error(error instanceof Error ? error.message : '法规检索失败')
  } finally {
    searching.value = false
  }
}

async function loadHistory() {
  historyLoading.value = true
  try {
    history.value = await listRetrieveHistory(20)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '检索历史加载失败')
  } finally {
    historyLoading.value = false
  }
}

function repeatSearch(value: string) {
  query.value = value
  window.scrollTo({ top: 0, behavior: 'smooth' })
  void search()
}

async function removeHistory(item: RetrieveHistoryItem) {
  try {
    await ElMessageBox.confirm(`确定删除“${item.query}”这条检索记录吗？`, '删除检索记录', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      confirmButtonClass: 'el-button--danger',
    })
    await deleteRetrieveHistory(item.trace_id)
    history.value = history.value.filter((record) => record.trace_id !== item.trace_id)
    ElMessage.success('检索记录已删除')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error instanceof Error ? error.message : '删除检索记录失败')
  }
}

function formatHistoryTime(value: string) {
  const date = new Date(value)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  if (diff >= 0 && diff < 60_000) return '刚刚'
  if (diff >= 0 && diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (date.toDateString() === now.toDateString()) return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function useExample(value: string) {
  query.value = value
  void search()
}

function openOriginal(item: ChunkResultItem) {
  selectedResult.value = item
  drawerVisible.value = true
}

async function copyOriginal() {
  if (!selectedResult.value) return
  await navigator.clipboard.writeText(selectedResult.value.text)
  ElMessage.success('条款原文已复制')
}

function lawTitle(item: ChunkResultItem) {
  return item.law_name || stringMeta(item, 'filename') || stringMeta(item, 'document_name') || '法律条文'
}

function sourceLabel(item: ChunkResultItem) {
  return stringMeta(item, 'filename') || stringMeta(item, 'document_name') || item.source_uri || '知识库原文'
}

function stringMeta(item: ChunkResultItem, key: string) {
  const value = item.metadata?.[key]
  return typeof value === 'string' ? value : ''
}

function formatResultText(text: string) {
  const lines = text.replace(/\r\n?/g, '\n').split('\n')
  const blocks: string[] = []
  let current = ''
  const structuralLine = /^(?:第[\u4e00-\u9fa5\d]+条|[（(][\u4e00-\u9fa5\d]+[）)]|[\u4e00-\u9fa5\d]+[\u3001.]|【)/

  const flush = () => {
    if (current) blocks.push(current)
    current = ''
  }
  for (const rawLine of lines) {
    const line = rawLine.trim()
    if (!line) {
      flush()
      continue
    }
    if (structuralLine.test(line) && current) flush()
    // PDF 内的换行通常只是页面宽度造成的视觉折行，应合并回同一段。
    current += line
  }
  flush()
  const formatted = blocks.join('\n')
  return formatted.length > 900 ? `${formatted.slice(0, 900)}…` : formatted
}

function intentName(intent?: string) {
  const names: Record<string, string> = {
    article_locate: '法条定位', chapter_summary: '章节检索', law_qa: '法规问答', case_search: '案例检索',
  }
  return intent ? names[intent] || '智能检索' : ''
}
</script>

<style scoped>
.law-search-page { display: grid; gap: 20px; }
.search-hero, .guide-panel, .result-panel, .history-panel { border: 1px solid var(--law-border); border-radius: 18px; background: var(--law-card); box-shadow: var(--law-shadow); }
.search-hero { padding: 34px; background: linear-gradient(135deg, color-mix(in srgb, var(--el-color-primary) 8%, var(--law-card)) 0%, var(--law-card) 58%); }
.hero-copy { max-width: 760px; }
.eyebrow { display: flex; align-items: center; gap: 7px; color: var(--el-color-primary); font-weight: 700; font-size: 14px; }
h1 { margin: 12px 0 8px; color: var(--law-text); font-size: clamp(28px, 3vw, 40px); letter-spacing: -1px; }
.hero-copy p, .result-header p { margin: 0; color: var(--law-text-muted); }
.search-box { max-width: 980px; margin-top: 28px; }
.search-box :deep(.el-input-group__append) { padding: 0; background: var(--el-color-primary); border-color: var(--el-color-primary); }
.search-box :deep(.el-input-group__append .el-button) { height: 46px; margin: 0; padding: 0 26px; color: #fff; }
.search-options { display: flex; align-items: center; gap: 12px; margin-top: 13px; color: var(--law-text-muted); font-size: 13px; }
.search-options .el-select { width: min(420px, 65vw); }
.latency { margin-left: auto; }
.guide-panel, .result-panel, .history-panel { padding: 26px; }
.guide-title { display: flex; align-items: center; gap: 8px; color: var(--law-text); font-size: 18px; font-weight: 700; }
.query-chips { display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0 24px; }
.query-chips button { padding: 9px 14px; color: var(--el-color-primary); border: 1px solid color-mix(in srgb, var(--el-color-primary) 28%, var(--law-border)); border-radius: 999px; background: color-mix(in srgb, var(--el-color-primary) 5%, var(--law-card)); cursor: pointer; }
.query-chips button:hover { background: color-mix(in srgb, var(--el-color-primary) 11%, var(--law-card)); }
.guide-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.guide-grid > div { display: grid; grid-template-columns: auto 1fr; gap: 5px 10px; padding: 18px; border: 1px solid var(--law-border); border-radius: 14px; color: var(--el-color-primary); }
.guide-grid strong { color: var(--law-text); }
.guide-grid span { grid-column: 2; color: var(--law-text-muted); font-size: 13px; }
.result-header { display: flex; align-items: center; justify-content: space-between; padding-bottom: 20px; border-bottom: 1px solid var(--law-border); }
.result-header h2 { margin: 0 0 5px; color: var(--law-text); font-size: 22px; }
.loading-list { display: grid; gap: 18px; padding-top: 24px; }
.result-list { display: grid; }
.result-card { display: grid; grid-template-columns: 34px 1fr; gap: 16px; padding: 24px 4px; border-bottom: 1px solid var(--law-border); }
.result-card:last-child { border-bottom: 0; }
.rank { width: 30px; height: 30px; display: grid; place-items: center; border-radius: 9px; color: var(--el-color-primary); background: color-mix(in srgb, var(--el-color-primary) 10%, var(--law-card)); font-weight: 700; }
.result-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 9px; }
.law-name { color: var(--law-text); font-size: 17px; font-weight: 750; }
.hierarchy { color: var(--law-text-muted); font-size: 13px; }
.result-content { min-width: 0; }
.result-content > p { width: 100%; margin: 13px 0; color: var(--law-text); line-height: 1.85; white-space: pre-line; overflow-wrap: anywhere; }
.result-footer { display: flex; align-items: center; gap: 18px; color: var(--law-text-muted); font-size: 12px; }
.result-footer span { display: inline-flex; align-items: center; gap: 5px; }
.result-footer .el-button { margin-left: auto; }
.drawer-heading { display: grid; gap: 4px; color: var(--law-text); font-size: 20px; font-weight: 700; }
.drawer-heading small { color: var(--law-text-muted); font-size: 13px; font-weight: 500; }
.original-meta { display: flex; align-items: center; gap: 10px; color: var(--law-text-muted); }
.original-text { margin: 20px 0; padding: 24px; border-left: 4px solid var(--el-color-primary); border-radius: 0 12px 12px 0; background: var(--law-bg); color: var(--law-text); font-size: 16px; line-height: 2; white-space: pre-wrap; }
.source-card { display: grid; gap: 10px; padding: 18px; border: 1px solid var(--law-border); border-radius: 12px; color: var(--law-text); }
.source-card > div { display: grid; grid-template-columns: 90px 1fr; font-size: 13px; }
.source-card span { color: var(--law-text-muted); }
.copy-button { margin-top: 18px; }
.history-header { display: flex; align-items: flex-start; justify-content: space-between; padding-bottom: 18px; border-bottom: 1px solid var(--law-border); }
.history-header p { margin: 7px 0 0; color: var(--law-text-muted); font-size: 13px; }
.history-list { display: grid; }
.history-item { display: grid; grid-template-columns: auto minmax(180px, 1fr) auto auto auto; align-items: center; gap: 14px; width: 100%; padding: 16px 8px; border: 0; border-bottom: 1px solid var(--law-border); color: var(--law-text); background: transparent; text-align: left; cursor: pointer; }
.history-item:last-child { border-bottom: 0; }
.history-item:hover { background: color-mix(in srgb, var(--el-color-primary) 5%, transparent); }
.history-icon { width: 34px; height: 34px; display: grid; place-items: center; border-radius: 10px; color: var(--el-color-primary); background: color-mix(in srgb, var(--el-color-primary) 9%, var(--law-card)); }
.history-query { overflow: hidden; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.history-intent { padding: 4px 9px; border-radius: 999px; color: var(--el-color-primary); background: color-mix(in srgb, var(--el-color-primary) 8%, var(--law-card)); font-size: 12px; }
.history-detail { color: var(--law-text-muted); font-size: 12px; white-space: nowrap; }
.history-actions { display: inline-flex; align-items: center; gap: 10px; }
.delete-history { width: 32px; height: 32px; display: grid; place-items: center; padding: 0; border: 0; border-radius: 8px; color: var(--law-text-muted); background: transparent; cursor: pointer; }
.delete-history:hover { color: #dc2626; background: #fef2f2; }
@media (max-width: 760px) { .search-hero { padding: 24px 18px; } .guide-panel, .result-panel, .history-panel { padding: 20px 16px; } .guide-grid { grid-template-columns: 1fr; } .search-options { align-items: flex-start; flex-wrap: wrap; } .latency { margin-left: 0; } .result-footer { flex-wrap: wrap; } .result-footer .el-button { width: 100%; margin-left: 0; justify-content: flex-start; } .history-item { grid-template-columns: auto 1fr auto; } .history-intent { display: none; } .history-detail { grid-column: 2; } }
</style>
