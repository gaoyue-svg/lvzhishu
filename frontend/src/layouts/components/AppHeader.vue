<!-- 顶部 Header 组件，提供全局搜索、通知、语言与用户菜单。 -->
<template>
  <header class="app-header">
    <div class="header-search">
      <Search :size="18" />
      <input
        v-model="keyword"
        type="search"
        placeholder="搜索法规、案例、合同、会话..."
        @keydown.enter="handleSearch"
      >
      <kbd>⌘ K</kbd>
    </div>

    <div class="header-actions">
      <el-tooltip
        content="消息通知"
        placement="bottom"
      >
        <button
          class="header-icon"
          type="button"
          @click="drawerVisible = true"
        >
          <Bell :size="18" />
          <span class="badge" />
        </button>
      </el-tooltip>

      <el-dropdown
        trigger="click"
        @command="handleLanguage"
      >
        <button
          class="language-button"
          type="button"
        >
          <Languages :size="17" />
          <span>{{ appStore.language === 'zh-CN' ? '中文' : 'EN' }}</span>
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="zh-CN">
              中文
            </el-dropdown-item>
            <el-dropdown-item command="en-US">
              English
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>

      <el-dropdown trigger="click" @command="handleUserCommand">
        <button
          class="user-button"
          type="button"
        >
          <img
            v-if="avatar"
            alt="用户头像"
            :src="avatar"
          >
          <span
            v-else
            class="avatar-fallback"
          >
            {{ displayName.charAt(0).toUpperCase() }}
          </span>
          <span>{{ displayName }}</span>
          <ChevronDown :size="16" />
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="profile">
              个人中心
            </el-dropdown-item>
            <el-dropdown-item command="security">
              账号安全
            </el-dropdown-item>
            <el-dropdown-item
              command="logout"
              divided
            >
              退出登录
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>

    <NotificationDrawer v-model="drawerVisible" />
  </header>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Bell, ChevronDown, Languages, Search } from 'lucide-vue-next'

import NotificationDrawer from './NotificationDrawer.vue'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'

const appStore = useAppStore()
const authStore = useAuthStore()
const router = useRouter()
const keyword = ref('')
const drawerVisible = ref(false)

// 头像与显示名优先取后端用户资料，未拉取到时降级为本地存储的用户名提示。
const displayName = computed(() => authStore.displayName)
const avatar = computed(() => authStore.avatar)

function handleSearch() {
  if (!keyword.value.trim()) {
    ElMessage.info('请输入要检索的法律问题或关键词')
    return
  }
  ElMessage.success(`已为你检索：${keyword.value}`)
}

function handleLanguage(value: 'zh-CN' | 'en-US') {
  appStore.setLanguage(value)
  ElMessage.success(value === 'zh-CN' ? '已切换为中文' : 'Language switched')
}

// 用户菜单命令分发：登出前确认并清理状态。
async function handleUserCommand(command: string) {
  if (command === 'logout') {
    try {
      await ElMessageBox.confirm('确定要退出登录吗？', '退出确认', {
        type: 'warning',
        confirmButtonText: '退出',
        cancelButtonText: '取消',
      })
    } catch {
      return
    }
    await authStore.logout()
    ElMessage.success('已安全退出')
    router.replace('/login')
    return
  }
  if (command === 'profile') {
    router.push('/profile')
    return
  }
  if (command === 'security') {
    router.push({ path: '/profile', query: { tab: 'security' } })
  }
}

// 进入应用后拉取一次用户资料，确保顶部信息与后端同步。
onMounted(() => {
  if (authStore.isAuthenticated && !authStore.user) {
    authStore.fetchUserProfile().catch(() => {})
  }
})
</script>

<style scoped>
.app-header {
  position: sticky;
  top: 0;
  z-index: 20;
  height: 72px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 0 34px;
  border-bottom: 1px solid #d8e4df;
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 4px 20px rgba(38, 74, 67, 0.04);
  backdrop-filter: blur(16px);
}

.header-search {
  width: min(600px, 50vw);
  height: 42px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 12px;
  border: 1px solid var(--law-border);
  border-radius: 999px;
  background: #f3f7f5;
  box-shadow: none;
  color: var(--law-muted);
  transition:
    border-color 180ms ease,
    box-shadow 180ms ease,
    background 180ms ease;
}

.header-search:focus-within {
  border-color: var(--law-primary);
  box-shadow: 0 0 0 3px var(--law-ring);
}

.header-search input {
  min-width: 0;
  flex: 1;
  border: 0;
  outline: 0;
  color: var(--law-text);
  background: transparent;
  font-size: 14px;
}

.header-search kbd {
  padding: 3px 7px;
  border: 1px solid var(--law-border);
  border-radius: 6px;
  color: var(--law-muted-soft);
  background: var(--law-bg);
  font-size: 12px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-icon,
.language-button,
.user-button {
  height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 1px solid var(--law-border);
  border-radius: 999px;
  color: var(--law-text);
  background: var(--law-card);
  cursor: pointer;
  transition:
    transform 160ms ease,
    box-shadow 160ms ease,
    border-color 160ms ease,
    background 160ms ease;
}

.header-icon {
  position: relative;
  width: 40px;
}

.header-icon:hover,
.language-button:hover,
.user-button:hover {
  transform: translateY(-1px);
  border-color: var(--law-primary);
  box-shadow: 0 5px 14px rgba(8, 127, 114, 0.12);
}

.badge {
  position: absolute;
  top: 9px;
  right: 10px;
  width: 7px;
  height: 7px;
  border: 2px solid var(--law-card);
  border-radius: 999px;
  background: #ef4444;
}

.language-button {
  padding: 0 12px;
  font-size: 13px;
}

.user-button {
  padding: 0 10px 0 6px;
  font-size: 14px;
}

.user-button img {
  width: 30px;
  height: 30px;
  border-radius: 999px;
  background: var(--law-primary-soft);
  object-fit: cover;
}

/* 无头像时显示首字母圆形占位。 */
.avatar-fallback {
  width: 30px;
  height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  color: #ffffff;
  background: linear-gradient(135deg, #2c5282 0%, #1e3a5f 100%);
  font-size: 13px;
  font-weight: 600;
}

@media (max-width: 768px) {
  .app-header {
    height: auto;
    flex-wrap: wrap;
    padding: 14px;
  }

  .header-search {
    order: 2;
    width: 100%;
  }

  .language-button span,
  .user-button span {
    display: none;
  }
}
</style>
