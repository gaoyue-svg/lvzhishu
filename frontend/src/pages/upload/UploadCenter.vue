<!--
  本文件是上传中心主页面(简化版):
  - 选择目标知识库 + 拖拽上传文件
  - 文件直传后端 /api/document/upload,由后端写入阿里云 OSS 并自动入队解析与 embedding
  - 不再包含统计概览、最近上传聚合、复杂侧栏等附加功能
-->
<template>
  <div class="upload-page">
    <!-- Hero -->
    <header class="upload-hero">
      <div class="hero-copy">
        <span class="hero-eyebrow">
          <UploadCloud :size="14" />
          文档入库
        </span>
        <h1>上传中心</h1>
        <p>将法律文档上传至阿里云 OSS,系统自动完成解析与向量化索引。</p>
      </div>
    </header>

    <!-- 目标知识库选择 -->
    <section class="kb-selector">
      <label class="selector-label">
        <FolderOpen :size="15" />
        目标知识库
      </label>
      <el-select
        v-model="selectedKBId"
        placeholder="请选择目标知识库"
        class="selector-select"
        :loading="kbLoading"
        @change="onKBChange"
      >
        <el-option
          v-for="kb in kbList"
          :key="kb.id"
          :label="kb.name"
          :value="kb.id"
        >
          <template #default>
            <span class="kb-option">
              <component
                :is="getKBTypeMeta(kb.kb_type).icon"
                :size="14"
                :style="{ color: getKBTypeMeta(kb.kb_type).color }"
              />
              <span class="kb-option-name">{{ kb.name }}</span>
              <span class="kb-option-meta">{{ kb.doc_count }} 文档</span>
            </span>
          </template>
        </el-option>
      </el-select>
    </section>

    <!-- 拖拽上传区 -->
    <UploadDropzone :kb="selectedKB" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { FolderOpen, UploadCloud } from 'lucide-vue-next'

import { listKnowledgeBases } from '@/api/kb'
import { getKBTypeMeta } from '@/pages/knowledge/kb-meta'
import type { KnowledgeBase } from '@/types/kb'
import UploadDropzone from './components/UploadDropzone.vue'

const kbList = ref<KnowledgeBase[]>([])
const kbLoading = ref(true)
const selectedKBId = ref<number | null>(null)

// 当前选中的知识库对象,传给 UploadDropzone。
const selectedKB = computed(
  () => kbList.value.find((kb) => kb.id === selectedKBId.value) ?? null,
)

async function loadKBList() {
  kbLoading.value = true
  try {
    kbList.value = await listKnowledgeBases()
    // 默认选中第一个启用的知识库。
    if (kbList.value.length > 0 && selectedKBId.value === null) {
      const firstEnabled = kbList.value.find((kb) => kb.status === 'enabled')
      selectedKBId.value = firstEnabled?.id ?? kbList.value[0].id
    }
  } finally {
    kbLoading.value = false
  }
}

function onKBChange() {
  // 选择变化时 selectedKB computed 自动更新,无需额外处理。
}

onMounted(loadKBList)
</script>

<style scoped>
.upload-page {
  display: grid;
  gap: 20px;
}

/* Hero */
.upload-hero {
  padding: 24px 26px;
  border: 1px solid rgba(0, 0, 0, 0.06);
  border-radius: 20px;
  background: var(--law-card);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

:global(html.dark) .upload-hero {
  background:
    radial-gradient(circle at 0% 0%, rgb(37 99 235 / 14%), transparent 46%),
    linear-gradient(180deg, var(--law-card) 0%, var(--law-card-soft) 100%);
  border-color: var(--law-border);
  box-shadow: inset 0 1px 0 rgb(255 255 255 / 4%);
}

.hero-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--law-primary);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.upload-hero h1 {
  margin: 8px 0;
  font-size: 28px;
  font-weight: 800;
  line-height: 1.2;
  color: var(--law-text);
}

.upload-hero p {
  max-width: 680px;
  margin: 0;
  color: var(--law-muted);
  font-size: 14px;
  line-height: 1.7;
}

/* 知识库选择器 */
.kb-selector {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.selector-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--law-text);
  font-size: 14px;
  font-weight: 600;
}

.selector-select {
  width: 320px;
  max-width: 100%;
}

.kb-option {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.kb-option-name {
  font-weight: 600;
}

.kb-option-meta {
  color: var(--law-muted);
  font-size: 12px;
}

@media (max-width: 768px) {
  .selector-select {
    width: 100%;
  }
}
</style>
