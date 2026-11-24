<!--
  本文件是文档列表与单文档管理表格:
  - 展示知识库下文档及其解析/向量化状态
  - 支持按解析状态筛选与按文件名搜索(查询能力)
  - 支持查看解析原文、重新解析和单篇删除
-->
<template>
  <section class="doc-panel">
    <header class="doc-toolbar">
      <div class="toolbar-left">
        <el-select
          v-model="parseStatus"
          placeholder="全部解析状态"
          clearable
          class="status-select"
          @change="loadDocuments(true)"
        >
          <el-option
            v-for="item in parseStatusOptions"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
        <el-input
          v-model="search"
          class="search-input"
          placeholder="搜索文件名"
          clearable
          :prefix-icon="Search"
        />
      </div>
      <div class="toolbar-right">
        <span class="doc-total">共 {{ total }} 篇文档</span>
        <el-button
          :icon="RefreshCw"
          text
          @click="loadDocuments()"
        >
          刷新
        </el-button>
      </div>
    </header>

    <el-table
      v-loading="loading"
      :data="filteredList"
      class="doc-table"
      row-key="id"
      stripe
    >
      <el-table-column
        label="文件名"
        min-width="220"
      >
        <template #default="{ row }: { row: DocumentDetail }">
          <div class="cell-file">
            <span
              class="file-icon"
              :class="row.file_type"
            >
              <FileText :size="15" />
            </span>
            <div class="file-main">
              <strong>{{ row.filename }}</strong>
              <small>{{ row.file_type.toUpperCase() }} · {{ formatFileSize(row.file_size) }}</small>
            </div>
          </div>
        </template>
      </el-table-column>

      <el-table-column
        label="解析状态"
        width="120"
      >
        <template #default="{ row }: { row: DocumentDetail }">
          <span
            class="status-pill"
            :class="parseStatusMeta[row.parse_status].tone"
          >
            <i class="pill-dot" />
            {{ parseStatusMeta[row.parse_status].label }}
          </span>
        </template>
      </el-table-column>

      <el-table-column
        label="向量化"
        width="130"
      >
        <template #default="{ row }: { row: DocumentDetail }">
          <span
            class="status-pill"
            :class="embeddingStatusMeta[row.embedding_status].tone"
          >
            <i class="pill-dot" />
            {{ embeddingStatusMeta[row.embedding_status].label }}
          </span>
        </template>
      </el-table-column>

      <el-table-column
        label="Chunk"
        width="90"
        align="center"
      >
        <template #default="{ row }: { row: DocumentDetail }">
          <span class="chunk-count">{{ row.chunk_count }}</span>
        </template>
      </el-table-column>

      <el-table-column
        label="上传时间"
        width="170"
      >
        <template #default="{ row }: { row: DocumentDetail }">
          <span class="cell-date">{{ formatDateTime(row.created_at) }}</span>
        </template>
      </el-table-column>

      <el-table-column
        label="操作"
        width="220"
        fixed="right"
        align="right"
      >
        <template #default="{ row }: { row: DocumentDetail }">
          <div class="row-actions">
            <el-button
              link
              type="primary"
              :icon="Eye"
              :disabled="row.parse_status !== 'completed'"
              @click="previewDocument(row)"
            >
              原文
            </el-button>
            <el-button
              link
              type="primary"
              :icon="RotateCw"
              :disabled="row.parse_status === 'parsing'"
              @click="handleReparse(row)"
            >
              重解析
            </el-button>
            <el-button
              link
              type="danger"
              :icon="Trash2"
              :disabled="row.parse_status === 'parsing'"
              @click="handleDelete(row)"
            >
              删除
            </el-button>
          </div>
        </template>
      </el-table-column>

      <template #empty>
        <el-empty
          :description="emptyText"
          :image-size="100"
        />
      </template>
    </el-table>

    <footer
      v-if="total > pageSize"
      class="doc-pagination"
    >
      <el-pagination
        v-model:current-page="page"
        :page-size="pageSize"
        :total="total"
        layout="prev, pager, next, total"
        background
        @current-change="loadDocuments()"
      />
    </footer>

    <el-dialog
      v-model="previewVisible"
      :title="previewTitle"
      width="min(860px, 90vw)"
      append-to-body
    >
      <div
        v-loading="previewLoading"
        class="markdown-preview"
      >
        <pre>{{ previewContent }}</pre>
      </div>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Eye, FileText, RefreshCw, RotateCw, Search, Trash2 } from 'lucide-vue-next'

import { deleteDocument, getDocumentMarkdown, listDocuments, reparseDocument } from '@/api/kb'
import { formatDateTime, formatFileSize } from '@/utils/format'
import type { DocumentDetail, ParseStatus } from '@/types/kb'

const props = defineProps<{
  kbId: number
}>()

const emit = defineEmits<{
  documentsChanged: []
}>()

const list = ref<DocumentDetail[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 10
const loading = ref(false)
const parseStatus = ref<ParseStatus | ''>('')
const search = ref('')
const previewVisible = ref(false)
const previewLoading = ref(false)
const previewTitle = ref('文档原文')
const previewContent = ref('')

const parseStatusOptions = [
  { label: '待解析', value: 'pending' },
  { label: '解析中', value: 'parsing' },
  { label: '解析完成', value: 'completed' },
  { label: '解析失败', value: 'failed' },
] as const

// 解析状态元数据:tone 控制徽章配色。
const parseStatusMeta: Record<ParseStatus, { label: string; tone: string }> = {
  pending: { label: '待解析', tone: 'muted' },
  parsing: { label: '解析中', tone: 'warning' },
  completed: { label: '完成', tone: 'success' },
  failed: { label: '失败', tone: 'danger' },
}

// 向量化状态元数据。
const embeddingStatusMeta: Record<string, { label: string; tone: string }> = {
  pending: { label: '待处理', tone: 'muted' },
  processing: { label: '处理中', tone: 'warning' },
  completed: { label: '完成', tone: 'success' },
  partial_failed: { label: '部分失败', tone: 'warning' },
  failed: { label: '失败', tone: 'danger' },
}

// 客户端按文件名搜索(后端 list 接口暂不支持关键字,本地兜底过滤当前页)。
const filteredList = computed(() => {
  const word = search.value.trim().toLowerCase()
  if (!word) return list.value
  return list.value.filter((doc) => doc.filename.toLowerCase().includes(word))
})

const emptyText = computed(() => {
  if (search.value) return '没有匹配的文档'
  if (parseStatus.value) return '当前状态下没有文档'
  return '该知识库还没有文档'
})

async function loadDocuments(resetPage = false) {
  if (resetPage) page.value = 1
  loading.value = true
  try {
    const result = await listDocuments({
      kb_id: props.kbId,
      parse_status: parseStatus.value || undefined,
      page: page.value,
      page_size: pageSize,
    })
    list.value = result.items
    total.value = result.total
  } catch (error) {
    list.value = []
    total.value = 0
    // 错误由全局拦截器提示,这里仅清空避免脏数据。
    console.error('[DocumentTable] load failed:', error)
  } finally {
    loading.value = false
  }
}

async function previewDocument(row: DocumentDetail) {
  previewVisible.value = true
  previewLoading.value = true
  previewTitle.value = `${row.filename} · 解析原文`
  previewContent.value = ''
  try {
    const result = await getDocumentMarkdown(row.id)
    previewContent.value = result.raw_markdown?.trim() || '该文档暂无解析原文。'
  } catch (error) {
    previewContent.value = '原文加载失败。'
    ElMessage.error(error instanceof Error ? error.message : '原文加载失败')
  } finally {
    previewLoading.value = false
  }
}

async function handleReparse(row: DocumentDetail) {
  try {
    await ElMessageBox.confirm(
      `确定重新解析「${row.filename}」吗？现有 Chunk 和向量索引将重新生成。`,
      '重新解析文档',
      { type: 'warning', confirmButtonText: '重新解析', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await reparseDocument(row.id)
    ElMessage.success('已提交重新解析任务')
    await loadDocuments()
    emit('documentsChanged')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '重新解析失败')
  }
}

async function handleDelete(row: DocumentDetail) {
  try {
    await ElMessageBox.confirm(
      `确定删除「${row.filename}」吗？该文档的原文件、Chunk 和向量索引将一并删除，且无法恢复。`,
      '删除单个文档',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
      },
    )
  } catch {
    return
  }
  try {
    await deleteDocument(row.id)
    ElMessage.success('文档已删除')
    if (list.value.length === 1 && page.value > 1) page.value--
    await loadDocuments()
    emit('documentsChanged')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '文档删除失败')
  }
}

watch(() => props.kbId, () => loadDocuments(true), { immediate: true })
</script>

<style scoped>
.doc-panel {
  display: grid;
  gap: 14px;
  padding: 18px;
  border: 1px solid var(--law-border);
  border-radius: 16px;
  background: var(--law-card);
  box-shadow: var(--law-shadow);
}

.doc-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 14px;
}

.status-select {
  width: 160px;
}

.search-input {
  width: 220px;
}

.doc-total {
  color: var(--law-muted);
  font-size: 13px;
}

.doc-table {
  width: 100%;
}

.cell-file {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.file-icon {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 9px;
  flex-shrink: 0;
  color: #2563eb;
  background: #dbeafe;
}

.file-icon.pdf {
  color: #b91c1c;
  background: #fee2e2;
}

.file-icon.docx {
  color: #1d4ed8;
  background: #dbeafe;
}

.file-icon.html {
  color: #c2410c;
  background: #ffedd5;
}

.file-icon.txt {
  color: #475569;
  background: #e2e8f0;
}

.file-main {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.file-main strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  font-weight: 600;
  color: var(--law-text);
}

.file-main small {
  color: var(--law-muted);
  font-size: 11px;
}

/* 状态胶囊:统一四种色调 */
.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
}

.status-pill .pill-dot {
  width: 6px;
  height: 6px;
  border-radius: 999px;
}

.status-pill.success {
  color: #15803d;
  background: #dcfce7;
}

.status-pill.success .pill-dot {
  background: #22c55e;
}

.status-pill.warning {
  color: #b45309;
  background: #fef3c7;
}

.status-pill.warning .pill-dot {
  background: #f59e0b;
}

.status-pill.danger {
  color: #b91c1c;
  background: #fee2e2;
}

.status-pill.danger .pill-dot {
  background: #ef4444;
}

.status-pill.muted {
  color: #475569;
  background: #e2e8f0;
}

.status-pill.muted .pill-dot {
  background: #94a3b8;
}

:global(html.dark) .status-pill.muted {
  color: #cbd5e1;
  background: var(--law-card-soft);
}

.chunk-count {
  font-weight: 700;
  color: var(--law-text);
}

.cell-date {
  color: var(--law-muted);
  font-size: 12px;
}

.row-actions {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  white-space: nowrap;
}

.markdown-preview {
  min-height: 220px;
  max-height: 65vh;
  overflow: auto;
  padding: 16px;
  border: 1px solid var(--law-border);
  border-radius: 12px;
  background: var(--law-card-soft);
}

.markdown-preview pre {
  margin: 0;
  color: var(--law-text);
  font-family: inherit;
  font-size: 13px;
  line-height: 1.8;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.doc-pagination {
  display: flex;
  justify-content: flex-end;
  padding-top: 4px;
}

@media (max-width: 720px) {
  .status-select,
  .search-input {
    width: 100%;
  }

  .toolbar-left {
    width: 100%;
  }
}
</style>
