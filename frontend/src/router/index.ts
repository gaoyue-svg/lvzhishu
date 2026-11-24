// 路由入口，注册登录页与受保护业务路由，并通过全局守卫实施登录态校验。
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import AppLayout from '@/layouts/AppLayout.vue'
import Assistant from '@/pages/assistant/Assistant.vue'
import Dashboard from '@/pages/dashboard/Dashboard.vue'
import History from '@/pages/history/History.vue'
import KnowledgeBase from '@/pages/knowledge/KnowledgeBase.vue'
import KnowledgeDetail from '@/pages/knowledge/KnowledgeDetail.vue'
import LawSearch from '@/pages/laws/LawSearch.vue'
import Login from '@/pages/auth/Login.vue'
import MonitorConsole from '@/pages/monitor/MonitorConsole.vue'
import Profile from '@/pages/profile/Profile.vue'
import PlaceholderPage from '@/pages/placeholder/PlaceholderPage.vue'
import SystemSettings from '@/pages/settings/SystemSettings.vue'
import UploadCenter from '@/pages/upload/UploadCenter.vue'
import { useAuthStore } from '@/stores/auth'
import { menuItems } from './menu'

// 占位路由：除已实现页面外的菜单项暂指向占位页，保留导航可跳转。
const placeholderRoutes: RouteRecordRaw[] = menuItems
  .filter(
    (item) =>
      item.path !== '/' &&
      item.path !== '/assistant' &&
      item.path !== '/laws' &&
      item.path !== '/cases' &&
      item.path !== '/contracts' &&
      item.path !== '/documents' &&
      item.path !== '/archive' &&
      item.path !== '/knowledge' &&
      item.path !== '/uploads' &&
      item.path !== '/settings' &&
      item.path !== '/profile' &&
      item.path !== '/history' &&
      item.path !== '/monitor',
  )
  .map((item) => ({
    path: item.path,
    name: item.name,
    component: PlaceholderPage,
    meta: { title: item.label, requiresAuth: true },
  }))

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: Login,
      meta: { title: '登录', requiresGuest: true },
    },
    {
      path: '/',
      component: AppLayout,
      children: [
        {
          path: '',
          name: 'Dashboard',
          component: Dashboard,
          meta: { title: '首页', requiresAuth: true },
        },
        {
          path: 'assistant',
          name: 'Assistant',
          component: Assistant,
          meta: { title: 'AI 智能问答', requiresAuth: true, keepAlive: true },
        },
        {
          path: 'laws',
          name: 'LawSearch',
          component: LawSearch,
          meta: { title: '法规检索', requiresAuth: true },
        },
        {
          path: 'cases',
          name: 'CaseSearch',
          component: Assistant,
          meta: { title: '案例检索', requiresAuth: true, keepAlive: true, scene: 'case' },
        },
        {
          path: 'contracts',
          name: 'ContractReview',
          component: Assistant,
          meta: { title: '文件审查', requiresAuth: true, keepAlive: true, scene: 'contract' },
        },
        {
          path: 'documents',
          name: 'LegalDocuments',
          component: Assistant,
          meta: { title: '文书起草', requiresAuth: true, keepAlive: true, scene: 'document' },
        },
        {
          path: 'history',
          name: 'History',
          component: History,
          meta: { title: '历史会话', requiresAuth: true },
        },
        {
          path: 'knowledge',
          name: 'KnowledgeBase',
          component: KnowledgeBase,
          meta: { title: '知识中心', requiresAuth: true },
        },
        {
          path: 'knowledge/:id',
          name: 'KnowledgeDetail',
          component: KnowledgeDetail,
          meta: { title: '知识中心详情', requiresAuth: true },
        },
        {
          path: 'uploads',
          name: 'UploadCenter',
          component: UploadCenter,
          meta: { title: '上传中心', requiresAuth: true },
        },
        {
          path: 'settings',
          name: 'Settings',
          component: SystemSettings,
          meta: { title: '系统设置', requiresAuth: true },
        },
        {
          path: 'monitor',
          name: 'Monitor',
          component: MonitorConsole,
          meta: { title: '运营监控', requiresAuth: true },
        },
        {
          path: 'profile',
          name: 'Profile',
          component: Profile,
          meta: { title: '个人中心', requiresAuth: true },
        },
        ...placeholderRoutes,
      ],
    },
  ],
})

// 全局前置守卫：未登录用户访问受保护页面时跳转登录，已登录访问登录页时跳转首页。
router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.meta.requiresAuth && !auth.isAuthenticated) {
    return {
      path: '/login',
      query: { redirect: to.fullPath },
    }
  }
  if (to.meta.requiresGuest && auth.isAuthenticated) {
    return { path: '/' }
  }
  return true
})
