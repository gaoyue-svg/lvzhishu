// 首页 Dashboard 类型定义，约束 Mock API 与组件之间的数据契约。
export interface StatItem {
  key: string
  label: string
  value: number
  unit: string
  trend: string
  status: 'up' | 'down' | 'stable'
  secondaryValue?: number
  secondaryUnit?: string
}

export interface QuickAction {
  key: string
  title: string
  description: string
  route: string
  icon: string
  tone: 'blue' | 'green' | 'violet' | 'amber'
}

export interface RecentChat {
  id: string
  title: string
  summary: string
  time: string
  category: string
}

export interface SearchRecord {
  id: string
  keyword: string
  scope: string
  count: number
  time: string
}

export interface Announcement {
  id: string
  title: string
  content: string
  level: 'info' | 'warning'
}

export interface SystemStatus {
  label: string
  value: number
  description: string
  color: string
  hasData?: boolean
}

export interface ChartPoint {
  day: string
  qa: number
  retrieval: number
  contract: number
  document: number
}

export interface PieSlice {
  name: string
  value: number
}

export interface DashboardData {
  userName: string
  stats: StatItem[]
  quickActions: QuickAction[]
  recentChats: RecentChat[]
  searchRecords: SearchRecord[]
  announcements: Announcement[]
  systemStatus: SystemStatus[]
  usageTrend: ChartPoint[]
  knowledgePie: PieSlice[]
}
