// 知识库与文档相关类型定义,对齐后端 schemas/kb.py 与 schemas/document.py 的响应契约。
// 状态枚举取自后端 worker 实际写入值,保证前端类型与运行时数据一致。

// 知识库类型:法律法规 / 案例判例 / 司法解释 / 合同范本 / 企业制度。
export type KBType = 'law' | 'case' | 'judicial' | 'contract' | 'enterprise'

// 知识库启停状态。
export type KBStatus = 'enabled' | 'disabled'

// 文档解析状态:待解析 / 解析中 / 解析完成 / 解析失败。
export type ParseStatus = 'pending' | 'parsing' | 'completed' | 'failed'

// 文档向量化状态:待处理 / 处理中 / 完成 / 部分失败 / 失败。
export type EmbeddingStatus = 'pending' | 'processing' | 'completed' | 'partial_failed' | 'failed'

// 知识库响应,对应后端 KnowledgeBaseResponse。
export interface KnowledgeBase {
  id: number
  user_id: number
  name: string
  description: string | null
  kb_type: KBType
  embedding_model: string | null
  chunk_size: number
  chunk_overlap: number
  doc_count: number
  chunk_count: number
  total_size: number
  status: KBStatus
  created_at: string
  updated_at: string
}

// 创建知识库请求体,对应后端 CreateKBRequest。
export interface CreateKBPayload {
  name: string
  description?: string | null
  kb_type: KBType
  embedding_model: string
  chunk_size: number
  chunk_overlap: number
}

// 更新知识库请求体,对应后端 UpdateKBRequest,所有字段可选。
export interface UpdateKBPayload {
  name?: string
  description?: string | null
  chunk_size?: number
  chunk_overlap?: number
  status?: KBStatus
}

// 文档详情响应,对应后端 DocumentDetailResponse。
export interface DocumentDetail {
  id: number
  kb_id: number
  filename: string
  file_type: string
  file_size: number
  oss_url: string
  parse_status: ParseStatus
  embedding_status: EmbeddingStatus
  embedding_count: number
  embedding_failed_count: number
  error_message: string | null
  chunk_count: number
  version: string | null
  effective_date: number | null
  is_latest: boolean
  superseded_by_document_id: number | null
  created_at: string
}

// 分页文档列表响应,对应后端 PaginatedDocumentResponse。
export interface PaginatedDocuments {
  items: DocumentDetail[]
  total: number
  page: number
  page_size: number
}

// 文档上传响应,对应后端 DocumentUploadResponse。
export interface DocumentUploadResult {
  document_id: number
  filename: string
  file_size: number
  oss_url: string
  parse_status: ParseStatus
}

// 文档 Markdown 原文响应,对应后端 DocumentMarkdownResponse。
export interface DocumentMarkdown {
  document_id: number
  filename: string
  raw_markdown: string | null
}
