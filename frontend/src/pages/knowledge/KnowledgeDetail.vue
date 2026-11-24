<!--
  本文件是知识库详情与文档管理页:
  - 展示知识库基本信息(类型、名称、描述、配置)与其下文档清单
  - 文档清单支持查看原文、重解析与单篇删除
-->
<template>
  <div class="kb-detail-page">
    <!-- 顶部返回与面包屑 -->
    <nav class="detail-crumb">
      <el-button
        link
        :icon="ArrowLeft"
        @click="goBack"
      >
        返回知识库
      </el-button>
      <span class="crumb-sep">/</span>
      <span class="crumb-current">{{ kb?.name ?? '加载中' }}</span>
    </nav>

    <!-- 加载骨架 / 错误 / 主体 -->
    <div
      v-if="loading && !kb"
      class="state-panel"
      v-loading="true"
      element-loading-text="加载知识库中"
    />

    <section
      v-else-if="error && !kb"
      class="state-panel"
    >
      <el-result
        icon="error"
        title="知识库加载失败"
        :sub-title="error"
      >
        <template #extra>
          <el-button
            type="primary"
            @click="loadKB"
          >
            重新加载
          </el-button>
        </template>
      </el-result>
    </section>

    <template v-else-if="kb">
      <!-- 知识库信息头:类型徽章、名称、描述、配置摘要(只读) -->
      <header class="detail-hero">
        <div class="hero-main">
          <div
            class="hero-badge"
            :style="{ color: meta.color, background: meta.soft }"
          >
            <component
              :is="meta.icon"
              :size="26"
            />
          </div>
          <div class="hero-text">
            <div class="hero-title-row">
              <h1>{{ kb.name }}</h1>
              <span
                class="status-tag"
                :class="kb.status"
              >
                <i class="tag-dot" />
                {{ kbStatusMeta[kb.status].label }}
              </span>
            </div>
            <div class="hero-meta">
              <span class="meta-type">
                <component
                  :is="meta.icon"
                  :size="13"
                />
                {{ meta.label }}
              </span>
              <span class="meta-sep">·</span>
              <span>{{ kb.embedding_model || '未配置向量模型' }}</span>
              <span class="meta-sep">·</span>
              <span>分块 {{ kb.chunk_size }} / 重叠 {{ kb.chunk_overlap }}</span>
            </div>
            <p class="hero-desc">
              {{ kb.description || '该知识库尚未填写描述。' }}
            </p>
          </div>
        </div>
      </header>

      <!-- 文档列表:由 DocumentTable 组件自管理分页与筛选查询 -->
      <DocumentTable
        :kb-id="kb.id"
        @documents-changed="loadKB"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from 'lucide-vue-next'

import { getKnowledgeBase } from '@/api/kb'
import DocumentTable from './components/DocumentTable.vue'
import { getKBTypeMeta, kbStatusMeta } from './kb-meta'
import type { KnowledgeBase } from '@/types/kb'

const route = useRoute()
const router = useRouter()

const kb = ref<KnowledgeBase | null>(null)
const loading = ref(true)
const error = ref('')

const kbId = computed(() => Number(route.params.id))
const meta = computed(() => (kb.value ? getKBTypeMeta(kb.value.kb_type) : getKBTypeMeta('law')))

function goBack() {
  router.push('/knowledge')
}

async function loadKB() {
  error.value = ''
  loading.value = true
  try {
    kb.value = await getKnowledgeBase(kbId.value)
  } catch (currentError) {
    error.value = currentError instanceof Error ? currentError.message : '未知错误'
  } finally {
    loading.value = false
  }
}

onMounted(loadKB)
</script>

<style scoped>
.kb-detail-page {
  display: grid;
  gap: 18px;
}

.detail-crumb {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--law-muted);
  font-size: 13px;
}

.crumb-current {
  color: var(--law-text);
  font-weight: 600;
}

.crumb-sep {
  color: #cbd5e1;
}

/* 信息头:左侧徽章+文案(只读) */
.detail-hero {
  display: grid;
  gap: 20px;
  align-items: center;
  padding: 24px;
  border: 1px solid var(--law-border);
  border-radius: 18px;
  background:
    linear-gradient(125deg, rgb(37 99 235 / 8%), transparent 50%),
    var(--law-card);
  box-shadow: var(--law-shadow);
}

.hero-main {
  display: flex;
  align-items: flex-start;
  gap: 18px;
  min-width: 0;
}

.hero-badge {
  width: 60px;
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 16px;
  flex-shrink: 0;
}

.hero-text {
  min-width: 0;
}

.hero-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.hero-title-row h1 {
  margin: 0;
  font-size: 24px;
  font-weight: 800;
  line-height: 1.2;
  color: var(--law-text);
}

.status-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
}

.status-tag .tag-dot {
  width: 6px;
  height: 6px;
  border-radius: 999px;
}

.status-tag.enabled {
  color: #15803d;
  background: #dcfce7;
}

.status-tag.enabled .tag-dot {
  background: #22c55e;
}

.status-tag.disabled {
  color: #475569;
  background: #e2e8f0;
}

.status-tag.disabled .tag-dot {
  background: #94a3b8;
}

.hero-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
  color: var(--law-muted);
  font-size: 13px;
}

.meta-type {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-weight: 600;
  color: var(--law-text);
}

.meta-sep {
  color: #cbd5e1;
}

.hero-desc {
  margin: 10px 0 0;
  max-width: 720px;
  color: var(--law-muted);
  font-size: 13px;
  line-height: 1.7;
}

.state-panel {
  min-height: 360px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--law-border);
  border-radius: 16px;
  background: var(--law-card);
  box-shadow: var(--law-shadow);
}

@media (max-width: 760px) {
  .hero-main {
    flex-direction: column;
  }
}
</style>
