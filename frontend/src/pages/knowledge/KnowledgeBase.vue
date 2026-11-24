<!--
  本文件是知识库列表页:
  - 展示当前用户的知识库列表,点击卡片进入详情查看文档
  - 支持新建知识库并选择内容类型,其余沿用后端默认配置
-->
<template>
  <div class="kb-page">
    <!-- 页头:标题与说明 -->
    <header class="kb-hero">
      <div class="hero-copy">
        <span class="hero-eyebrow">
          <FolderOpen :size="14" />
          知识资产管理
        </span>
        <h1>知识中心</h1>
        <p>查看当前用户下的法律法规、案例判例、合同范本等可检索语料库及其文档清单。</p>
      </div>
      <div class="hero-actions">
        <el-button
          type="primary"
          :icon="Plus"
          @click="openCreateDialog"
        >
          新建知识库
        </el-button>
        <el-button
          :icon="RefreshCw"
          @click="loadList"
        >
          刷新
        </el-button>
      </div>
    </header>

    <!-- 新建知识库弹窗:名称与类型必填,其余使用后端默认 -->
    <el-dialog
      v-model="createDialogVisible"
      title="新建知识库"
      width="440px"
      :close-on-click-modal="false"
      append-to-body
    >
      <el-form
        ref="createFormRef"
        :model="createForm"
        :rules="createRules"
        label-position="top"
        @submit.prevent
      >
        <el-form-item
          label="知识库名称"
          prop="name"
        >
          <el-input
            v-model="createForm.name"
            placeholder="请输入知识库名称"
            maxlength="100"
            show-word-limit
            clearable
            @keydown.enter.prevent="submitCreate"
          />
        </el-form-item>
        <el-form-item
          label="知识库类型"
          prop="kbType"
        >
          <el-select
            v-model="createForm.kbType"
            placeholder="请选择知识库类型"
            class="type-select"
          >
            <el-option
              v-for="item in kbTypeMetaList"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            >
              <div class="type-option">
                <component
                  :is="item.icon"
                  :size="15"
                  :style="{ color: item.color }"
                />
                <span>{{ item.label }}</span>
                <small>{{ item.description }}</small>
              </div>
            </el-option>
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">
          取消
        </el-button>
        <el-button
          type="primary"
          :loading="creating"
          @click="submitCreate"
        >
          创建
        </el-button>
      </template>
    </el-dialog>

    <!-- 重命名弹窗:仅修改名称,预填当前名称 -->
    <el-dialog
      v-model="renameDialogVisible"
      title="重命名知识库"
      width="440px"
      :close-on-click-modal="false"
      append-to-body
    >
      <el-form
        ref="renameFormRef"
        :model="renameForm"
        :rules="renameRules"
        label-position="top"
        @submit.prevent
      >
        <el-form-item
          label="知识库名称"
          prop="name"
        >
          <el-input
            v-model="renameForm.name"
            placeholder="请输入新的知识库名称"
            maxlength="100"
            show-word-limit
            clearable
            @keydown.enter.prevent="submitRename"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="renameDialogVisible = false">
          取消
        </el-button>
        <el-button
          type="primary"
          :loading="renaming"
          @click="submitRename"
        >
          保存
        </el-button>
      </template>
    </el-dialog>

    <!-- 主体:加载骨架 / 错误 / 空态 / 卡片网格 -->
    <div
      v-loading="loading"
      class="kb-content"
    >
      <section
        v-if="error && !loading"
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
              @click="loadList"
            >
              重新加载
            </el-button>
          </template>
        </el-result>
      </section>

      <section
        v-else-if="!loading && list.length === 0"
        class="state-panel"
      >
        <el-empty description="还没有知识库" />
      </section>

      <section
        v-else
        class="kb-grid"
      >
        <KnowledgeCard
          v-for="kb in list"
          :key="kb.id"
          :kb="kb"
          @delete="handleDelete"
          @rename="openRenameDialog"
        />
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { FolderOpen, Plus, RefreshCw } from 'lucide-vue-next'

import {
  createKnowledgeBase,
  deleteKnowledgeBase,
  listKnowledgeBases,
  updateKnowledgeBase,
} from '@/api/kb'
import KnowledgeCard from './components/KnowledgeCard.vue'
import { kbTypeMetaList } from './kb-meta'
import type { KBType, KnowledgeBase } from '@/types/kb'

const list = ref<KnowledgeBase[]>([])
const loading = ref(true)
const error = ref('')

// 新建知识库弹窗状态:收集名称与内容类型,避免所有知识库被错误归为 law。
const createDialogVisible = ref(false)
const creating = ref(false)
const createFormRef = ref<FormInstance>()
const createForm = reactive<{ name: string; kbType: KBType }>({ name: '', kbType: 'law' })
const createRules: FormRules = {
  name: [
    { required: true, message: '请输入知识库名称', trigger: 'blur' },
    { min: 1, max: 100, message: '长度需在 1-100 之间', trigger: 'blur' },
  ],
  kbType: [{ required: true, message: '请选择知识库类型', trigger: 'change' }],
}

// 重命名弹窗状态:记录当前编辑的知识库,并预填当前名称。
const renameDialogVisible = ref(false)
const renaming = ref(false)
const renameFormRef = ref<FormInstance>()
const renamingKb = ref<KnowledgeBase | null>(null)
const renameForm = reactive({ name: '' })
const renameRules: FormRules = {
  name: [
    { required: true, message: '请输入知识库名称', trigger: 'blur' },
    { min: 1, max: 100, message: '长度需在 1-100 之间', trigger: 'blur' },
  ],
}

function openCreateDialog() {
  createForm.name = ''
  createForm.kbType = 'law'
  createDialogVisible.value = true
}

async function submitCreate() {
  const valid = await createFormRef.value?.validate().catch(() => false)
  if (!valid) return
  creating.value = true
  try {
    await createKnowledgeBase({
      name: createForm.name.trim(),
      kb_type: createForm.kbType,
      embedding_model: 'bge-large-zh-v1.5',
      chunk_size: 500,
      chunk_overlap: 50,
    })
    ElMessage.success('知识库已创建')
    createDialogVisible.value = false
    await loadList()
  } catch (currentError) {
    ElMessage.error(currentError instanceof Error ? currentError.message : '创建失败')
  } finally {
    creating.value = false
  }
}

function openRenameDialog(kb: KnowledgeBase) {
  // 预填当前名称,便于用户在原名称基础上修改。
  renamingKb.value = kb
  renameForm.name = kb.name
  renameDialogVisible.value = true
}

async function submitRename() {
  // 仅传 name,后端按 exclude_unset 只更新名称,其余配置不受影响。
  if (!renamingKb.value) return
  const valid = await renameFormRef.value?.validate().catch(() => false)
  if (!valid) return
  renaming.value = true
  try {
    await updateKnowledgeBase(renamingKb.value.id, { name: renameForm.name.trim() })
    ElMessage.success('知识库名称已更新')
    renameDialogVisible.value = false
    await loadList()
  } catch (currentError) {
    ElMessage.error(currentError instanceof Error ? currentError.message : '更新失败')
  } finally {
    renaming.value = false
  }
}

async function handleDelete(kb: KnowledgeBase) {
  // 二次确认:删除会清理数据库与 Milvus 向量,不可恢复。
  try {
    await ElMessageBox.confirm(
      `确定删除知识库「${kb.name}」吗?将同步删除其下所有文档、Chunk 与 Milvus 向量数据,且不可恢复。`,
      '删除知识库',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
      },
    )
  } catch {
    // 用户取消,不做任何处理。
    return
  }
  try {
    await deleteKnowledgeBase(kb.id)
    ElMessage.success('知识库已删除')
    await loadList()
  } catch (currentError) {
    ElMessage.error(currentError instanceof Error ? currentError.message : '删除失败')
  }
}

async function loadList() {
  error.value = ''
  loading.value = true
  try {
    list.value = await listKnowledgeBases()
  } catch (currentError) {
    error.value = currentError instanceof Error ? currentError.message : '未知错误'
  } finally {
    loading.value = false
  }
}

onMounted(loadList)
</script>

<style scoped>
.kb-page {
  display: grid;
  gap: 20px;
}

.type-select {
  width: 100%;
}

.type-option {
  display: grid;
  grid-template-columns: 18px auto minmax(0, 1fr);
  gap: 7px;
  align-items: center;
}

.type-option small {
  overflow: hidden;
  color: var(--law-muted);
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 页头:左侧文案 + 右侧刷新,带渐变氛围背景 */
.kb-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  padding: 24px 26px;
  border: 1px solid rgba(0, 0, 0, 0.06);
  border-radius: 20px;
  background: var(--law-card);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

::global(html.dark) .kb-hero {
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

.kb-hero h1 {
  margin: 8px 0 8px;
  font-size: 28px;
  font-weight: 800;
  line-height: 1.2;
}

.kb-hero p {
  max-width: 640px;
  margin: 0;
  color: var(--law-muted);
  font-size: 14px;
  line-height: 1.7;
}

.hero-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.kb-content {
  min-height: 240px;
}

.kb-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
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

@media (max-width: 960px) {
  .kb-hero {
    flex-direction: column;
  }

  .hero-actions {
    width: 100%;
    justify-content: flex-end;
  }
}
</style>
