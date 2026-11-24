// 菜单配置集中维护侧边栏导航入口。
import {
  Activity,
  Bot,
  BriefcaseBusiness,
  Clock3,
  FileSearch,
  FileText,
  FolderOpen,
  Heart,
  Home,
  Search,
  Settings,
  UploadCloud,
  UserRound,
} from 'lucide-vue-next'
import type { Component } from 'vue'

export interface MenuItem {
  path: string
  name: string
  label: string
  icon: Component
}

export const menuItems: MenuItem[] = [
  { path: '/', name: 'Dashboard', label: '首页', icon: Home },
  { path: '/assistant', name: 'Assistant', label: 'AI 智能问答', icon: Bot },
  { path: '/laws', name: 'LawSearch', label: '法律法规检索', icon: Search },
  { path: '/cases', name: 'CaseSearch', label: '案例检索', icon: FileSearch },
  { path: '/contracts', name: 'ContractReview', label: '文件审查', icon: BriefcaseBusiness },
  { path: '/documents', name: 'LegalDocuments', label: '文书起草', icon: FileText },
  { path: '/knowledge', name: 'KnowledgeBase', label: '知识中心', icon: FolderOpen },
  { path: '/uploads', name: 'UploadCenter', label: '上传中心', icon: UploadCloud },
  { path: '/history', name: 'History', label: '历史会话', icon: Clock3 },
  { path: '/monitor', name: 'Monitor', label: '运营监控', icon: Activity },
  { path: '/favorites', name: 'Favorites', label: '收藏夹', icon: Heart },
  { path: '/profile', name: 'Profile', label: '个人中心', icon: UserRound },
  { path: '/settings', name: 'Settings', label: '系统设置', icon: Settings },
]
