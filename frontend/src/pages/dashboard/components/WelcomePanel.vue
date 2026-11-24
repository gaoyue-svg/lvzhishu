<!-- 欢迎面板组件，展示首页主行动入口和平台状态摘要。 -->
<template>
  <section class="welcome-panel">
    <div class="welcome-copy">
      <span class="date-text">{{ currentDate }}</span>
      <h1>欢迎回来，{{ userName }}</h1>
      <p>今天已有 18 个法律问题通过引用溯源完成答复，知识库与法规索引保持在线。</p>
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
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { MessageCircle, Sparkles, UploadCloud } from 'lucide-vue-next'

defineProps<{
  userName: string
}>()

const router = useRouter()
const currentDate = computed(() =>
  new Intl.DateTimeFormat('zh-CN', {
    month: 'long',
    day: 'numeric',
    weekday: 'long',
  }).format(new Date()),
)

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
}

.date-text {
  display: inline-flex;
  padding: 6px 11px;
  border-radius: 999px;
  color: var(--law-primary-strong);
  background: var(--law-primary-soft);
  font-size: 12px;
  font-weight: 700;
  line-height: 1.4;
}

.welcome-copy h1 {
  margin: 15px 0 10px;
  font-size: clamp(26px, 3vw, 38px);
  font-weight: 800;
  line-height: 1.15;
}

.welcome-copy p {
  max-width: 640px;
  margin: 0;
  color: var(--law-muted);
  font-size: 15px;
  line-height: 1.8;
}

.welcome-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 22px;
}

.assistant-card {
  min-width: 0;
  display: grid;
  align-content: center;
  gap: 16px;
  padding: 22px;
  border: 1px solid var(--law-border-soft);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.78);
  box-shadow: 0 12px 30px rgba(15, 38, 68, 0.06);
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

@media (max-width: 1180px) {
  .welcome-panel {
    grid-template-columns: 1fr;
  }
}
</style>
