<!--
  对话输入框组件:
  - 自适应高度的 textarea,回车发送、Shift+回车换行
  - 支持知识库多选(对齐后端 kb_ids)
  - 支持会话文件上传(合同等):附件按钮 + 文件 chips,上传解析后随对话请求携带
  - 流式生成中显示"停止生成"按钮,可中断 SSE
-->
<template>
  <div class="chat-composer">
    <!-- 知识库选择条 -->
    <div class="composer-bar">
      <div class="kb-picker">
        <Library :size="13" />
        <span class="kb-label">检索范围</span>
        <el-select
          v-model="selectedKbIds"
          multiple
          collapse-tags
          collapse-tags-tooltip
          placeholder="默认全部知识库"
          size="small"
          class="kb-select"
          :disabled="streaming"
        >
          <el-option
            v-for="kb in knowledgeBases"
            :key="kb.id"
            :label="kb.name"
            :value="String(kb.id)"
          />
        </el-select>
      </div>
      <div class="composer-hint">
        <kbd>Enter</kbd> 发送 · <kbd>Shift</kbd>+<kbd>Enter</kbd> 换行
      </div>
    </div>

    <!-- 已上传文件 chips -->
    <div
      v-if="files.length > 0"
      class="file-chips"
    >
      <div
        v-for="(item, idx) in files"
        :key="idx"
        class="file-chip"
        :class="`file-${item.status}`"
      >
        <FileText :size="13" />
        <span class="file-name">{{ item.file.name }}</span>
        <span class="file-badge">{{ fileTypeLabel(item.ref?.file_type ?? item.file.name) }}</span>
        <span
          v-if="item.status === 'uploading'"
          class="file-status file-status-uploading"
        >
          <Loader2
            :size="11"
            class="spin"
          />
          上传中…
        </span>
        <span
          v-else-if="item.status === 'parsing'"
          class="file-status file-status-uploading"
        >
          <Loader2
            :size="11"
            class="spin"
          />
          后台识别中…
        </span>
        <span
          v-else-if="item.status === 'error'"
          class="file-status file-status-error"
          :title="item.error"
        >失败</span>
        <button
          type="button"
          class="file-remove"
          :disabled="item.status === 'uploading' || item.status === 'parsing'"
          @click="removeFile(idx)"
        >
          <X :size="12" />
        </button>
      </div>
    </div>

    <!-- 输入区 -->
    <div class="composer-input">
      <textarea
        ref="textareaRef"
        v-model="text"
        class="composer-textarea"
        placeholder="输入法律问题,例如:劳动合同解除的法定情形有哪些?"
        rows="1"
        :disabled="streaming"
        @keydown="onKeydown"
        @input="autoResize"
      />
      <div class="composer-actions">
        <button
          v-if="streaming"
          type="button"
          class="stop-btn"
          @click="$emit('stop')"
        >
          <Square :size="13" />
          停止生成
        </button>
        <template v-else>
          <button
            type="button"
            class="attach-btn"
            title="上传合同文件(Word/PDF/图片/扫描件)"
            :disabled="anyUploading"
            @click="fileInputRef?.click()"
          >
            <Paperclip :size="15" />
          </button>
          <input
            ref="fileInputRef"
            type="file"
            accept=".docx,.pdf,.txt,.html,.jpg,.jpeg,.png,.bmp,.tiff,.tif,.webp"
            multiple
            class="file-input-hidden"
            @change="handleFilesChange"
          />
          <button
            type="button"
            class="send-btn"
            :disabled="!canSend || submitting"
            @click="submit"
          >
            <Loader2
              v-if="submitting"
              :size="14"
              class="spin"
            />
            <Send
              v-else
              :size="14"
            />
            {{ submitting ? '等待文件解析…' : '发送' }}
          </button>
        </template>
      </div>
    </div>

    <!-- 快捷问题建议 -->
    <div
      v-if="!streaming && text.trim() === '' && files.length === 0 && suggestions.length > 0"
      class="composer-suggestions"
    >
      <button
        v-for="(s, i) in suggestions"
        :key="i"
        type="button"
        class="suggestion-chip"
        @click="useSuggestion(s)"
      >
        <Sparkles :size="12" />
        {{ s }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { FileText, Library, Loader2, Paperclip, Send, Sparkles, Square, X } from 'lucide-vue-next'

import { getChatUploadStatus, uploadChatFile } from '@/api/agent'
import type { KnowledgeBase } from '@/types/kb'
import type { UploadedFileRef } from '@/types/conversation'

const props = defineProps<{
  // 是否正在流式生成。
  streaming: boolean
  // 可选知识库列表。
  knowledgeBases: KnowledgeBase[]
  // 快捷问题建议。
  suggestions?: string[]
}>()

const emit = defineEmits<{
  send: [payload: { text: string; kb_ids: string[]; uploaded_files: UploadedFileRef[] }]
  stop: []
}>()

interface UploadItem {
  ref: UploadedFileRef | null
  file: File
  status: 'uploading' | 'parsing' | 'ready' | 'error'
  error?: string
}

const text = ref('')
const selectedKbIds = ref<string[]>([])
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)
const files = ref<UploadItem[]>([])
// 发送前等待待解析文件完成时的等待态。
const submitting = ref(false)

// 默认快捷问题,父组件未传时使用。
const suggestions = computed(() => props.suggestions ?? [
  '劳动合同解除的法定情形有哪些?',
  '醉驾与酒驾的法律后果区别?',
  '民事诉讼时效一般是几年?',
  '合同违约金过高能否请求调整?',
])

const readyFiles = computed(() => files.value.filter((f) => f.status === 'ready'))
const anyUploading = computed(() =>
  files.value.some((f) => f.status === 'uploading' || f.status === 'parsing'),
)
// 允许在文件解析过程中发送:有待解析文件时按钮也可点,提交前会先等文件解析完成。
const canSend = computed(
  () => !props.streaming && (text.value.trim().length > 0 || files.value.length > 0),
)

function fileTypeLabel(fileOrName: string): string {
  const suffix = fileOrName.split('.').pop()?.toLowerCase() ?? ''
  const image = ['jpg', 'jpeg', 'png', 'bmp', 'tiff', 'tif', 'webp']
  if (image.includes(suffix)) return '图片'
  if (suffix === 'docx') return 'Word'
  if (suffix === 'pdf') return 'PDF'
  return suffix.toUpperCase() || '文件'
}

function handleFilesChange(event: Event) {
  const input = event.target as HTMLInputElement
  const selected = Array.from(input.files ?? [])
  input.value = ''
  for (const file of selected) {
    uploadOne(file)
  }
}

async function uploadOne(file: File) {
  // 后续异步上传和轮询会持续修改状态，必须使用响应式对象触发视图更新。
  const item = reactive<UploadItem>({ ref: null, file, status: 'uploading' })
  files.value.push(item)
  try {
    const ref = await uploadChatFile(file)
    item.ref = ref
    if (ref.parse_status === 'completed') {
      item.status = 'ready'
    } else if (ref.parse_status === 'pending' || ref.parse_status === 'parsing') {
      item.status = 'parsing'
      const parsed = await waitForParsedUpload(ref.upload_id)
      item.ref = parsed
      if (parsed.parse_status === 'completed') {
        item.status = 'ready'
      } else {
        item.status = 'error'
        item.error = parsed.error_message || '文件解析失败,请尝试更清晰的文档'
      }
    } else {
      item.status = 'error'
      item.error = ref.error_message || '文件解析失败,请尝试更清晰的文档'
    }
  } catch (err) {
    item.status = 'error'
    item.error = err instanceof Error ? err.message : '上传失败'
  }
}

async function waitForParsedUpload(uploadId: string, timeoutMs = 90000): Promise<UploadedFileRef> {
  const deadline = Date.now() + timeoutMs
  let latest: UploadedFileRef | null = null
  while (Date.now() <= deadline) {
    latest = await getChatUploadStatus(uploadId)
    if (latest.parse_status === 'completed' || latest.parse_status === 'failed') return latest
    await new Promise((resolve) => window.setTimeout(resolve, 1000))
  }
  throw new Error(latest?.error_message || '文件后台解析超时，请稍后重试')
}

function removeFile(idx: number) {
  files.value.splice(idx, 1)
}

// 等待所有待解析文件完成;超时后跳过未就绪文件,不阻塞发送。
async function waitForUploads(timeoutMs = 90000) {
  const deadline = Date.now() + timeoutMs
  while (files.value.some((f) => f.status === 'uploading' || f.status === 'parsing')) {
    if (Date.now() > deadline) break
    await new Promise((resolve) => window.setTimeout(resolve, 300))
  }
}

async function submit() {
  const trimmed = text.value.trim()
  if ((!trimmed && files.value.length === 0) || props.streaming || submitting.value) return

  // 有待解析文件时:先等它解析完成,再连同文字一起发送,确保上传的合同被本次审查包含。
  if (anyUploading.value) {
    submitting.value = true
    try {
      await waitForUploads()
    } finally {
      submitting.value = false
    }
  }

  const ready = readyFiles.value
  if (!trimmed && ready.length === 0) return // 没有文字且文件均未就绪(如解析失败),无可发送内容
  // 只传文件时,自动带默认审查意图,让 Router 命中合同审查。
  const query = trimmed || '请审查并分析这份合同'
  emit('send', {
    text: query,
    kb_ids: selectedKbIds.value,
    uploaded_files: ready.map((f) => f.ref!).filter(Boolean),
  })
  text.value = ''
  nextTick(autoResize)
}

function useSuggestion(s: string) {
  text.value = s
  nextTick(() => {
    autoResize()
    textareaRef.value?.focus()
  })
}

function onKeydown(e: KeyboardEvent) {
  // 回车发送,Shift+回车换行;中文输入法 composing 状态不触发。
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    submit()
  }
}

// 自适应高度,最大 160px。
function autoResize() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 160)}px`
}

// streaming 状态切换时,关闭后自动聚焦回输入框。
watch(
  () => props.streaming,
  (now) => {
    if (!now) nextTick(() => textareaRef.value?.focus())
  },
)

function setText(value: string) {
  text.value = value
  nextTick(() => {
    autoResize()
    textareaRef.value?.focus()
  })
}

defineExpose({
  focus: () => textareaRef.value?.focus(),
  setText,
})
</script>

<style scoped>
/* ChatGPT 风格输入框：浅色下纯白 + 16px 圆角 + 淡灰描边，hover/focus 变蓝。 */
.chat-composer {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px 20px 18px;
  background: transparent;
  border-top: 1px solid var(--law-border);
}

:global(html.dark) .chat-composer {
  background: var(--law-card);
  border-top: 1px solid var(--law-border);
  box-shadow: 0 -10px 30px rgb(0 0 0 / 22%);
}

.composer-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.kb-picker {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--law-muted);
  font-size: 12px;
  font-weight: 600;
}

.kb-picker :deep(svg) {
  color: var(--law-primary);
}

.kb-label {
  letter-spacing: 0.02em;
}

.kb-select {
  width: 240px;
}

.composer-hint {
  font-size: 11px;
  color: var(--law-muted-soft);
}

.composer-hint kbd {
  display: inline-block;
  padding: 1px 5px;
  margin: 0 1px;
  border: 1px solid var(--law-border);
  border-radius: 4px;
  background: var(--law-bg);
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10px;
  font-weight: 700;
  color: var(--law-muted);
}

:global(html.dark) .composer-hint kbd {
  background: rgb(255 255 255 / 6%);
}

/* ===== 文件 chips ===== */
.file-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.file-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 300px;
  padding: 5px 9px;
  border: 1px solid var(--law-border);
  border-radius: 9px;
  background: var(--law-card);
  font-size: 12px;
  color: var(--law-text);
}

:global(html.dark) .file-chip {
  background: var(--law-bg);
}

.file-chip :deep(svg) {
  color: var(--law-primary);
  flex-shrink: 0;
}

.file-chip.file-error {
  border-color: rgba(239, 68, 68, 0.4);
  background: rgba(239, 68, 68, 0.06);
}

.file-chip.file-error :deep(svg) {
  color: rgb(239 68 68);
}

.file-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-badge {
  padding: 1px 6px;
  border-radius: 5px;
  background: rgba(59, 130, 246, 0.10);
  color: var(--law-primary-strong);
  font-size: 10px;
  font-weight: 800;
  flex-shrink: 0;
}

.file-status {
  color: var(--law-muted);
  font-size: 11px;
  flex-shrink: 0;
}

.file-status-uploading {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--law-primary-strong);
  font-weight: 700;
}

.file-status-uploading .spin {
  animation: composer-spin 0.9s linear infinite;
}

@keyframes composer-spin {
  to {
    transform: rotate(360deg);
  }
}

.file-status-error {
  color: rgb(185 28 28);
}

:global(html.dark) .file-status-error {
  color: rgb(252 165 165);
}

.file-remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--law-muted);
  cursor: pointer;
  flex-shrink: 0;
}

.file-remove:hover:not(:disabled) {
  color: rgb(185 28 28);
}

.file-remove:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* ===== 输入区（ChatGPT 风格） ===== */
.composer-input {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid rgba(0, 0, 0, 0.08);
  border-radius: 16px;
  background: var(--law-card);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  transition: border-color 180ms ease, box-shadow 180ms ease;
}

.composer-input:hover {
  border-color: var(--law-primary);
}

.composer-input:focus-within {
  border-color: var(--law-primary);
  box-shadow: 0 0 0 4px var(--law-ring);
}

:global(html.dark) .composer-input {
  background: var(--law-bg);
  border-color: var(--law-border);
  box-shadow: 0 -2px 8px rgb(0 0 0 / 12%);
}

.composer-textarea {
  flex: 1;
  min-height: 28px;
  max-height: 160px;
  border: none;
  outline: none;
  background: transparent;
  resize: none;
  font-size: 14px;
  line-height: 1.6;
  color: var(--law-text);
  font-family: inherit;
}

.composer-textarea::placeholder {
  color: var(--law-placeholder);
}

.composer-textarea:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.composer-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.send-btn,
.stop-btn,
.attach-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 8px 16px;
  border: none;
  border-radius: 12px;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  transition: all 180ms ease;
}

.attach-btn {
  padding: 8px 10px;
  background: transparent;
  color: var(--law-muted);
}

.attach-btn:hover:not(:disabled) {
  background: rgba(59, 130, 246, 0.08);
  color: var(--law-primary);
  transform: translateY(-1px);
}

:global(html.dark) .attach-btn {
  background: rgb(37 99 235 / 8%);
  color: var(--law-primary-strong);
}

:global(html.dark) .attach-btn:hover:not(:disabled) {
  background: rgb(37 99 235 / 14%);
}

.attach-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.file-input-hidden {
  display: none;
}

.send-btn {
  color: #ffffff;
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
  color: #fff;
  box-shadow: 0 4px 12px rgb(37 99 235 / 24%);
}

.send-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 6px 18px rgb(37 99 235 / 32%);
}

.send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  box-shadow: none;
}

.stop-btn {
  background: rgba(239, 68, 68, 0.10);
  color: rgb(185 28 28);
  border: 1px solid rgba(239, 68, 68, 0.30);
}

.stop-btn:hover {
  background: rgba(239, 68, 68, 0.18);
}

:global(html.dark) .stop-btn {
  color: rgb(252 165 165);
}

.composer-suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.suggestion-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 11px;
  border: 1px solid var(--law-border);
  border-radius: 999px;
  background: var(--law-card);
  color: var(--law-text);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 160ms ease;
}

.suggestion-chip:hover {
  border-color: var(--law-primary);
  color: var(--law-primary);
  background: rgba(59, 130, 246, 0.06);
  transform: translateY(-1px);
}

.suggestion-chip :deep(svg) {
  color: rgb(245 158 11);
}

@media (max-width: 768px) {
  .composer-bar {
    flex-direction: column;
    align-items: flex-start;
  }

  .kb-select {
    width: 100%;
  }
}
</style>
