// 知识库类型元数据:统一维护类型标签、配色与图标,供列表卡片、筛选器、表单与详情头复用。
import {
  BookOpen,
  Building2,
  FileText,
  Gavel,
  Scale,
  type LucideIcon,
} from 'lucide-vue-next'

import type { KBStatus, KBType } from '@/types/kb'

export interface KBTypeMeta {
  value: KBType
  label: string
  description: string
  icon: LucideIcon
  // 主色与浅色背景,用于卡片图标徽章。
  color: string
  soft: string
}

// 知识库类型元数据表,顺序即为表单与筛选下拉的展示顺序。
export const kbTypeMetaList: KBTypeMeta[] = [
  {
    value: 'law',
    label: '法律法规',
    description: '国家法律、行政法规、地方性法规与部门规章',
    icon: Scale,
    color: '#1d4ed8',
    soft: '#dbeafe',
  },
  {
    value: 'case',
    label: '案例判例',
    description: '指导性案例、公报案例与典型裁判文书',
    icon: Gavel,
    color: '#b45309',
    soft: '#fef3c7',
  },
  {
    value: 'judicial',
    label: '司法解释',
    description: '最高法、最高检司法解释与批复文件',
    icon: BookOpen,
    color: '#7c3aed',
    soft: '#ede9fe',
  },
  {
    value: 'contract',
    label: '合同范本',
    description: '标准合同模板、条款库与审查参考样本',
    icon: FileText,
    color: '#0f766e',
    soft: '#ccfbf1',
  },
  {
    value: 'enterprise',
    label: '企业制度',
    description: '公司章程、内部规章与合规手册',
    icon: Building2,
    color: '#be123c',
    soft: '#ffe4e6',
  },
]

// 按类型值快速取元数据,未知类型回退到第一个(法律法规)。
export const getKBTypeMeta = (type: KBType): KBTypeMeta =>
  kbTypeMetaList.find((item) => item.value === type) ?? kbTypeMetaList[0]

// 状态元数据:启用为绿,停用为灰。
export const kbStatusMeta: Record<KBStatus, { label: string; color: string; soft: string }> = {
  enabled: { label: '启用中', color: '#15803d', soft: '#dcfce7' },
  disabled: { label: '已停用', color: '#475569', soft: '#e2e8f0' },
}

// 文档支持的解析后缀白名单,与后端 parser 支持范围保持一致。
export const ACCEPTED_FILE_TYPES = '.pdf,.docx,.txt,.html'
