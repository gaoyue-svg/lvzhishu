<!-- 应用布局组件，组织固定侧栏、顶部导航和主内容区域。 -->
<template>
  <div
    class="app-shell"
    :class="{ 'is-collapsed': appStore.sidebarCollapsed }"
  >
    <AppSidebar />
    <div class="app-workspace">
      <AppHeader />
      <main class="app-main">
        <RouterView v-slot="{ Component, route }">
          <!--
            AI 问答在 SSE 生成期间允许切换到其他业务页。仅缓存显式标记的页面，
            避免 Assistant 被卸载后丢失流式内容、处理进度和 Agent 时间线。
          -->
          <KeepAlive>
            <component
              :is="Component"
              v-if="route.meta.keepAlive"
              :key="String(route.name ?? route.path)"
            />
          </KeepAlive>
          <component
            :is="Component"
            v-if="!route.meta.keepAlive"
          />
        </RouterView>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { RouterView } from 'vue-router'

import AppHeader from './components/AppHeader.vue'
import AppSidebar from './components/AppSidebar.vue'
import { useAppStore } from '@/stores/app'

const appStore = useAppStore()
</script>

<style scoped>
.app-shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 252px minmax(0, 1fr);
  /* 让 body::before 的氛围光层透出，shell 自身保持透明 */
  background: transparent;
  transition: grid-template-columns 220ms ease;
}

.app-shell.is-collapsed {
  grid-template-columns: 76px minmax(0, 1fr);
}

.app-workspace {
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.app-main {
  width: 100%;
  min-height: calc(100vh - 72px);
  padding: 30px 34px 42px;
}

@media (max-width: 1024px) {
  .app-shell,
  .app-shell.is-collapsed {
    grid-template-columns: 88px minmax(0, 1fr);
  }
}

@media (max-width: 768px) {
  .app-shell,
  .app-shell.is-collapsed {
    grid-template-columns: 1fr;
  }

  .app-main {
    padding: 18px 14px 88px;
  }
}
</style>
