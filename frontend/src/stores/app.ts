// 应用级状态管理，维护侧栏、语言与通知抽屉状态。
import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useAppStore = defineStore('app', () => {
  // 产品统一使用浅色主题，清理旧版本可能残留在根节点上的 dark 类名。
  document.documentElement.classList.remove('dark')
  const sidebarCollapsed = ref(false)
  const language = ref<'zh-CN' | 'en-US'>('zh-CN')
  const notificationOpen = ref(false)

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  function toggleNotifications() {
    notificationOpen.value = !notificationOpen.value
  }

  function setLanguage(value: 'zh-CN' | 'en-US') {
    language.value = value
  }

  return {
    sidebarCollapsed,
    toggleSidebar,
    language,
    setLanguage,
    notificationOpen,
    toggleNotifications,
  }
})
