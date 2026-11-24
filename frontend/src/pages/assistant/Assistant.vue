<!--
  AI 智能问答主页面:
  - 左侧会话侧边栏 + 右侧对话主区(消息流 + 输入框)
  - 通过 SSE 流式调用 /api/agent/chat,实时展示节点进度、token、引用
  - 支持新建/切换/删除会话,会话切换时拉取历史消息
  - 流式生成可中断,引用编号可点击滚动到对应卡片
-->
<template>
  <div
    class="assistant-page"
    :class="{ 'sidebar-collapsed': sidebarCollapsed }"
  >
    <AssistantSidebar
      :conversations="conversations"
      :active-id="activeConversationId"
      :loading="convLoading"
      :collapsed="sidebarCollapsed"
      @new="startNewConversation"
      @select="selectConversation"
      @delete="handleDelete"
      @toggle-collapse="sidebarCollapsed = true"
    />

    <!-- 侧边栏收起时的悬浮展开按钮 -->
    <button
      v-if="sidebarCollapsed"
      type="button"
      class="sidebar-expand-btn"
      title="展开会话侧栏"
      @click="sidebarCollapsed = false"
    >
      <PanelLeft :size="18" />
    </button>

    <main class="assistant-main">
      <!-- 顶部条:仅在已有会话时显示标题 + Router 决策摘要 -->
      <header
        v-if="activeConversationId"
        class="chat-header"
      >
        <div class="header-left">
          <h1 class="header-title">{{ headerTitle }}</h1>
          <div
            v-if="routerDecision"
            class="router-chips"
          >
            <span class="chip chip-agent">
              <component
                :is="agentIcon"
                :size="12"
              />
              {{ agentLabel }}
            </span>
            <span class="chip chip-risk">
              <ShieldAlert :size="12" />
              {{ riskLabel }}
            </span>
            <span
              v-if="routerDecision.need_retrieval"
              class="chip chip-retr"
            >
              <Search :size="12" />
              需检索
            </span>
            <span class="chip chip-conf">
              置信度 {{ Math.round(routerDecision.confidence * 100) }}%
            </span>
          </div>
        </div>
        <div class="header-right">
          <el-tooltip
            content="刷新会话列表"
            placement="bottom"
          >
            <button
              type="button"
              class="icon-btn"
              :disabled="convLoading"
              @click="loadConversations"
            >
              <RefreshCw :size="15" />
            </button>
          </el-tooltip>
        </div>
      </header>

      <!-- 消息流 -->
      <div
        ref="scrollRef"
        class="chat-stream"
        @scroll="handleScroll"
      >
        <!-- 空态欢迎屏 -->
        <div
          v-if="messages.length === 0 && !streaming"
          class="welcome-screen"
        >
          <div class="welcome-mark">
            <img
              :src="brandLogo"
              alt="律智枢 天秤与法槌"
              class="welcome-logo"
            />
          </div>
          <h2 class="welcome-title">法律智能问答</h2>
          <p class="welcome-sub">
            基于 RAG 检索增强与多 Agent 编排,覆盖法律咨询、法条定位、合同审查、案例分析场景。
          </p>
          <div class="welcome-grid-wrap">
            <div class="welcome-grid">
              <button
                v-for="(s, i) in currentSuggestions"
                :key="i"
                type="button"
                class="welcome-card"
                @click="quickSend(s.query, s.kb_ids)"
              >
                <component
                  :is="s.icon"
                  :size="18"
                  class="card-icon"
                />
                <div class="card-body">
                  <span class="card-title">{{ s.title }}</span>
                  <span class="card-desc">{{ s.query }}</span>
                </div>
                <ArrowRight :size="14" class="card-arrow" />
              </button>
            </div>
            <!-- 问题组切换 -->
            <div
              v-if="suggestionGroups.length > 1"
              class="suggestion-switch"
            >
              <button
                type="button"
                class="switch-arrow"
                :disabled="suggestionGroupIndex === 0"
                @click="suggestionGroupIndex--"
              >
                <ChevronLeft :size="16" />
              </button>
              <div class="switch-dots">
                <span
                  v-for="(_, idx) in suggestionGroups"
                  :key="idx"
                  class="switch-dot"
                  :class="{ active: idx === suggestionGroupIndex }"
                  @click="suggestionGroupIndex = idx"
                />
              </div>
              <button
                type="button"
                class="switch-arrow"
                :disabled="suggestionGroupIndex === suggestionGroups.length - 1"
                @click="suggestionGroupIndex++"
              >
                <ChevronRight :size="16" />
              </button>
            </div>
          </div>

          <!-- 空态输入框 -->
          <ChatComposer
            v-if="messages.length === 0 && !streaming"
            ref="composerRef"
            :streaming="streaming"
            :knowledge-bases="knowledgeBases"
            @send="handleSend"
            @stop="stopStreaming"
          />
        </div>

        <!-- 消息列表 -->
        <template v-else>
          <div class="stream-inner">
            <ChatMessage
              v-for="(msg, idx) in messages"
              :key="msg.id || `temp-${idx}`"
              :message="msg"
              :streaming="streaming && idx === messages.length - 1 && msg.role === 'assistant'"
              :finished-nodes="idx === messages.length - 1 ? finishedNodes : new Set()"
              :current-node="idx === messages.length - 1 ? currentNode : null"
              :chunk-count="idx === messages.length - 1 ? chunkCount : null"
              :tool-count="idx === messages.length - 1 ? toolCount : null"
              :show-timeline="idx === messages.length - 1 && streaming"
              :timeline-mode="idx === messages.length - 1 ? timelineMode : null"
              :agent-steps="idx === messages.length - 1 ? agentSteps : []"
              :current-agent="idx === messages.length - 1 ? currentAgent : null"
              :finished-agents="idx === messages.length - 1 ? finishedAgents : new Set()"
              :failed-agents="idx === messages.length - 1 ? failedAgents : new Set()"
              @feedback="(fb) => handleFeedback(msg, fb)"
              @trace="handleTrace"
              @copy="handleCopy"
            />
          </div>
        </template>
      </div>

      <!-- 输入框(有消息时显示在底部) -->
      <ChatComposer
        v-if="messages.length > 0 || streaming"
        ref="composerRef"
        :streaming="streaming"
        :knowledge-bases="knowledgeBases"
        @send="handleSend"
        @stop="stopStreaming"
      />
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ArrowRight,
  BriefcaseBusiness,
  ChevronLeft,
  ChevronRight,
  FileText,
  FileSearch,
  Gavel,
  Hammer,
  PanelLeft,
  RefreshCw,
  Scale,
  Search,
  ShieldAlert,
  Users,
} from 'lucide-vue-next'

import brandLogo from '@/assets/brand/lawagent-balance-gavel-v3.png'

import AssistantSidebar from './components/AssistantSidebar.vue'
import ChatComposer from './components/ChatComposer.vue'
import ChatMessage from './components/ChatMessage.vue'
import { listConversations, getConversation, deleteConversation, feedbackMessage } from '@/api/conversation'
import { streamAgentChat } from '@/api/agent'
import { listKnowledgeBases } from '@/api/kb'
import type {
  AgentType,
  Citation,
  Conversation,
  ConversationMessage,
  ContractAnalysisResult,
  MessageFeedback,
  RouterDecision,
  UploadedFileRef,
} from '@/types/conversation'
import type { KnowledgeBase } from '@/types/kb'

const route = useRoute()

// ===== 侧边栏折叠状态 =====
const sidebarCollapsed = ref(false)

// ===== 会话列表状态 =====
const conversations = ref<Conversation[]>([])
const activeConversationId = ref<string | number | null>(null)
const convLoading = ref(false)

// ===== 消息流状态 =====
const messages = ref<ConversationMessage[]>([])
const streaming = ref(false)

// ===== SSE 流式过程中的临时状态(绑定到最后一条 assistant 消息)=====
const finishedNodes = ref<Set<string>>(new Set())
const currentNode = ref<string | null>(null)
const chunkCount = ref<number | null>(null)
const toolCount = ref<number | null>(null)
const routerDecision = ref<RouterDecision | null>(null)

// ===== v2 多 Agent 步骤进度(agent_start/agent_end 驱动)=====
interface AgentPlanStep {
  step_id: string
  agent: string
  goal: string
}
const agentSteps = ref<AgentPlanStep[]>([])
const currentAgent = ref<string | null>(null)
const finishedAgents = ref<Set<string>>(new Set())
const failedAgents = ref<Set<string>>(new Set())
// 时间线模式:node=单 Agent 节点级(意图/检索/...),agent=Supervisor/v2 的 Agent 级。
// Supervisor 只发 agent_start/agent_end、不发 node_* 事件,需用 Agent 时间线驱动进度。
const timelineMode = ref<'node' | 'agent' | null>(null)

// ===== 知识库列表(供输入框选择)=====
const knowledgeBases = ref<KnowledgeBase[]>([])

// ===== DOM 引用 =====
const scrollRef = ref<HTMLDivElement | null>(null)
const composerRef = ref<InstanceType<typeof ChatComposer> | null>(null)

// 用于中断 SSE 流的 AbortController。
let abortController: AbortController | null = null
// 用户是否手动滚动,用于决定流式 token 来时是否自动贴底。
let userPinnedToBottom = true

// ===== 计算属性 =====
const headerTitle = computed(() => {
  if (activeConversationId.value === null) return '新的对话'
  const conv = conversations.value.find((c) => String(c.id) === String(activeConversationId.value))
  return conv?.title || '新的对话'
})

const agentLabel = computed(() => {
  const map: Record<AgentType, string> = {
    law_qa: '法律咨询',
    article_locate: '法条定位',
    contract_review: '合同审查',
    case_analysis: '案例分析',
  }
  return routerDecision.value ? map[routerDecision.value.agent] ?? routerDecision.value.agent : ''
})

const agentIcon = computed(() => {
  const map: Record<AgentType, typeof Scale> = {
    law_qa: Scale,
    article_locate: Search,
    contract_review: BriefcaseBusiness,
    case_analysis: FileSearch,
  }
  return routerDecision.value ? map[routerDecision.value.agent] ?? Scale : Scale
})

const riskLabel = computed(() => {
  const map: Record<string, string> = { low: '低风险', medium: '中风险', high: '高风险' }
  return routerDecision.value ? map[routerDecision.value.risk_level] ?? routerDecision.value.risk_level : ''
})

// 欢迎屏快捷问题卡片:多组可切换,模拟不同法律场景下的常见问题。
type Suggestion = { title: string; query: string; kb_ids: string[]; icon: any }
type SuggestionGroup = Suggestion[]

const suggestionGroups: SuggestionGroup[] = [
  [
    { title: '合同解除', query: '劳动合同解除的法定情形有哪些?', kb_ids: [], icon: Scale },
    { title: '盗窃罪量刑', query: '刑法第二百六十四条关于盗窃罪的规定是什么?', kb_ids: [], icon: Search },
    { title: '民间借贷', query: '民间借贷利率超过 LPR 四倍的法律后果?', kb_ids: [], icon: FileSearch },
    { title: '租赁合同', query: '房屋租赁合同中常见的违约条款风险点?', kb_ids: [], icon: BriefcaseBusiness },
  ],
  [
    { title: '工伤认定', query: '工伤认定的法定条件和赔偿标准?', kb_ids: [], icon: ShieldAlert },
    { title: '离婚财产', query: '离婚时夫妻共同财产如何分割?', kb_ids: [], icon: Users },
    { title: '公司法务', query: '有限责任公司股权转让的法定程序?', kb_ids: [], icon: BriefcaseBusiness },
    { title: '消费者保护', query: '消费者权益保护法中三倍赔偿的适用条件?', kb_ids: [], icon: Scale },
  ],
  [
    { title: '遗嘱效力', query: '自书遗嘱的有效要件是什么?', kb_ids: [], icon: FileText },
    { title: '交通事故', query: '交通事故责任认定与保险理赔流程?', kb_ids: [], icon: Search },
    { title: '竞业限制', query: '竞业限制协议的法律效力和补偿金标准?', kb_ids: [], icon: BriefcaseBusiness },
    { title: '行政处罚', query: '行政处罚的听证程序和救济途径?', kb_ids: [], icon: Gavel },
  ],
]

const suggestionGroupIndex = ref(0)
const currentSuggestions = computed(() => suggestionGroups[suggestionGroupIndex.value] ?? [])

// ===== 生命周期 =====
onMounted(async () => {
  await Promise.all([loadConversations(), loadKnowledgeBases()])
  // 支持从历史会话页跳转过来时自动选中指定会话(如 /assistant?conversation_id=123)。
  const targetId = route.query.conversation_id
  if (targetId) {
    const target = conversations.value.find((c) => String(c.id) === String(targetId))
    if (target) {
      await selectConversation(target)
      return
    }
  }
  // 默认进入"新的对话"空态,不预选会话,聚焦输入框。
  nextTick(() => composerRef.value?.focus())
})

// ===== 数据加载 =====
async function loadConversations() {
  convLoading.value = true
  try {
    const data = await listConversations({ page: 1, page_size: 50 })
    conversations.value = data.items
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '会话列表加载失败')
  } finally {
    convLoading.value = false
  }
}

async function loadKnowledgeBases() {
  try {
    knowledgeBases.value = await listKnowledgeBases()
  } catch (err) {
    // 知识库加载失败不阻塞对话,只是无法选择检索范围。
    console.warn('知识库列表加载失败', err)
  }
}

// ===== 会话切换 =====
function startNewConversation() {
  if (streaming.value) {
    ElMessage.warning('请先停止当前生成再新建对话')
    return
  }
  activeConversationId.value = null
  messages.value = []
  routerDecision.value = null
  resetStreamState()
  nextTick(() => composerRef.value?.focus())
}

async function selectConversation(conv: Conversation) {
  if (streaming.value) {
    ElMessage.warning('请先停止当前生成再切换会话')
    return
  }
  if (String(conv.id) === String(activeConversationId.value)) return
  activeConversationId.value = conv.id
  routerDecision.value = null
  resetStreamState()
  try {
    const detail = await getConversation(conv.id)
    messages.value = detail.messages.map(normalizeMessage)
    nextTick(scrollToBottom)
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '会话详情加载失败')
    messages.value = []
  }
}

async function handleDelete(conv: Conversation) {
  try {
    await deleteConversation(conv.id)
    ElMessage.success('会话已删除')
    // 如果删除的是当前会话,回到新建空态。
    if (String(conv.id) === String(activeConversationId.value)) {
      activeConversationId.value = null
      messages.value = []
      routerDecision.value = null
    }
    await loadConversations()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '删除失败')
  }
}

// ===== 发送对话 =====
async function handleSend(payload: {
  text: string
  kb_ids: string[]
  uploaded_files: UploadedFileRef[]
}) {
  if (streaming.value) return
  await runChat(payload.text, payload.kb_ids, payload.uploaded_files)
}

async function quickSend(text: string, kb_ids: string[]) {
  if (streaming.value) return
  await runChat(text, kb_ids, [])
}

// 核心:发起 SSE 流式对话,处理所有事件类型。
async function runChat(query: string, kb_ids: string[], uploaded_files: UploadedFileRef[] = []) {
  // 1. 立即把 user 消息塞进列表,assistant 占位消息紧跟其后。
  const userMsg: ConversationMessage = {
    id: `temp-user-${Date.now()}`,
    conversation_id: String(activeConversationId.value ?? ''),
    role: 'user',
    content: query,
    citations: null,
    feedback: null,
    retrieval_trace_id: null,
    created_at: new Date().toISOString(),
    uploaded_files: uploaded_files.length ? [...uploaded_files] : undefined,
  }
  const assistantMsg: ConversationMessage = {
    id: `temp-assistant-${Date.now()}`,
    conversation_id: String(activeConversationId.value ?? ''),
    role: 'assistant',
    content: '',
    citations: null,
    feedback: null,
    retrieval_trace_id: null,
    created_at: new Date().toISOString(),
  }
  messages.value.push(userMsg, assistantMsg)

  // 2. 重置流式状态,进入 streaming。
  resetStreamState()
  streaming.value = true
  userPinnedToBottom = true
  nextTick(scrollToBottom)

  // 3. 发起 SSE。
  abortController = new AbortController()
  const conversationIdStr = activeConversationId.value ? String(activeConversationId.value) : ''

  try {
    await streamAgentChat({
      payload: {
        query,
        conversation_id: conversationIdStr,
        kb_ids,
        ...(uploaded_files.length ? { uploaded_files } : {}),
      },
      signal: abortController.signal,
      onEvent: (event) => handleSseEvent(event, assistantMsg),
      onError: (err) => {
        ElMessage.error(err.message || '对话失败')
        // 错误时若 assistant 消息仍空,移除占位。
        if (!assistantMsg.content) {
          const idx = messages.value.findIndex((m) => m.id === assistantMsg.id)
          if (idx >= 0) messages.value.splice(idx, 1)
        }
      },
      onDone: () => {
        streaming.value = false
        // 流结束后刷新会话列表标题(新建会话会拿到真实 id 与标题)。
        loadConversations().catch(() => undefined)
      },
    })
  } finally {
    streaming.value = false
    abortController = null
  }
}

// 处理单条 SSE 事件,更新最后一条 assistant 消息。
function handleSseEvent(event: { event: string; [key: string]: unknown }, assistantMsg: ConversationMessage) {
  // 关键修复:assistantMsg 是 push 进 messages.value 之前的原始对象字面量。
  // 直接改原始对象不会触发 Vue 响应式(set trap 不经过),导致 renderedContent computed
  // 的依赖永远不失效,流式 token 文本、引用、结构化结果在整轮流式期间都"看不见",
  // 直到 done 事件替换 message id 触发组件重挂载才一次性显示。
  // 这里把引用重指向数组里的响应式代理,所有后续变更都走代理 set trap,实时刷新。
  const liveMsg = messages.value.find((m) => m.id === assistantMsg.id)
  if (liveMsg) {
    assistantMsg = liveMsg
  }
  switch (event.event) {
    case 'router': {
      // Router 决策结果,提取关键字段用于顶部 chips。
      const decision = event as unknown as RouterDecision & { event: string }
      routerDecision.value = {
        task_type: String(decision.task_type ?? ''),
        agent: decision.agent as AgentType,
        confidence: Number(decision.confidence ?? 0),
        need_retrieval: Boolean(decision.need_retrieval),
        retrieval_scope: decision.retrieval_scope ?? { domain: '', category: '', keywords: [] },
        need_file: Boolean(decision.need_file),
        file_requirement: (decision.file_requirement as RouterDecision['file_requirement']) ?? null,
        legal_context: decision.legal_context ?? { law_name: null, article_no: null, cause_of_action: null },
        sub_questions: decision.sub_questions ?? [],
        time_context: decision.time_context ?? { type: 'latest', year: null },
        execution_mode: String(decision.execution_mode ?? 'rag'),
        risk_level: (decision.risk_level as RouterDecision['risk_level']) ?? 'low',
        route_reason: String(decision.route_reason ?? ''),
        fallback: Boolean(decision.fallback),
        needs_human_review: Boolean(decision.needs_human_review),
      }
      // 同步 agent_type 到 assistant 消息,供 ChatMessage 展示标签。
      ;(assistantMsg as ConversationMessage & { agent_type?: string }).agent_type = routerDecision.value.agent
      break
    }
    case 'node_start': {
      // 单 Agent 链路:切到节点级时间线(意图/检索/工具/推理/引用/校验)。
      timelineMode.value = 'node'
      currentNode.value = String(event.node ?? '')
      break
    }
    case 'node_end': {
      const node = String(event.node ?? '')
      if (node) {
        const next = new Set(finishedNodes.value)
        next.add(node)
        finishedNodes.value = next
      }
      // retrieve 节点结束时报 chunk_count。
      if (node === 'retrieve' && typeof event.chunk_count === 'number') {
        chunkCount.value = event.chunk_count as number
      }
      // tool_exec 节点结束时报 tool_count。
      if (node === 'tool_exec' && typeof event.tool_count === 'number') {
        toolCount.value = event.tool_count as number
      }
      currentNode.value = null
      break
    }
    case 'token': {
      // 流式 token 追加到 assistant 消息正文。
      const piece = String(event.content ?? '')
      assistantMsg.content += piece
      if (userPinnedToBottom) nextTick(scrollToBottom)
      break
    }
    case 'citation': {
      // 引用列表,写入 citations.items 形态。
      const citations = (event.citations as Citation[]) ?? []
      assistantMsg.citations = { items: citations }
      break
    }
    case 'final': {
      // 最终载荷:覆盖答案、引用、风险提醒、合同分析结构化结果。
      const final = event as unknown as {
        answer: string
        citations: Citation[]
        risk_alerts: { level: string; message: string }[]
        trace_id: string
        needs_human_review: boolean
        contract?: ContractAnalysisResult
      }
      if (final.answer) assistantMsg.content = final.answer
      if (Array.isArray(final.citations)) assistantMsg.citations = { items: final.citations }
      if (Array.isArray(final.risk_alerts)) {
        ;(assistantMsg as ConversationMessage & { risk_alerts?: { level: string; message: string }[] }).risk_alerts = final.risk_alerts
      }
      if (final.trace_id) assistantMsg.retrieval_trace_id = final.trace_id
      if (final.contract) assistantMsg.contract = final.contract
      // 收尾:Agent 级时间线全部标记完成,清除当前执行态(Supervisor 无 synthesize 专属 agent_end)。
      currentAgent.value = null
      if (agentSteps.value.length) {
        finishedAgents.value = new Set(agentSteps.value.map((s) => s.agent))
      }
      break
    }
    case 'done': {
      // 会话与消息已落库,更新真实 id,便于后续反馈与 trace 跳转。
      const done = event as unknown as {
        conversation_id: string
        message_id: string
        trace_id: string
        upload_ids?: string[]
      }
      assistantMsg.id = done.message_id
      assistantMsg.conversation_id = done.conversation_id
      if (done.trace_id) assistantMsg.retrieval_trace_id = done.trace_id
      if (Array.isArray(done.upload_ids) && done.upload_ids.length) {
        assistantMsg.upload_ids = done.upload_ids
      }
      activeConversationId.value = done.conversation_id
      break
    }
    case 'v2_plan': {
      // v2 编排计划:记录 Agent 步骤,供 AgentTimeline 展示深度报告生成进度。
      timelineMode.value = 'agent'
      const steps = (event.steps as Array<{ step_id: string; agent: string; goal: string }>) ?? []
      agentSteps.value = steps.map((s) => ({
        step_id: String(s.step_id ?? ''),
        agent: String(s.agent ?? ''),
        goal: String(s.goal ?? ''),
      }))
      break
    }
    case 'supervisor_start': {
      // Supervisor 编排开始:切到 Agent 级时间线(展示"这个提问用了哪些 Agent")。
      timelineMode.value = 'agent'
      agentSteps.value = []
      currentAgent.value = null
      break
    }
    case 'supervisor_synthesize': {
      // 进入合成阶段:登记"答案合成"步骤并点亮。
      if (!agentSteps.value.some((s) => s.agent === 'synthesize')) {
        agentSteps.value.push({
          step_id: 'synthesize',
          agent: 'synthesize',
          goal: String(event.reason ?? '合并引用并重写最终答案'),
        })
      }
      currentAgent.value = 'synthesize'
      break
    }
    case 'supervisor_finish': {
      // finish=直接使用最后一个 Agent 的答案,无合成阶段。
      currentAgent.value = null
      break
    }
    case 'agent_start': {
      // Agent 开始执行:Supervisor 动态调度时把出现的 Agent 登记进步骤(去重);
      // v2 的 v2_plan 已预置步骤,此处不会重复。
      const agent = String(event.agent ?? '')
      if (agent && !agentSteps.value.some((s) => s.agent === agent)) {
        agentSteps.value.push({
          step_id: `agent-${agentSteps.value.length + 1}`,
          agent,
          goal: String(event.thought ?? event.input ?? ''),
        })
      }
      currentAgent.value = agent
      break
    }
    case 'agent_end': {
      // v2 编排某 Agent 结束:标记完成,失败则红显该步骤。
      const agent = String(event.agent ?? '')
      if (agent) {
        const next = new Set(finishedAgents.value)
        next.add(agent)
        finishedAgents.value = next
        if (String(event.output_summary ?? '').includes('失败')) {
          const failed = new Set(failedAgents.value)
          failed.add(agent)
          failedAgents.value = failed
        }
      }
      currentAgent.value = null
      break
    }
    default:
      // 未知事件忽略,向前兼容后端新增事件。
      break
  }
}

// 停止流式生成。
function stopStreaming() {
  if (abortController) {
    abortController.abort()
    abortController = null
  }
  streaming.value = false
  currentNode.value = null
}

// 重置流式过程状态。
function resetStreamState() {
  finishedNodes.value = new Set()
  currentNode.value = null
  chunkCount.value = null
  toolCount.value = null
  routerDecision.value = null
  agentSteps.value = []
  currentAgent.value = null
  finishedAgents.value = new Set()
  failedAgents.value = new Set()
  timelineMode.value = null
}

// ===== 滚动控制 =====
function handleScroll() {
  const el = scrollRef.value
  if (!el) return
  // 距底部 80px 内视为贴底,允许自动滚动。
  userPinnedToBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80
}

function scrollToBottom() {
  const el = scrollRef.value
  if (!el) return
  el.scrollTop = el.scrollHeight
}

// ===== 消息反馈与操作 =====
async function handleFeedback(msg: ConversationMessage, feedback: Exclude<MessageFeedback, null>) {
  if (!msg.id || msg.id.startsWith('temp-')) {
    ElMessage.warning('消息尚未保存,无法反馈')
    return
  }
  // 乐观更新,失败回滚。
  const prev = msg.feedback
  msg.feedback = feedback
  try {
    await feedbackMessage(msg.conversation_id, msg.id, feedback)
    ElMessage.success(feedback === 'like' ? '感谢反馈' : '已记录改进建议')
  } catch (err) {
    msg.feedback = prev
    ElMessage.error(err instanceof Error ? err.message : '反馈失败')
  }
}

function handleTrace(traceId: string) {
  // 跳转到检索调试页(如已实现),这里给出提示并打开新标签。
  const url = `/api/retrieve/trace/${traceId}`
  window.open(url, '_blank')
}

async function handleCopy(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.error('复制失败,请手动选择文本')
  }
}

// ===== 工具函数 =====
// 后端消息的 citations 可能是 {"items": [...]}、[...] 或 null,统一规整。
function normalizeMessage(msg: ConversationMessage): ConversationMessage {
  if (msg.citations && Array.isArray((msg.citations as { items?: Citation[] }).items)) {
    return msg
  }
  if (Array.isArray(msg.citations)) {
    return { ...msg, citations: { items: msg.citations as Citation[] } }
  }
  return msg
}
</script>

<style scoped>
/* Assistant 是一个全屏工作台。
   浅色：聊天区域背景用灰白 #F8FAFC，主内容与消息卡片用纯白，层次清晰。
   深色：深空面板，保持原视觉。 */
.assistant-page {
  position: relative;
  display: flex;
  height: calc(100vh - 72px);
  background: var(--law-bg);
  overflow: hidden;
}

.assistant-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: var(--law-bg);
}

:global(html.dark) .assistant-page {
  background: var(--law-bg);
  border-left: 1px solid var(--law-border);
}

:global(html.dark) .assistant-main {
  background: var(--law-bg-soft);
}

/* ===== 顶部条 ===== */
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 24px;
  border-bottom: 1px solid var(--law-border);
  background: var(--law-card);
}

:global(html.dark) .chat-header {
  background: linear-gradient(180deg, var(--law-card) 0%, var(--law-bg-soft) 100%);
  border-bottom-color: var(--law-border);
}

.header-left {
  min-width: 0;
  flex: 1;
}

.header-title {
  margin: 0;
  font-family: 'Cormorant Garamond', 'Noto Serif SC', serif;
  font-size: 20px;
  font-weight: 700;
  color: var(--law-text);
  letter-spacing: 0.01em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.router-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.02em;
}

.chip-agent {
  background: rgba(30, 58, 95, 0.10);
  color: var(--law-primary-strong);
}

.chip-risk {
  background: rgba(201, 169, 110, 0.14);
  color: var(--law-gold-strong);
}

:global(html.dark) .chip-risk {
  color: var(--law-gold);
}

.chip-retr {
  background: rgba(30, 58, 95, 0.08);
  color: var(--law-accent);
}

.chip-conf {
  background: var(--law-bg);
  color: var(--law-muted);
}

:global(html.dark) .chip-conf {
  background: rgb(255 255 255 / 8%);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: 1px solid var(--law-border);
  border-radius: 9px;
  background: var(--law-card);
  color: var(--law-muted);
  cursor: pointer;
  transition: all 160ms ease;
}

.icon-btn:hover:not(:disabled) {
  border-color: var(--law-primary);
  color: var(--law-primary-strong);
  background: rgba(30, 58, 95, 0.06);
}

.icon-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ===== 消息流 ===== */
.chat-stream {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 22px 24px 8px;
  scroll-behavior: smooth;
  background: var(--law-bg);
}

:global(html.dark) .chat-stream {
  background: var(--law-bg-soft);
}

.chat-stream::-webkit-scrollbar {
  width: 8px;
}

.chat-stream::-webkit-scrollbar-thumb {
  background: rgba(15, 23, 42, 0.12);
  border-radius: 4px;
}

:global(html.dark) .chat-stream::-webkit-scrollbar-thumb {
  background: rgb(255 255 255 / 12%);
}

.stream-inner {
  display: flex;
  flex-direction: column;
  gap: 22px;
  max-width: 980px;
  margin: 0 auto;
}

/* ===== 欢迎屏 ===== */
.welcome-screen {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100%;
  padding: 40px 20px;
  text-align: center;
}

.welcome-mark {
  width: 88px;
  height: 88px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 24px;
  background: linear-gradient(160deg, #ffffff 0%, #f5f7fb 100%);
  color: #fff;
  box-shadow:
    0 14px 34px rgba(15, 38, 68, 0.12),
    inset 0 1px 0 rgba(255, 255, 255, 1);
  border: 1px solid rgba(201, 169, 110, 0.55);
  margin-bottom: 24px;
}

.welcome-logo {
  width: 56px;
  height: 56px;
  display: block;
  object-fit: contain;
  filter: drop-shadow(0 2px 6px rgba(201, 169, 110, 0.3));
}

.welcome-title {
  margin: 0 0 10px;
  font-family: 'Cormorant Garamond', 'Noto Serif SC', serif;
  font-size: 38px;
  font-weight: 700;
  color: var(--law-text);
  letter-spacing: 0.02em;
}

.welcome-sub {
  max-width: 560px;
  margin: 0 0 32px;
  font-size: 14px;
  line-height: 1.8;
  color: var(--law-muted);
}

.welcome-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  width: 100%;
  max-width: 720px;
}

.welcome-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  border: 1px solid var(--law-border);
  border-radius: 14px;
  background: var(--law-card);
  text-align: left;
  cursor: pointer;
  transition: all 200ms ease;
}

.welcome-card:hover {
  border-color: var(--law-primary);
  box-shadow: 0 10px 28px rgba(30, 58, 95, 0.14);
  transform: translateY(-2px);
}

.card-icon {
  width: 38px;
  height: 38px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  background: rgba(30, 58, 95, 0.10);
  color: var(--law-primary);
}

.card-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.card-title {
  font-size: 13.5px;
  font-weight: 700;
  color: var(--law-text);
}

.card-desc {
  font-size: 12px;
  color: var(--law-muted);
  line-height: 1.5;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.card-arrow {
  color: var(--law-muted);
  flex-shrink: 0;
  transition: transform 200ms ease;
}

.welcome-card:hover .card-arrow {
  transform: translateX(3px);
  color: var(--law-primary);
}

@media (max-width: 960px) {
  .assistant-page {
    flex-direction: column;
    height: auto;
    min-height: calc(100vh - 72px);
  }

  .assistant-main {
    min-height: 520px;
  }

  .welcome-grid {
    grid-template-columns: 1fr;
  }

  .chat-stream {
    padding: 16px 12px 8px;
  }
}

/* ===== 侧边栏收起/展开 ===== */
.assistant-page.sidebar-collapsed .assistant-main {
  flex: 1;
  min-width: 0;
  margin-left: 0;
}

.sidebar-expand-btn {
  position: absolute;
  left: 6px;
  top: 50%;
  transform: translateY(-50%);
  width: 28px;
  height: 56px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--law-border);
  border-radius: 0 8px 8px 0;
  background: var(--law-card);
  color: var(--law-muted);
  cursor: pointer;
  box-shadow: 2px 0 10px rgba(15, 38, 68, 0.10);
  transition: all 180ms ease;
  z-index: 10;
}

.sidebar-expand-btn:hover {
  color: var(--law-primary);
  background: rgba(30, 58, 95, 0.06);
}

/* ===== 欢迎屏问题切换 ===== */
.welcome-grid-wrap {
  display: flex;
  flex-direction: column;
  gap: 14px;
  width: 100%;
  max-width: 760px;
}

.suggestion-switch {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 6px 0;
}

.switch-arrow {
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--law-border);
  border-radius: 50%;
  background: transparent;
  color: var(--law-muted);
  cursor: pointer;
  transition: all 160ms ease;
}

.switch-arrow:hover:not(:disabled) {
  color: var(--law-primary);
  border-color: var(--law-primary);
}

.switch-arrow:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.switch-dots {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.switch-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--law-border);
  cursor: pointer;
  transition: all 180ms ease;
}

.switch-dot.active {
  width: 20px;
  border-radius: 4px;
  background: var(--law-primary);
}
</style>
