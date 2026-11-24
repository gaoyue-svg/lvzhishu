<!-- 最近聊天组件，展示用户近期法律咨询会话。 -->
<template>
  <SectionPanel
    title="最近聊天"
    description="继续处理未完成的法律问题"
  >
    <template #action>
      <el-button
        link
        type="primary"
        @click="router.push('/history')"
      >
        查看全部
      </el-button>
    </template>

    <div class="chat-list">
      <button
        v-for="chat in chats"
        :key="chat.id"
        class="chat-row"
        type="button"
        @click="openChat(chat.title)"
      >
        <span class="chat-icon"><MessageCircle :size="16" /></span>
        <span class="chat-main">
          <strong>{{ chat.title }}</strong>
          <small>{{ chat.summary }}</small>
        </span>
        <span class="chat-meta">
          <el-tag
            size="small"
            effect="light"
          >{{ chat.category }}</el-tag>
          <time>{{ chat.time }}</time>
        </span>
      </button>
    </div>
  </SectionPanel>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { MessageCircle } from 'lucide-vue-next'

import SectionPanel from './SectionPanel.vue'
import type { RecentChat } from '@/types/dashboard'

defineProps<{
  chats: RecentChat[]
}>()

const router = useRouter()

function openChat(title: string) {
  ElMessage.success(`打开会话：${title}`)
}
</script>

<style scoped>
.chat-list {
  display: grid;
  gap: 10px;
}

.chat-row {
  width: 100%;
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  padding: 12px;
  border: 1px solid transparent;
  border-radius: 14px;
  color: var(--law-text);
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition:
    background 160ms ease,
    border-color 160ms ease;
}

.chat-row:hover {
  border-color: var(--law-border);
  background: var(--law-bg-soft);
}

.chat-icon {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  color: var(--law-primary);
  background: var(--law-primary-soft);
}

.chat-main {
  min-width: 0;
  display: grid;
  gap: 4px;
}

.chat-main strong,
.chat-main small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chat-main strong {
  font-size: 14px;
}

.chat-main small,
.chat-meta time {
  color: var(--law-muted);
  font-size: 12px;
}

.chat-meta {
  display: grid;
  justify-items: end;
  gap: 6px;
}
</style>
