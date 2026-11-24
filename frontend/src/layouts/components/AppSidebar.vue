<!-- 左侧固定菜单，承载 LawAgent 主要功能入口与当前路由状态。 -->
<template>
  <aside class="app-sidebar">
    <div class="sidebar-top">
      <AppLogo :compact="appStore.sidebarCollapsed" />
      <el-tooltip
        content="收起/展开菜单"
        placement="right"
      >
        <button
          class="icon-button subtle"
          type="button"
          @click="appStore.toggleSidebar"
        >
          <PanelLeftClose
            v-if="!appStore.sidebarCollapsed"
            :size="18"
          />
          <PanelLeftOpen
            v-else
            :size="18"
          />
        </button>
      </el-tooltip>
    </div>

    <nav
      class="sidebar-nav"
      aria-label="主导航"
    >
      <RouterLink
        v-for="item in menuItems"
        :key="item.path"
        v-slot="{ navigate }"
        :to="item.path"
        custom
      >
        <el-tooltip
          :content="item.label"
          :disabled="!appStore.sidebarCollapsed"
          placement="right"
          :show-after="240"
        >
          <button
            class="nav-item"
            :class="{ active: isMenuActive(item.path) }"
            type="button"
            @click="navigate"
          >
            <component
              :is="item.icon"
              :size="18"
            />
            <span v-if="!appStore.sidebarCollapsed">{{ item.label }}</span>
          </button>
        </el-tooltip>
      </RouterLink>
    </nav>

  </aside>
</template>

<script setup lang="ts">
import { PanelLeftClose, PanelLeftOpen } from 'lucide-vue-next'
import { RouterLink, useRoute } from 'vue-router'

import AppLogo from './AppLogo.vue'
import { menuItems } from '@/router/menu'
import { useAppStore } from '@/stores/app'

const appStore = useAppStore()
const route = useRoute()

function isMenuActive(path: string) {
  if (path === '/') {
    return route.path === '/'
  }
  return route.path === path || route.path.startsWith(`${path}/`)
}
</script>

<style scoped>
/* 深蓝藏青浅色导航：用分组卡片感替代旧版纯白蓝色后台样式。 */
.app-sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
  display: flex;
  flex-direction: column;
  padding: 22px 14px;
  overflow: hidden;
  background: var(--law-sidebar);
  border-right: 1px solid var(--law-border-soft);
  color: var(--law-text);
}

.sidebar-top {
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.sidebar-nav {
  display: grid;
  gap: 5px;
  margin-top: 30px;
}

.icon-button,
.theme-entry,
.nav-item {
  border: 0;
  cursor: pointer;
}

.icon-button {
  width: 34px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  color: var(--law-muted);
  background: transparent;
  transition:
    background 160ms ease,
    color 160ms ease,
    transform 160ms ease;
}

.icon-button:hover {
  background: var(--law-sidebar-soft);
  color: var(--law-primary);
  transform: translateY(-1px);
}

.nav-item {
  position: relative;
  width: 100%;
  height: 42px;
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 0 12px;
  border-radius: 12px;
  color: var(--law-muted);
  background: transparent;
  text-align: left;
  font-size: 14px;
  letter-spacing: 0.01em;
  font-weight: 600;
  transition:
    background 180ms ease,
    color 180ms ease,
    transform 180ms ease;
}

.nav-item:hover {
  color: var(--law-primary-strong);
  background: var(--law-sidebar-soft);
  transform: translateX(2px);
}

.nav-item.active {
  color: #ffffff;
  background: linear-gradient(135deg, #1e3a5f 0%, #0f2644 100%);
  box-shadow:
    0 10px 24px rgba(15, 38, 68, 0.22),
    inset 0 1px 0 rgba(201, 169, 110, 0.2);
  font-weight: 700;
  border: 1px solid rgba(201, 169, 110, 0.3);
}

/* 新版激活态使用完整色块，不再使用旧版左侧蓝色竖线。 */
.nav-item.active::before {
  display: none;
}

.nav-item span {
  white-space: nowrap;
}

@media (max-width: 768px) {
  .app-sidebar {
    position: fixed;
    z-index: 30;
    inset: auto 12px 12px;
    height: 62px;
    display: block;
    padding: 8px;
    border-radius: 18px;
    box-shadow: 0 20px 48px rgb(15 23 42 / 24%);
    border-right: 0;
  }

  .sidebar-top,
  .sidebar-bottom {
    display: none;
  }

  .sidebar-nav {
    height: 100%;
    display: flex;
    gap: 6px;
    margin: 0;
    overflow-x: auto;
  }

  .nav-item {
    width: 46px;
    height: 46px;
    justify-content: center;
    padding: 0;
  }

  .nav-item span {
    display: none;
  }
}
</style>
