// 会话接口模块,对齐后端 /api/conversation 路由:
// - 列表、详情、消息分页、软删除、消息反馈
// 复用统一 request 实例,自动注入 Bearer Token 与 401 跳转。
import { httpDelete, httpGet, httpPost } from './request'

import type {
  Conversation,
  ConversationDetail,
  ConversationMessage,
  MessageFeedback,
  Paginated,
} from '@/types/conversation'

// 列表查询参数。
export interface ConversationListQuery {
  page?: number
  page_size?: number
}

// 列表分页响应。
interface ConversationListData {
  items: Conversation[]
  total: number
}

// 获取当前用户的活跃会话列表。
export const listConversations = (params?: ConversationListQuery) =>
  httpGet<ConversationListData>('/conversation/list', { params })

// 获取会话详情(含最近 50 条消息)。
export const getConversation = (id: number | string) =>
  httpGet<ConversationDetail>(`/conversation/${id}`)

// 分页获取会话消息历史。
export const listMessages = (
  id: number | string,
  params?: ConversationListQuery,
) => httpGet<Paginated<ConversationMessage>>(`/conversation/${id}/messages`, { params })

// 软删除会话(后端置为 archived)。
export const deleteConversation = (id: number | string) =>
  httpDelete<{ status: string }>(`/conversation/${id}`)

// 消息反馈请求体。
interface FeedbackPayload {
  feedback: Exclude<MessageFeedback, null>
  comment?: string
}

// 给 assistant 消息点赞或点踩。
export const feedbackMessage = (
  conversationId: number | string,
  messageId: number | string,
  feedback: Exclude<MessageFeedback, null>,
  comment?: string,
) =>
  httpPost<{ feedback: string }>(
    `/conversation/${conversationId}/message/${messageId}/feedback`,
    { feedback, comment } satisfies FeedbackPayload,
  )
