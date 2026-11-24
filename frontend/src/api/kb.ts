// 知识库与文档接口模块,对齐后端 /api/kb 与 /api/document 路由。
// 文档上传使用 multipart/form-data,通过 request 实例直接调用以保留 FormData 与 onUploadProgress。
import { httpDelete, httpGet, httpPost, httpPut, request } from './request'
import type { AxiosProgressEvent } from 'axios'

import type {
  CreateKBPayload,
  DocumentDetail,
  DocumentMarkdown,
  DocumentUploadResult,
  KBStatus,
  KBType,
  KnowledgeBase,
  PaginatedDocuments,
  ParseStatus,
  UpdateKBPayload,
} from '@/types/kb'

// 知识库列表查询参数。
export interface KBListQuery {
  kb_type?: KBType
  status?: KBStatus
}

// 获取当前用户的知识库列表。
export const listKnowledgeBases = (params?: KBListQuery) =>
  httpGet<KnowledgeBase[]>('/kb', { params })

// 创建知识库。
export const createKnowledgeBase = (payload: CreateKBPayload) =>
  httpPost<KnowledgeBase>('/kb', payload)

// 获取知识库详情。
export const getKnowledgeBase = (id: number) => httpGet<KnowledgeBase>(`/kb/${id}`)

// 更新知识库配置。
export const updateKnowledgeBase = (id: number, payload: UpdateKBPayload) =>
  httpPut<KnowledgeBase>(`/kb/${id}`, payload)

// 删除知识库(后端会写入 OSS 清理任务,不直接物理删除文件)。
export const deleteKnowledgeBase = (id: number) => httpDelete<null>(`/kb/${id}`)

// 文档列表查询参数。
export interface DocumentListQuery {
  kb_id: number
  parse_status?: ParseStatus
  page?: number
  page_size?: number
}

// 分页获取知识库下的文档列表。
export const listDocuments = (params: DocumentListQuery) =>
  httpGet<PaginatedDocuments>('/document', { params })

// 获取文档详情。
export const getDocument = (documentId: number) =>
  httpGet<DocumentDetail>(`/document/${documentId}`)

// 获取文档解析后的 Markdown 原文。
export const getDocumentMarkdown = (documentId: number) =>
  httpGet<DocumentMarkdown>(`/document/${documentId}/markdown`)

// 删除文档及其 Chunk(后端会 best-effort 清理 OSS 与 Milvus 向量)。
export const deleteDocument = (documentId: number) => httpDelete<null>(`/document/${documentId}`)

// 上传文档并入队解析任务,使用 FormData 以匹配后端 UploadFile 表单。
export const uploadDocument = (
  kbId: number,
  file: File,
  onProgress?: (percent: number) => void,
) => {
  const form = new FormData()
  form.append('kb_id', String(kbId))
  form.append('file', file)
  return request
    .post<{ code: number; message: string; data: DocumentUploadResult }>('/document/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      // 大型法律汇编 PDF 上传到本地后端再转存 OSS，不能沿用全局 10 秒超时。
      timeout: 10 * 60 * 1000,
      onUploadProgress: (event: AxiosProgressEvent) => {
        if (!onProgress || !event.total) return
        onProgress(Math.round((event.loaded / event.total) * 100))
      },
    })
    .then((response) => response.data.data)
}

// 重置文档状态并重新入队解析(parsing 状态会被后端拒绝并返回 409)。
export const reparseDocument = (documentId: number) =>
  httpPost<null>(`/document/${documentId}/reparse`)
