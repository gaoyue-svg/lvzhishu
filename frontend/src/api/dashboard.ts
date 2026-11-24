// 首页接口模块，只展示当前用户的真实聚合数据；接口失败时由页面明确报错。
import { httpGet } from './request'
import { listKnowledgeBases } from './kb'

import type { DashboardData } from '@/types/dashboard'

export const getDashboardOverview = async (days: 7 | 14 | 30 = 7): Promise<DashboardData> => {
  const dashboard = await httpGet<DashboardData>('/dashboard/overview', { params: { days } })

  // 首页知识库卡片同时展示知识库总数和其中的文档总数。
  // 使用知识库列表返回的 doc_count 汇总，避免依赖 Mock 或写死统计值。
  try {
    const knowledgeBases = await listKnowledgeBases()
    const documentCount = knowledgeBases.reduce((total, kb) => total + (kb.doc_count || 0), 0)
    const knowledgeStat = dashboard.stats.find((stat) => stat.key === 'knowledgeBases')
    if (knowledgeStat) {
      knowledgeStat.value = knowledgeBases.length
      knowledgeStat.secondaryValue = documentCount
      knowledgeStat.secondaryUnit = '个文档'
    }
  } catch {
    // 知识库接口短暂不可用时仍保留 Dashboard 原始统计，不阻断首页加载。
  }

  return dashboard
}
