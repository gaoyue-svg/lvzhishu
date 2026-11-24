// Agent SSE 流式对话接口模块,对齐后端 /api/agent/chat。
// 使用 fetch + ReadableStream 解析 text/event-stream,因为 axios 不支持流式读取。
// 每条 SSE 帧格式为 "data: {json}\n\n",后端把事件名编码进 JSON 的 event 字段。
import { getToken } from '@/utils/auth-token'

import type { AgentSseEvent, UploadedFileRef } from '@/types/conversation'

// 对话请求体,对齐 agent_service.routers.agent.AgentChatRequest。
export interface AgentChatPayload {
  query: string
  conversation_id?: string
  kb_ids?: string[]
  // 会话已上传文件引用(合同分析):后端解析 clauses 注入 v2 预置工作流。
  uploaded_files?: UploadedFileRef[]
}

// SSE 事件回调:每解析出一条事件就触发一次。
export type SseEventHandler = (event: AgentSseEvent) => void

// SSE 错误回调:网络错误或解析失败时触发。
export type SseErrorHandler = (error: Error) => void

// SSE 完成回调:流正常结束或被中止时触发。
export type SseDoneHandler = () => void

// 流式对话参数。
export interface StreamChatOptions {
  payload: AgentChatPayload
  onEvent: SseEventHandler
  onError?: SseErrorHandler
  onDone?: SseDoneHandler
  // AbortSignal,用于前端主动停止生成。
  signal?: AbortSignal
}

// 把 SSE 原始文本缓冲区切成完整帧,返回剩余未完成的片段。
// 帧分隔符为 "\n\n",每帧形如 "data: {...}"。
function* parseSseFrames(buffer: string): Generator<string, string, undefined> {
  let remaining = buffer
  while (true) {
    const idx = remaining.indexOf('\n\n')
    if (idx === -1) break
    const frame = remaining.slice(0, idx)
    remaining = remaining.slice(idx + 2)
    if (frame.trim()) yield frame
  }
  return remaining
}

// 从单帧中提取 data: 后的 JSON 并解析为事件对象。
function parseFrame(frame: string): AgentSseEvent | null {
  // SSE 帧可能由多行组成,只取 data: 开头的行拼接。
  const dataLines = frame
    .split('\n')
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trim())
  if (dataLines.length === 0) return null
  const jsonText = dataLines.join('\n')
  try {
    return JSON.parse(jsonText) as AgentSseEvent
  } catch {
    // 后端始终输出合法 JSON,解析失败时丢弃,避免整条流中断。
    return null
  }
}

// 发起 SSE 流式对话,返回一个可主动取消的控制器。
// 调用方拿到 controller 后,可通过 controller.abort() 停止生成。
export async function streamAgentChat(options: StreamChatOptions): Promise<void> {
  const { payload, onEvent, onError, onDone, signal } = options
  const token = getToken()
  let response: Response
  try {
    response = await fetch('/api/agent/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        // 后端 get_current_user 依赖 Bearer Token。
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(payload),
      signal,
    })
  } catch (rawError) {
    // AbortError 由调用方通过 signal 处理,这里只兜底网络错误。
    if (rawError instanceof DOMException && rawError.name === 'AbortError') {
      onDone?.()
      return
    }
    const error = rawError instanceof Error ? rawError : new Error('网络异常')
    onError?.(error)
    return
  }

  if (!response.ok || !response.body) {
    // 后端鉴权失败会返回 401,统一拦截器已处理跳转;此处兜底其他错误。
    let message = `请求失败 (${response.status})`
    try {
      const data = await response.json()
      if (data?.message) message = data.message
    } catch {
      // 非 JSON 响应,沿用默认 message。
    }
    onError?.(new Error(message))
    return
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const gen = parseSseFrames(buffer)
      let rest = ''
      while (true) {
        const step = gen.next()
        if (step.done) {
          rest = step.value ?? ''
          break
        }
        const event = parseFrame(step.value)
        if (event) onEvent(event)
      }
      buffer = rest
    }
    // 处理流末尾可能残留的最后一帧。
    if (buffer.trim()) {
      const event = parseFrame(buffer)
      if (event) onEvent(event)
    }
  } catch (rawError) {
    if (rawError instanceof DOMException && rawError.name === 'AbortError') {
      onDone?.()
      return
    }
    const error = rawError instanceof Error ? rawError : new Error('流式读取失败')
    onError?.(error)
    return
  }
  onDone?.()
}

// 上传会话文件(合同等),后端解析为 Markdown 后返回文件引用,供对话请求携带。
export async function uploadChatFile(file: File): Promise<UploadedFileRef> {
  const token = getToken()
  const form = new FormData()
  form.append('file', file)
  const response = await fetch('/api/agent/upload', {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  })
  if (!response.ok) {
    let message = `上传失败 (${response.status})`
    try {
      const data = await response.json()
      if (data?.message) message = data.message
    } catch {
      // 非 JSON 响应,沿用默认 message。
    }
    throw new Error(message)
  }
  const payload = (await response.json()) as { code: number; message: string; data: UploadedFileRef | null }
  if (payload.code !== 0 || !payload.data) {
    throw new Error(payload.message || '上传失败')
  }
  return payload.data
}

// 查询会话附件的后台 OCR/解析状态。
export async function getChatUploadStatus(uploadId: string): Promise<UploadedFileRef> {
  const token = getToken()
  const response = await fetch(`/api/agent/upload/${encodeURIComponent(uploadId)}`, {
    method: 'GET',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!response.ok) {
    throw new Error(`查询文件解析状态失败 (${response.status})`)
  }
  const payload = (await response.json()) as { code: number; message: string; data: UploadedFileRef | null }
  if (payload.code !== 0 || !payload.data) {
    throw new Error(payload.message || '查询文件解析状态失败')
  }
  return payload.data
}

// 下载合同审查报告(.docx),供"导出报告"按钮调用。
export async function downloadContractReport(uploadId: string): Promise<Blob> {
  const token = getToken()
  const response = await fetch(`/api/agent/upload/${uploadId}/report`, {
    method: 'GET',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!response.ok) {
    let message = '导出失败'
    try {
      const data = await response.json()
      if (data?.message) message = data.message
    } catch {
      // 非 JSON 响应,沿用默认 message。
    }
    throw new Error(message)
  }
  return response.blob()
}

// 将一条已保存的 Assistant 回答导出为 Word 文书。
export async function exportAgentDocument(
  messageId: string,
): Promise<{ blob: Blob; filename: string }> {
  const token = getToken()
  const response = await fetch(`/api/agent/message/${encodeURIComponent(messageId)}/export`, {
    method: 'GET',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!response.ok) {
    let message = '文书导出失败'
    try {
      const data = await response.json()
      if (data?.message) message = data.message
    } catch {
      // 非 JSON 响应,沿用默认 message。
    }
    throw new Error(message)
  }
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  const filename = encodedName ? decodeURIComponent(encodedName) : `LawAgent-${messageId}.docx`
  return { blob: await response.blob(), filename }
}
