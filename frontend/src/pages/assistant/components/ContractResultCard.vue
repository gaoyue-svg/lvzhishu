<!--
  合同分析结果卡片:
  - 关键要素表(结构化 elements)
  - 风险清单(等级徽章 + 描述 + 建议 + 法条)
  - 底部"导出审查报告"按钮(.docx)
  摘要已在主答案 Markdown 中呈现,本卡片只渲染结构化数据。
-->
<template>
  <div
    v-if="visible"
    class="contract-card"
  >
    <!-- 关键要素表 -->
    <template v-if="elementRows.length > 0">
      <div class="cc-section-title">
        <FileKey2 :size="14" />
        合同要素
      </div>
      <div class="cc-elements">
        <div
          v-for="row in elementRows"
          :key="row.label"
          class="cc-element-row"
        >
          <span class="cc-element-label">{{ row.label }}</span>
          <span class="cc-element-value">{{ row.value }}</span>
        </div>
      </div>
    </template>

    <!-- 风险清单 -->
    <template v-if="risks.length > 0">
      <div class="cc-section-title cc-risks-title">
        <ShieldAlert :size="14" />
        风险清单
      </div>
      <div class="cc-risks">
        <div
          v-for="(risk, idx) in risks"
          :key="idx"
          class="cc-risk"
          :class="`cc-risk-${risk.level}`"
        >
          <div class="cc-risk-head">
            <span class="cc-risk-badge">{{ levelLabel(risk.level) }}</span>
            <span
              v-if="risk.clause"
              class="cc-risk-clause"
            >{{ risk.clause }}</span>
            <span class="cc-risk-title">{{ risk.title }}</span>
          </div>
          <div class="cc-risk-desc">{{ risk.description }}</div>
          <div
            v-if="risk.suggestion"
            class="cc-risk-suggestion"
          >
            <span class="cc-sug-label">建议：</span>{{ risk.suggestion }}
          </div>
          <div
            v-if="lawText"
            class="cc-risk-law"
          >
            <span class="cc-sug-label">依据：</span>{{ lawText(risk) }}
          </div>
        </div>
      </div>
    </template>

    <!-- 导出报告 -->
    <div
      v-if="uploadId"
      class="cc-export"
    >
      <button
        type="button"
        class="cc-export-btn"
        :disabled="exporting"
        @click="handleExport"
      >
        <Download :size="13" />
        {{ exporting ? '导出中…' : '导出审查报告 (.docx)' }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Download, FileKey2, ShieldAlert } from 'lucide-vue-next'

import { downloadContractReport } from '@/api/agent'
import type { ContractAnalysisResult, ContractRisk } from '@/types/conversation'

const props = defineProps<{
  result: ContractAnalysisResult
  // 用于导出报告的上传 ID。
  uploadId?: string
}>()

const exporting = ref(false)

// 要素展示顺序与中文标签。
const elementFields: { key: string; label: string }[] = [
  { key: 'contract_name', label: '合同名称' },
  { key: 'contract_type', label: '合同类型' },
  { key: 'party_a', label: '甲方' },
  { key: 'party_b', label: '乙方' },
  { key: 'amount', label: '合同金额' },
  { key: 'currency', label: '币种' },
  { key: 'payment_terms', label: '付款方式' },
  { key: 'payment_deadline', label: '付款期限' },
  { key: 'contract_term', label: '合同期限' },
  { key: 'effective_date', label: '生效日期' },
  { key: 'governing_law', label: '适用法律' },
  { key: 'jurisdiction', label: '争议解决' },
  { key: 'breach_liability', label: '违约责任' },
  { key: 'signing_requirements', label: '签署生效' },
  { key: 'key_obligations', label: '核心义务' },
  { key: 'important_clauses', label: '重要条款' },
]

const risks = computed<ContractRisk[]>(() => props.result.risks ?? [])
const elements = computed<Record<string, unknown>>(
  () => (props.result.elements ?? {}) as Record<string, unknown>,
)

const elementRows = computed(() => {
  const rows: { label: string; value: string }[] = []
  for (const field of elementFields) {
    const value = elementDisplay(elements.value[field.key])
    if (value) rows.push({ label: field.label, value })
  }
  return rows
})

// 渲染对象/数组/字符串为展示文本。
function elementDisplay(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'string') return value.trim()
  if (Array.isArray(value)) return value.filter(Boolean).map(String).join('；')
  if (typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>)
      .filter(([, v]) => v != null && String(v).trim() !== '')
      .map(([k, v]) => `${k}：${String(v)}`)
      .join('；')
  }
  return String(value)
}

function levelLabel(level: string): string {
  const map: Record<string, string> = { high: '高风险', medium: '中风险', low: '低风险' }
  return map[level] ?? (level ? String(level) : '风险')
}

function lawText(risk: ContractRisk): string {
  const ref = risk.law_reference
  if (!ref) return ''
  return Array.isArray(ref) ? ref.join('；') : String(ref)
}

const visible = computed(() => elementRows.value.length > 0 || risks.value.length > 0 || Boolean(props.uploadId))

async function handleExport() {
  if (!props.uploadId || exporting.value) return
  exporting.value = true
  try {
    const blob = await downloadContractReport(props.uploadId)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = '合同审查报告.docx'
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
    ElMessage.success('报告已下载')
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '报告导出失败')
  } finally {
    exporting.value = false
  }
}
</script>

<style scoped>
.contract-card {
  margin-top: 12px;
  padding: 14px 16px;
  border: 1px solid var(--law-border);
  border-radius: 12px;
  background: var(--law-bg);
}

.cc-section-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
  font-size: 13px;
  font-weight: 800;
  color: var(--law-text);
}

.cc-section-title :deep(svg) {
  color: var(--law-primary);
}

.cc-risks-title {
  margin-top: 16px;
}

.cc-elements {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 7px 18px;
}

.cc-element-row {
  display: flex;
  gap: 8px;
  font-size: 12.5px;
  line-height: 1.6;
}

.cc-element-label {
  flex-shrink: 0;
  min-width: 64px;
  color: var(--law-muted);
  font-weight: 700;
}

.cc-element-value {
  color: var(--law-text);
  overflow-wrap: anywhere;
}

.cc-risks {
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.cc-risk {
  padding: 10px 12px;
  border: 1px solid var(--law-border);
  border-left: 3px solid var(--law-border);
  border-radius: 9px;
  background: var(--law-card);
}

.cc-risk-high {
  border-left-color: rgb(239 68 68);
}

.cc-risk-medium {
  border-left-color: rgb(245 158 11);
}

.cc-risk-low {
  border-left-color: rgb(16 185 129);
}

.cc-risk-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 7px;
  margin-bottom: 6px;
}

.cc-risk-badge {
  padding: 1px 7px;
  border-radius: 5px;
  font-size: 10.5px;
  font-weight: 800;
  flex-shrink: 0;
}

.cc-risk-high .cc-risk-badge {
  background: rgb(239 68 68 / 14%);
  color: rgb(185 28 28);
}

.cc-risk-medium .cc-risk-badge {
  background: rgb(245 158 11 / 16%);
  color: rgb(180 83 9);
}

.cc-risk-low .cc-risk-badge {
  background: rgb(16 185 129 / 14%);
  color: rgb(5 122 85);
}

:global(html.dark) .cc-risk-high .cc-risk-badge {
  color: rgb(252 165 165);
}

:global(html.dark) .cc-risk-medium .cc-risk-badge {
  color: rgb(252 211 77);
}

:global(html.dark) .cc-risk-low .cc-risk-badge {
  color: rgb(94 234 212);
}

.cc-risk-clause {
  padding: 1px 7px;
  border-radius: 5px;
  background: rgb(37 99 235 / 10%);
  color: var(--law-primary-strong);
  font-size: 10.5px;
  font-weight: 800;
  flex-shrink: 0;
}

.cc-risk-title {
  font-size: 13px;
  font-weight: 800;
  color: var(--law-text);
}

.cc-risk-desc {
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--law-text);
}

.cc-risk-suggestion,
.cc-risk-law {
  margin-top: 6px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--law-text);
}

.cc-sug-label {
  color: var(--law-muted);
  font-weight: 700;
}

.cc-risk-law {
  color: var(--law-primary-strong);
}

.cc-export {
  margin-top: 14px;
  display: flex;
  justify-content: flex-end;
}

.cc-export-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border: 1px solid var(--law-primary);
  border-radius: 9px;
  background: rgb(37 99 235 / 8%);
  color: var(--law-primary-strong);
  font-size: 12.5px;
  font-weight: 800;
  cursor: pointer;
  transition: all 160ms ease;
}

.cc-export-btn:hover:not(:disabled) {
  background: rgb(37 99 235 / 16%);
  transform: translateY(-1px);
}

.cc-export-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

@media (max-width: 768px) {
  .cc-elements {
    grid-template-columns: 1fr;
  }
}
</style>
