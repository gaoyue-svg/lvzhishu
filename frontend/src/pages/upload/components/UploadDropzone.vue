<!--
  本文件是上传中心的拖拽上传组件(简化版):
  - 支持拖拽多文件与点击选择
  - 顺序上传(一个完成再上传下一个),实时进度条
  - 文件直传后端 /api/document/upload,由后端写入阿里云 OSS 并自动入队解析与 embedding
-->
<template>
  <section class="dropzone-panel">
    <!-- 拖拽区:HTML5 drag-and-drop + 隐藏 file input -->
    <div
      class="dropzone"
      :class="{ 'is-dragover': isDragover, 'is-disabled': !kb }"
      role="button"
      tabindex="0"
      @click="openFilePicker"
      @keydown.enter.prevent="openFilePicker"
      @keydown.space.prevent="openFilePicker"
      @dragenter.prevent="onDragEnter"
      @dragover.prevent
      @dragleave.prevent="onDragLeave"
      @drop.prevent="onDrop"
    >
      <input
        ref="fileInputRef"
        type="file"
        multiple
        :accept="ACCEPTED_FILE_TYPES"
        class="file-input"
        @change="onFileInputChange"
      >
      <div class="dropzone-inner">
        <div class="dropzone-icon">
          <UploadCloud :size="38" />
        </div>
        <strong v-if="kb">
          拖拽文件到此处,或<span class="dropzone-link">点击选择</span>
        </strong>
        <strong
          v-else
          class="dropzone-warn"
        >
          <AlertCircle :size="14" />
          请先选择目标知识库
        </strong>
        <small class="dropzone-hint">支持 PDF、DOCX、TXT、HTML,上传后自动解析与向量化</small>
      </div>
    </div>

    <!-- 队列列表 -->
    <div
      v-if="tasks.length"
      class="queue-list"
    >
      <div
        v-for="task in tasks"
        :key="task.id"
        class="queue-item"
        :class="task.status"
      >
        <span
          class="file-icon"
          :class="task.ext"
        >
          <FileText :size="16" />
        </span>
        <div class="item-body">
          <div class="item-head">
            <strong>{{ task.file.name }}</strong>
            <span class="item-size">{{ formatFileSize(task.file.size) }}</span>
          </div>
          <div class="item-status">
            <span
              v-if="task.status === 'pending'"
              class="status-text pending"
            >
              <i class="status-dot" /> 等待中
            </span>
            <span
              v-else-if="task.status === 'uploading'"
              class="status-text uploading"
            >
              <i class="status-dot" /> 上传中 {{ task.progress }}%
            </span>
            <span
              v-else-if="task.status === 'success'"
              class="status-text success"
            >
              <i class="status-dot" /> 已上传,自动入队解析
            </span>
            <span
              v-else
              class="status-text error"
              :title="task.error"
            >
              <i class="status-dot" /> 失败:{{ task.error }}
            </span>
            <div
              v-if="task.status === 'uploading'"
              class="progress-track"
            >
              <div
                class="progress-fill"
                :style="{ width: task.progress + '%' }"
              />
            </div>
          </div>
        </div>
        <div class="item-actions">
          <el-button
            v-if="task.status === 'error'"
            link
            type="primary"
            :icon="RotateCw"
            @click="retryTask(task)"
          >
            重试
          </el-button>
          <el-button
            v-if="task.status !== 'uploading'"
            link
            type="danger"
            :icon="X"
            @click="removeTask(task.id)"
          />
        </div>
      </div>
    </div>

    <!-- 空态 -->
    <div
      v-else
      class="queue-empty"
    >
      <FileCheck2 :size="22" />
      <span>暂无上传任务,拖拽文件即可开始</span>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  AlertCircle,
  FileCheck2,
  FileText,
  RotateCw,
  UploadCloud,
  X,
} from 'lucide-vue-next'

import { uploadDocument } from '@/api/kb'
import { ACCEPTED_FILE_TYPES } from '@/pages/knowledge/kb-meta'
import { formatFileSize } from '@/utils/format'
import type { KnowledgeBase } from '@/types/kb'

const props = defineProps<{
  // 当前选中的目标知识库,未选时禁用上传。
  kb: KnowledgeBase | null
}>()

const fileInputRef = ref<HTMLInputElement>()

// 单个上传任务的状态机。
interface UploadTask {
  id: string
  file: File
  ext: string
  status: 'pending' | 'uploading' | 'success' | 'error'
  progress: number
  error?: string
}

const tasks = ref<UploadTask[]>([])
const isDragover = ref(false)
// dragleave 计数:HTML5 拖拽事件在子元素间会触发 leave,需用计数避免抖动。
const dragCounter = ref(0)
// 标记是否正在上传,用于顺序调度。
const uploading = ref(false)
const MAX_KNOWLEDGE_FILE_BYTES = 200 * 1024 * 1024

function openFilePicker() {
  fileInputRef.value?.click()
}

function onDragEnter() {
  if (!props.kb) return
  dragCounter.value++
  isDragover.value = true
}

function onDragLeave() {
  dragCounter.value = Math.max(0, dragCounter.value - 1)
  if (dragCounter.value === 0) isDragover.value = false
}

function onDrop(event: DragEvent) {
  isDragover.value = false
  dragCounter.value = 0
  if (!props.kb) {
    ElMessage.warning('请先选择目标知识库')
    return
  }
  const files = Array.from(event.dataTransfer?.files ?? [])
  if (files.length === 0) return
  addFiles(files)
}

function onFileInputChange(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = '' // 清空 input,便于重复选择同一文件
  if (files.length === 0) return
  addFiles(files)
}

// 批量加入文件:校验扩展名,合法的入队并触发顺序上传。
function addFiles(files: File[]) {
  if (!props.kb) {
    ElMessage.warning('请先选择目标知识库')
    return
  }
  const accepted: UploadTask[] = []
  for (const file of files) {
    const ext = file.name.split('.').pop()?.toLowerCase() ?? ''
    if (!['pdf', 'docx', 'txt', 'html'].includes(ext)) {
      ElMessage.error(`「${file.name}」格式不支持,仅支持 PDF / DOCX / TXT / HTML`)
      continue
    }
    if (file.size > MAX_KNOWLEDGE_FILE_BYTES) {
      ElMessage.error(`「${file.name}」超过 200 MB 单文件上限`)
      continue
    }
    accepted.push({
      id: `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2, 8)}`,
      file,
      ext,
      status: 'pending',
      progress: 0,
    })
  }
  if (accepted.length === 0) return
  tasks.value.push(...accepted)
  ElMessage.success(`已加入 ${accepted.length} 个文件,自动开始上传`)
  scheduleUpload()
}

// 顺序上传:没有任务在传时,取第一个 pending 开始上传。
async function scheduleUpload() {
  if (uploading.value) return
  if (!props.kb) return
  const pending = tasks.value.find((t) => t.status === 'pending')
  if (!pending) return
  uploading.value = true
  await runUpload(pending)
  uploading.value = false
  // 当前任务结束后继续调度下一个 pending。
  scheduleUpload()
}

// 执行单个任务的上传:调用后端 /api/document/upload,后端写入 OSS 并入队解析与 embedding。
async function runUpload(task: UploadTask) {
  if (!props.kb) return
  task.status = 'uploading'
  task.progress = 0
  task.error = undefined
  try {
    await uploadDocument(props.kb.id, task.file, (percent) => {
      task.progress = percent
    })
    task.status = 'success'
    task.progress = 100
  } catch (error) {
    task.status = 'error'
    task.error = error instanceof Error ? error.message : '未知错误'
  }
}

function retryTask(task: UploadTask) {
  if (task.status !== 'error') return
  task.status = 'pending'
  task.progress = 0
  task.error = undefined
  scheduleUpload()
}

function removeTask(id: string) {
  const index = tasks.value.findIndex((t) => t.id === id)
  if (index >= 0) tasks.value.splice(index, 1)
}
</script>

<style scoped>
.dropzone-panel {
  display: grid;
  gap: 16px;
  padding: 20px;
  border: 1px solid var(--law-border);
  border-radius: 18px;
  background: var(--law-card);
  box-shadow: var(--law-shadow);
}

/* Dropzone 主体 */
.dropzone {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 240px;
  padding: 32px 24px;
  border: 2px dashed var(--law-border);
  border-radius: 16px;
  background:
    radial-gradient(circle at 18% 24%, rgb(37 99 235 / 8%), transparent 42%),
    radial-gradient(circle at 82% 78%, rgb(124 58 237 / 6%), transparent 42%),
    var(--law-card);
  cursor: pointer;
  transition:
    border-color 200ms ease,
    background 200ms ease,
    box-shadow 200ms ease;
  outline: none;
}

:global(html.dark) .dropzone {
  background:
    radial-gradient(circle at 18% 24%, rgb(37 99 235 / 14%), transparent 42%),
    radial-gradient(circle at 82% 78%, rgb(124 58 237 / 12%), transparent 42%),
    var(--law-card);
}

.dropzone:hover {
  border-color: rgb(37 99 235 / 50%);
}

.dropzone.is-dragover {
  border-color: var(--law-primary);
  background:
    radial-gradient(circle at 18% 24%, rgb(37 99 235 / 18%), transparent 52%),
    radial-gradient(circle at 82% 78%, rgb(124 58 237 / 14%), transparent 52%),
    var(--law-card);
  box-shadow: 0 0 0 6px rgb(37 99 235 / 10%);
}

.dropzone.is-disabled {
  cursor: not-allowed;
  opacity: 0.72;
}

.dropzone.is-disabled:hover {
  border-color: var(--law-border);
}

.file-input {
  position: absolute;
  width: 0;
  height: 0;
  opacity: 0;
  pointer-events: none;
}

.dropzone-inner {
  display: grid;
  justify-items: center;
  gap: 12px;
  text-align: center;
}

.dropzone-icon {
  width: 72px;
  height: 72px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 22px;
  color: #ffffff;
  background: linear-gradient(135deg, #2563eb 0%, #7c3aed 100%);
  box-shadow:
    0 18px 36px rgb(37 99 235 / 28%),
    inset 0 1px 0 rgb(255 255 255 / 30%);
}

.dropzone-inner strong {
  font-size: 15px;
  font-weight: 700;
  color: var(--law-text);
}

.dropzone-link {
  color: var(--law-primary);
  font-weight: 700;
}

.dropzone-warn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #b45309;
}

.dropzone-hint {
  color: var(--law-muted);
  font-size: 12px;
}

/* 队列列表 */
.queue-list {
  display: grid;
  gap: 8px;
}

.queue-item {
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--law-border);
  border-radius: 12px;
  background: var(--law-card);
}

.queue-item.success {
  border-color: rgb(22 163 74 / 28%);
  background: rgb(22 163 74 / 4%);
}

.queue-item.error {
  border-color: rgb(239 68 68 / 28%);
  background: rgb(239 68 68 / 4%);
}

.queue-item.uploading {
  border-color: rgb(37 99 235 / 28%);
  background: rgb(37 99 235 / 4%);
}

.file-icon {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
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

.item-body {
  min-width: 0;
  display: grid;
  gap: 6px;
}

.item-head {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.item-head strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  font-weight: 600;
  color: var(--law-text);
}

.item-size {
  flex-shrink: 0;
  color: var(--law-muted);
  font-size: 11px;
}

.item-status {
  display: grid;
  gap: 6px;
}

.status-text {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 999px;
}

.status-text.pending {
  color: var(--law-muted);
}

.status-text.pending .status-dot {
  background: #94a3b8;
}

.status-text.uploading {
  color: var(--law-primary);
}

.status-text.uploading .status-dot {
  background: var(--law-primary);
}

.status-text.success {
  color: #15803d;
}

.status-text.success .status-dot {
  background: #22c55e;
}

.status-text.error {
  color: #b91c1c;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-text.error .status-dot {
  background: #ef4444;
}

.progress-track {
  width: 100%;
  height: 4px;
  border-radius: 999px;
  background: rgb(37 99 235 / 14%);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #2563eb 0%, #7c3aed 100%);
  transition: width 200ms ease;
}

.item-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.queue-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 18px;
  color: var(--law-muted);
  font-size: 13px;
  border: 1px dashed var(--law-border);
  border-radius: 12px;
}

@media (max-width: 768px) {
  .dropzone {
    min-height: 200px;
    padding: 24px 18px;
  }

  .dropzone-icon {
    width: 60px;
    height: 60px;
    border-radius: 18px;
  }

  .queue-item {
    grid-template-columns: 32px minmax(0, 1fr);
  }

  .item-actions {
    grid-column: 1 / -1;
    justify-content: flex-end;
  }
}
</style>
