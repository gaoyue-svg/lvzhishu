<!-- 品牌介绍面板：首页左侧展示律智枢产品定位、核心能力与能力亮点。 -->
<template>
  <section class="welcome-panel">
    <div class="welcome-copy">
      <h1 class="brand-title">律智枢</h1>
      <p class="brand-sub">
        AI 法律智能工作台
        <span class="brand-tag">专业 · 智能 · 可信</span>
      </p>

      <div class="capability-block">
        <h2>汇法律知识</h2>
        <p>
          融合法规检索、案例分析、合同审查与文书生成，为法律从业者提供有依据、可溯源、可执行的智能辅助。
        </p>
      </div>

      <ul class="feature-list">
        <li>
          <span class="feature-title">权威法源</span>
          <span class="feature-desc">聚合现行法规、司法解释与裁判规则</span>
        </li>
        <li>
          <span class="feature-title">智能研判</span>
          <span class="feature-desc">结合案情与检索依据生成专业分析</span>
        </li>
        <li>
          <span class="feature-title">风险与文书</span>
          <span class="feature-desc">识别合同风险，辅助生成规范法律文书</span>
        </li>
      </ul>

      <p class="welcome-footer">© 2026 律智枢 · 基于 RAG 与多 Agent 架构构建</p>
    </div>

    <div class="assistant-card">
      <div class="assistant-orbit">
        <Sparkles :size="30" />
      </div>
      <div>
        <strong>智能检索链路</strong>
        <span>Query Rewrite → Hybrid Retrieval → Rerank → Citation</span>
      </div>
      <el-progress
        :percentage="92"
        :stroke-width="8"
      />
      <div class="welcome-actions">
        <el-button
          type="primary"
          :icon="MessageCircle"
          @click="goAssistant"
        >
          发起法律问答
        </el-button>
        <el-button
          :icon="UploadCloud"
          @click="goUpload"
        >
          上传法律文档
        </el-button>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { MessageCircle, Sparkles, UploadCloud } from 'lucide-vue-next'

// 该面板已改为品牌介绍风格，不再依赖 userName。
defineProps<{
  userName?: string
}>()

const router = useRouter()

function goAssistant() {
  router.push('/assistant')
}

function goUpload() {
  router.push('/uploads')
}
</script>

<style scoped>
.welcome-panel {
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: 22px;
  padding: 32px;
  border: 1px solid var(--law-border);
  border-radius: 26px;
  background:
    radial-gradient(circle at 92% 12%, rgba(201, 169, 110, 0.12), transparent 28%),
    linear-gradient(135deg, #ffffff 0%, #f4f6f9 100%);
  box-shadow: 0 18px 45px rgba(15, 38, 68, 0.08);
  overflow: hidden;
}

.welcome-copy {
  min-width: 0;
  display: grid;
  gap: 14px;
}

/* === 品牌标题 === */
.brand-title {
  margin: 0;
  font-size: clamp(34px, 4.2vw, 46px);
  font-weight: 800;
  letter-spacing: 0.08em;
  color: var(--law-primary);
  line-height: 1.1;
}

.brand-sub {
  margin: 0;
  font-size: 15px;
  color: var(--law-muted);
  letter-spacing: 0.03em;
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}

.brand-tag {
  display: inline-flex;
  padding: 4px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  color: var(--law-gold-strong);
  background: var(--law-gold-soft);
  letter-spacing: 0.12em;
}

/* === 核心能力 === */
.capability-block {
  margin-top: 6px;
  padding-top: 18px;
  border-top: 1px dashed var(--law-border-soft);
}

.capability-block h2 {
  margin: 0 0 8px;
  font-size: 17px;
  font-weight: 700;
  color: var(--law-text);
  letter-spacing: 0.04em;
}

.capability-block p {
  margin: 0;
  color: var(--law-muted);
  font-size: 14px;
  line-height: 1.85;
}

/* === 能力亮点列表 === */
.feature-list {
  display: grid;
  gap: 10px;
  padding: 0;
  margin: 0;
  list-style: none;
}

.feature-list li {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr);
  gap: 12px;
  align-items: baseline;
  padding: 8px 0;
  border-bottom: 1px dashed var(--law-border-soft);
}

.feature-list li:last-child {
  border-bottom: 0;
}

.feature-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--law-primary);
  letter-spacing: 0.04em;
}

.feature-desc {
  font-size: 13px;
  color: var(--law-muted);
  line-height: 1.7;
}

/* === 页脚声明 === */
.welcome-footer {
  margin: 8px 0 0;
  font-size: 11px;
  color: var(--law-faint);
  letter-spacing: 0.06em;
}

/* === 右侧卡片 === */
.assistant-card {
  min-width: 0;
  display: grid;
  align-content: start;
  gap: 14px;
  padding: 22px;
  border: 1px solid var(--law-border-soft);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.78);
  box-shadow: 0 12px 30px rgba(15, 38, 68, 0.06);
  align-self: start;
}

.assistant-orbit {
  width: 58px;
  height: 58px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  color: #ffffff;
  background: linear-gradient(135deg, #2c5282 0%, #1e3a5f 100%);
  box-shadow:
    0 18px 32px rgba(30, 58, 95, 0.26),
    inset 0 1px 0 rgba(201, 169, 110, 0.22);
}

.assistant-card strong {
  display: block;
  margin-bottom: 6px;
  font-size: 15px;
}

.assistant-card span {
  color: var(--law-muted);
  font-size: 13px;
  line-height: 1.6;
}

.welcome-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 6px;
}

@media (max-width: 1180px) {
  .welcome-panel {
    grid-template-columns: 1fr;
  }
}
</style>
