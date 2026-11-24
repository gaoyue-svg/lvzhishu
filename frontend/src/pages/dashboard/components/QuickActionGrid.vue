<!-- 快捷入口组件，提供首页到核心业务场景的一跳入口。 -->
<template>
  <div class="quick-grid">
    <button
      v-for="action in actions"
      :key="action.key"
      class="quick-card"
      :class="action.tone"
      type="button"
      @click="handleClick(action)"
    >
      <span class="quick-icon">
        <component
          :is="resolveIcon(action.icon)"
          :size="24"
        />
      </span>
      <strong>{{ action.title }}</strong>
      <small>{{ action.description }}</small>
    </button>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { FileText, MessageCircle, Search, ShieldCheck } from 'lucide-vue-next'

import type { QuickAction } from '@/types/dashboard'

defineProps<{
  actions: QuickAction[]
}>()

const router = useRouter()
const icons = {
  MessageCircle,
  Search,
  ShieldCheck,
  FileText,
}

function resolveIcon(name: string) {
  return icons[name as keyof typeof icons] ?? MessageCircle
}

function handleClick(action: QuickAction) {
  ElMessage.success(`进入${action.title}`)
  router.push(action.route)
}
</script>

<style scoped>
.quick-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 14px;
}

.quick-card {
  min-height: 148px;
  display: grid;
  align-content: center;
  justify-items: center;
  gap: 9px;
  padding: 18px 14px;
  border: 1px solid var(--law-border);
  border-radius: 16px;
  color: var(--law-text);
  background: var(--law-card);
  cursor: pointer;
  transition:
    transform 180ms ease,
    border-color 180ms ease,
    box-shadow 180ms ease;
}

.quick-card:hover {
  transform: translateY(-4px);
  border-color: rgba(30, 58, 95, 0.28);
  box-shadow: 0 18px 34px rgba(30, 58, 95, 0.12);
}

.quick-icon {
  width: 54px;
  height: 54px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 18px;
  background: var(--law-primary-soft);
}

.quick-card.blue .quick-icon {
  color: var(--law-primary);
  background: var(--law-primary-soft);
}

.quick-card.green .quick-icon {
  color: #28a06a;
  background: rgba(40, 160, 106, 0.12);
}

.quick-card.violet .quick-icon {
  color: #7c6ec7;
  background: rgba(124, 110, 199, 0.12);
}

.quick-card.amber .quick-icon {
  color: var(--law-gold-strong);
  background: var(--law-gold-soft);
}

.quick-card strong {
  font-size: 15px;
  line-height: 1.3;
}

.quick-card small {
  color: var(--law-muted);
  font-size: 12px;
  line-height: 1.5;
}

@media (max-width: 640px) {
  .quick-grid {
    grid-template-columns: 1fr;
  }
}
</style>
