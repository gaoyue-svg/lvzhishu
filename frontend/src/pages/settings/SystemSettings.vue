<!-- 本文件实现系统设置页，用于管理大模型、Embedding 与 Rerank 的动态后端配置。 -->
<template>
  <div class="settings-page">
    <header class="settings-header">
      <div>
        <h1>系统设置</h1>
        <p>模型配置会保存到后端，运行时按当前用户动态生效。</p>
      </div>
      <el-button
        :icon="RotateCw"
        :loading="loading"
        @click="loadSettings"
      >
        刷新
      </el-button>
    </header>

    <el-alert
      v-if="loadError"
      class="settings-alert"
      :closable="false"
      type="error"
      :title="loadError"
      show-icon
    />

    <section
      v-loading="loading"
      class="settings-grid"
    >
      <article
        v-for="item in configCards"
        :key="item.type"
        class="config-card"
      >
        <div class="card-heading">
          <span class="card-icon">
            <component
              :is="item.icon"
              :size="20"
            />
          </span>
          <div>
            <h2>{{ item.title }}</h2>
            <p>{{ item.subtitle }}</p>
          </div>
          <el-switch
            v-model="forms[item.type].is_active"
            class="card-switch"
            active-text="启用"
            inactive-text="停用"
          />
        </div>

        <el-form
          class="config-form"
          label-position="top"
        >
          <div class="form-row two">
            <el-form-item label="Provider">
              <el-select
                v-model="forms[item.type].provider"
                placeholder="选择 Provider"
                @change="handleProviderChange(item.type)"
              >
                <el-option
                  v-for="provider in providersFor(item.type)"
                  :key="provider.name"
                  :label="provider.label"
                  :value="provider.name"
                />
              </el-select>
            </el-form-item>

            <el-form-item label="模型">
              <el-input
                v-model="forms[item.type].model_name"
                clearable
                placeholder="请输入模型名称"
              />
            </el-form-item>
          </div>

          <el-form-item label="API Base">
            <el-input
              v-model="forms[item.type].api_base"
              clearable
              placeholder="为空时使用 Provider 默认地址"
            />
          </el-form-item>

          <el-form-item
            v-if="forms[item.type].provider !== 'rule'"
            label="API Key"
          >
            <el-input
              v-model="forms[item.type].api_key"
              type="password"
              show-password
              clearable
              placeholder="留空则保留已保存密钥"
            >
              <template #prefix>
                <KeyRound :size="16" />
              </template>
            </el-input>
            <div class="key-state">
              <CheckCircle2
                v-if="forms[item.type].has_saved_key"
                :size="14"
              />
              <span>{{ keyStateText(item.type) }}</span>
            </div>
          </el-form-item>

          <div
            v-if="item.type === 'chat'"
            class="form-row two"
          >
            <el-form-item label="温度">
              <el-input-number
                v-model="forms.chat.temperature"
                :min="0"
                :max="2"
                :step="0.1"
                controls-position="right"
              />
            </el-form-item>
            <el-form-item label="最大 Token">
              <el-input-number
                v-model="forms.chat.max_tokens"
                :min="1"
                :step="256"
                controls-position="right"
              />
            </el-form-item>
          </div>

          <div class="form-row three">
            <el-form-item
              v-if="item.type === 'embedding'"
              label="向量维度"
            >
              <el-input-number
                v-model="forms.embedding.dimension"
                :min="1"
                :step="128"
                controls-position="right"
              />
            </el-form-item>
            <el-form-item label="超时秒数">
              <el-input-number
                v-model="forms[item.type].timeout"
                :min="1"
                :step="5"
                controls-position="right"
              />
            </el-form-item>
            <el-form-item label="重试次数">
              <el-input-number
                v-model="forms[item.type].retry"
                :min="0"
                :step="1"
                controls-position="right"
              />
            </el-form-item>
          </div>
        </el-form>

        <footer class="card-actions">
          <div
            v-if="forms[item.type].test_result"
            class="test-result"
            :class="{ success: forms[item.type].test_result?.success }"
          >
            <span>{{ forms[item.type].test_result?.message }}</span>
            <em>{{ forms[item.type].test_result?.latency_ms }} ms</em>
          </div>
          <div class="action-buttons">
            <el-button
              :icon="PlugZap"
              :loading="testing[item.type]"
              @click="handleTest(item.type)"
            >
              测试
            </el-button>
            <el-button
              :icon="Trash2"
              :loading="deleting[item.type]"
              @click="handleDelete(item.type)"
            />
            <el-button
              type="primary"
              :icon="Save"
              :loading="saving[item.type]"
              @click="handleSave(item.type)"
            >
              保存
            </el-button>
          </div>
        </footer>
      </article>
    </section>

    <!-- Tavily 联网搜索 API Key 配置: 仅需填写一个 API Key, 供案例分析 Agent 调用网络来源。 -->
    <section
      v-loading="loading"
      class="tool-section"
    >
      <article class="config-card tool-card">
        <div class="card-heading">
          <span class="card-icon tavily-icon">
            <Globe :size="20" />
          </span>
          <div>
            <h2>Tavily 联网搜索</h2>
            <p>案例分析 Agent 联网检索的网络来源，仅需填写一个 API Key。</p>
          </div>
          <el-switch
            v-model="tavilyForm.is_active"
            class="card-switch"
            active-text="启用"
            inactive-text="停用"
          />
        </div>

        <el-form
          class="config-form"
          label-position="top"
        >
          <el-form-item label="API Key">
            <el-input
              v-model="tavilyForm.api_key"
              type="password"
              show-password
              clearable
              placeholder="留空则保留已保存密钥"
            >
              <template #prefix>
                <KeyRound :size="16" />
              </template>
            </el-input>
            <div class="key-state">
              <CheckCircle2
                v-if="tavilyForm.has_saved_key"
                :size="14"
              />
              <span>{{ tavilyKeyStateText }}</span>
            </div>
          </el-form-item>
        </el-form>

        <footer class="card-actions">
          <div
            v-if="tavilyForm.test_result"
            class="test-result"
            :class="{ success: tavilyForm.test_result?.success }"
          >
            <span>{{ tavilyForm.test_result?.message }}</span>
            <em>{{ tavilyForm.test_result?.latency_ms }} ms</em>
          </div>
          <div class="action-buttons">
            <el-button
              :icon="PlugZap"
              :loading="tavilyTesting"
              @click="handleTavilyTest"
            >
              测试
            </el-button>
            <el-button
              :icon="Trash2"
              :loading="tavilyDeleting"
              @click="handleTavilyDelete"
            />
            <el-button
              type="primary"
              :icon="Save"
              :loading="tavilySaving"
              @click="handleTavilySave"
            >
              保存
            </el-button>
          </div>
        </footer>
      </article>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  BrainCircuit,
  CheckCircle2,
  GitBranch,
  Globe,
  KeyRound,
  PlugZap,
  RotateCw,
  Save,
  Trash2,
  Workflow,
} from 'lucide-vue-next'
import type { Component } from 'vue'

import {
  deleteModelConfig,
  listModelConfigs,
  listModelProviders,
  saveModelConfig,
  testModelConfig,
} from '@/api/llm-config'
import type {
  ModelConfig,
  ModelConfigType,
  ModelProvider,
  SaveModelConfigPayload,
  TestModelConfigPayload,
  TestModelConfigResult,
} from '@/types/model-config'

interface ConfigCard {
  type: ModelConfigType
  title: string
  subtitle: string
  icon: Component
}

interface ModelConfigForm {
  id: number | null
  provider: string
  model_name: string
  api_base: string
  api_key: string
  api_key_masked: string
  has_saved_key: boolean
  is_active: boolean
  temperature: number | null
  max_tokens: number | null
  timeout: number | null
  retry: number | null
  dimension: number | null
  test_result: TestModelConfigResult | null
}

const configCards: ConfigCard[] = [
  {
    type: 'chat',
    title: '大模型',
    subtitle: '业务 Agent 的推理、问答和文书生成模型',
    icon: BrainCircuit,
  },
  {
    type: 'embedding',
    title: 'Embedding 模型',
    subtitle: '文档入库和语义检索共用的向量模型',
    icon: Workflow,
  },
  {
    type: 'rerank',
    title: 'Rerank 模型',
    subtitle: '混合检索后的结果重排模型',
    icon: GitBranch,
  },
]

const loading = ref(false)
const loadError = ref('')
const providers = ref<ModelProvider[]>([])

const forms = reactive<Record<ModelConfigType, ModelConfigForm>>({
  chat: createDefaultForm('chat'),
  embedding: createDefaultForm('embedding'),
  rerank: createDefaultForm('rerank'),
  tavily: createDefaultForm('tavily'),
})

const saving = reactive<Record<ModelConfigType, boolean>>({
  chat: false,
  embedding: false,
  rerank: false,
  tavily: false,
})

const testing = reactive<Record<ModelConfigType, boolean>>({
  chat: false,
  embedding: false,
  rerank: false,
  tavily: false,
})

const deleting = reactive<Record<ModelConfigType, boolean>>({
  chat: false,
  embedding: false,
  rerank: false,
  tavily: false,
})

const providerMap = computed(() => {
  const map = new Map<string, ModelProvider>()
  providers.value.forEach((provider) => map.set(provider.name, provider))
  return map
})

function createDefaultForm(type: ModelConfigType): ModelConfigForm {
  const defaults = {
    chat: { provider: 'deepseek', model: '', dimension: null },
    embedding: { provider: 'openai', model: '', dimension: 1536 },
    rerank: { provider: 'rule', model: '', dimension: null },
    // Tavily 占位: 实际 Tavily 配置由独立的 tavilyForm 管理, 此处仅为满足 Record 类型。
    tavily: { provider: 'tavily', model: 'tavily-search', dimension: null },
  }[type]
  return {
    id: null,
    provider: defaults.provider,
    model_name: defaults.model,
    api_base: '',
    api_key: '',
    api_key_masked: '',
    has_saved_key: false,
    is_active: true,
    temperature: type === 'chat' ? 0.3 : null,
    max_tokens: type === 'chat' ? 4096 : null,
    timeout: type === 'rerank' ? 30 : 60,
    retry: type === 'chat' ? 2 : 1,
    dimension: defaults.dimension,
    test_result: null,
  }
}

function providersFor(type: ModelConfigType): ModelProvider[] {
  return providers.value.filter((provider) => provider.config_types.includes(type))
}

function selectedProvider(type: ModelConfigType): ModelProvider | undefined {
  return providerMap.value.get(forms[type].provider)
}

function keyStateText(type: ModelConfigType): string {
  const form = forms[type]
  if (form.api_key) {
    return '将更新密钥'
  }
  if (form.has_saved_key) {
    return `已保存 ${form.api_key_masked}`
  }
  return '未保存密钥'
}

function requiresApiKey(type: ModelConfigType): boolean {
  return Boolean(selectedProvider(type)?.requires_api_key)
}

function handleProviderChange(type: ModelConfigType) {
  const form = forms[type]
  const provider = selectedProvider(type)
  if (!provider) {
    return
  }
  form.api_base = provider.default_api_base
  if (type === 'embedding') {
    form.dimension = provider.default_dimension ?? form.dimension
  }
  if (provider.name === 'rule') {
    form.api_key = ''
    form.api_base = ''
  }
  form.test_result = null
}

async function loadSettings() {
  loading.value = true
  loadError.value = ''
  try {
    const [providerData, configData] = await Promise.all([listModelProviders(), listModelConfigs()])
    providers.value = providerData
    resetDefaultsFromProviders()
    configData.forEach(applyConfig)
    // Tavily 配置复用 user_llm_config, 从同一份配置列表中提取。
    applyTavilyFromConfigs(configData)
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : '系统设置加载失败'
  } finally {
    loading.value = false
  }
}

function resetDefaultsFromProviders() {
  configCards.forEach((item) => {
    applyDefaultForType(item.type)
  })
}

function applyDefaultForType(type: ModelConfigType) {
  const provider = providersFor(type)[0]
  if (!provider) {
    return
  }
  const form = forms[type]
  form.provider = provider.name
  form.api_base = provider.default_api_base
  if (type === 'embedding') {
    form.dimension = provider.default_dimension ?? form.dimension
  }
}

function applyConfig(config: ModelConfig) {
  // Tavily 由 applyTavilyFromConfigs 单独写入 tavilyForm, 不走 forms, 避免数据冗余。
  if (config.config_type === 'tavily') {
    return
  }
  const form = forms[config.config_type]
  form.id = config.id
  form.provider = config.provider
  form.model_name = config.model_name
  form.api_base = config.api_base
  form.api_key = ''
  form.api_key_masked = config.api_key_masked
  form.has_saved_key = config.has_api_key
  form.is_active = config.is_active
  form.temperature = config.temperature
  form.max_tokens = config.max_tokens
  form.timeout = config.timeout
  form.retry = config.retry
  form.dimension = config.dimension
  form.test_result = null
}

function buildSavePayload(type: ModelConfigType): SaveModelConfigPayload {
  const form = forms[type]
  return {
    config_type: type,
    provider: form.provider,
    model_name: form.model_name,
    api_base: form.api_base,
    api_key: form.api_key || null,
    is_active: form.is_active,
    temperature: type === 'chat' ? form.temperature : null,
    max_tokens: type === 'chat' ? form.max_tokens : null,
    timeout: form.timeout,
    retry: form.retry,
    dimension: type === 'embedding' ? form.dimension : null,
  }
}

async function handleSave(type: ModelConfigType) {
  const form = forms[type]
  if (!form.provider || !form.model_name) {
    ElMessage.warning('请先选择 Provider 和模型')
    return
  }
  if (!form.api_key && !form.has_saved_key && requiresApiKey(type) && form.is_active) {
    ElMessage.warning('请填写 API Key')
    return
  }
  saving[type] = true
  try {
    const saved = await saveModelConfig(type, buildSavePayload(type))
    applyConfig(saved)
    ElMessage.success('配置已保存')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存失败')
  } finally {
    saving[type] = false
  }
}

async function handleTest(type: ModelConfigType) {
  const form = forms[type]
  testing[type] = true
  try {
    const payload = {
      config_type: type,
      provider: form.provider,
      model_name: form.model_name,
      api_base: form.api_base,
      api_key: form.api_key || null,
      dimension: type === 'embedding' ? form.dimension : null,
    }
    form.test_result = await testModelConfig(payload)
  } catch (error) {
    form.test_result = {
      success: false,
      message: error instanceof Error ? error.message : '测试失败',
      latency_ms: 0,
    }
  } finally {
    testing[type] = false
  }
}

async function handleDelete(type: ModelConfigType) {
  const form = forms[type]
  if (!form.id) {
    ElMessage.info('当前类型还没有保存配置')
    return
  }
  try {
    await ElMessageBox.confirm('删除后会回退到系统兜底配置。', '删除模型配置', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  deleting[type] = true
  try {
    await deleteModelConfig(type)
    forms[type] = createDefaultForm(type)
    applyDefaultForType(type)
    ElMessage.success('配置已删除')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '删除失败')
  } finally {
    deleting[type] = false
  }
}

// ===== Tavily 联网搜索 API Key 配置 (复用 user_llm_config, config_type='tavily') =====
interface TavilyForm {
  api_key: string
  api_key_masked: string
  has_saved_key: boolean
  is_active: boolean
  test_result: TestModelConfigResult | null
}

const tavilySaving = ref(false)
const tavilyTesting = ref(false)
const tavilyDeleting = ref(false)

const tavilyForm = reactive<TavilyForm>({
  api_key: '',
  api_key_masked: '',
  has_saved_key: false,
  is_active: true,
  test_result: null,
})

const tavilyKeyStateText = computed(() => {
  if (tavilyForm.api_key) {
    return '将更新密钥'
  }
  if (tavilyForm.has_saved_key) {
    return `已保存 ${tavilyForm.api_key_masked}`
  }
  return '未保存密钥'
})

function resetTavilyForm() {
  tavilyForm.api_key = ''
  tavilyForm.api_key_masked = ''
  tavilyForm.has_saved_key = false
  tavilyForm.is_active = true
  tavilyForm.test_result = null
}

// Tavily 复用 user_llm_config 表, 配置加载统一由 loadSettings 完成。
function applyTavilyFromConfigs(configs: ModelConfig[]) {
  const config = configs.find((item) => item.config_type === 'tavily') || null
  applyTavilyConfig(config)
}

function applyTavilyConfig(config: ModelConfig | null) {
  if (!config) {
    resetTavilyForm()
    return
  }
  tavilyForm.api_key = ''
  tavilyForm.api_key_masked = config.api_key_masked
  tavilyForm.has_saved_key = config.has_api_key
  tavilyForm.is_active = config.is_active
  tavilyForm.test_result = null
}

function buildTavilySavePayload(): SaveModelConfigPayload {
  // Tavily 只需要 API Key, provider/model_name/api_base 用占位值, 后端按 tavily 类型处理。
  return {
    config_type: 'tavily',
    provider: 'tavily',
    model_name: 'tavily-search',
    api_base: '',
    api_key: tavilyForm.api_key || null,
    is_active: tavilyForm.is_active,
  }
}

function buildTavilyTestPayload(): TestModelConfigPayload {
  return {
    config_type: 'tavily',
    provider: 'tavily',
    model_name: 'tavily-search',
    api_base: '',
    api_key: tavilyForm.api_key || null,
  }
}

async function handleTavilySave() {
  if (!tavilyForm.api_key && !tavilyForm.has_saved_key && tavilyForm.is_active) {
    ElMessage.warning('请填写 API Key')
    return
  }
  tavilySaving.value = true
  try {
    const saved = await saveModelConfig('tavily', buildTavilySavePayload())
    applyTavilyConfig(saved)
    ElMessage.success('Tavily 配置已保存')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存失败')
  } finally {
    tavilySaving.value = false
  }
}

async function handleTavilyTest() {
  tavilyTesting.value = true
  try {
    tavilyForm.test_result = await testModelConfig(buildTavilyTestPayload())
  } catch (error) {
    tavilyForm.test_result = {
      success: false,
      message: error instanceof Error ? error.message : '测试失败',
      latency_ms: 0,
    }
  } finally {
    tavilyTesting.value = false
  }
}

async function handleTavilyDelete() {
  if (!tavilyForm.has_saved_key) {
    ElMessage.info('尚未保存 Tavily 配置')
    return
  }
  try {
    await ElMessageBox.confirm('删除后将回退到系统兜底配置。', '删除 Tavily 配置', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  tavilyDeleting.value = true
  try {
    await deleteModelConfig('tavily')
    resetTavilyForm()
    ElMessage.success('Tavily 配置已删除')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '删除失败')
  } finally {
    tavilyDeleting.value = false
  }
}

onMounted(loadSettings)
</script>

<style scoped>
.settings-page {
  display: grid;
  gap: 18px;
}

.settings-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  padding: 24px 26px;
  border: 1px solid rgb(37 99 235 / 14%);
  border-radius: 16px;
  background:
    linear-gradient(135deg, rgb(37 99 235 / 9%), transparent 46%),
    var(--law-card);
  box-shadow: var(--law-shadow);
}

.settings-header h1 {
  margin: 0 0 8px;
  font-size: 28px;
  font-weight: 800;
  line-height: 1.2;
}

.settings-header p {
  margin: 0;
  color: var(--law-muted);
  font-size: 14px;
  line-height: 1.7;
}

.settings-alert {
  border-radius: 10px;
}

.settings-grid {
  min-height: 360px;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.config-card {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 18px;
  border: 1px solid var(--law-border);
  border-radius: 16px;
  background: var(--law-card);
  box-shadow: var(--law-shadow);
}

.card-heading {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr) auto;
  gap: 12px;
  align-items: flex-start;
}

.card-icon {
  width: 42px;
  height: 42px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  color: var(--law-primary);
  background: rgb(37 99 235 / 10%);
}

.card-heading h2 {
  margin: 0 0 6px;
  font-size: 17px;
  font-weight: 800;
  line-height: 1.25;
}

.card-heading p {
  margin: 0;
  color: var(--law-muted);
  font-size: 13px;
  line-height: 1.5;
}

.card-switch {
  margin-top: 4px;
}

.config-form {
  display: grid;
  gap: 2px;
}

.form-row {
  display: grid;
  gap: 12px;
}

.form-row.two {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.form-row.three {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.config-form :deep(.el-form-item) {
  margin-bottom: 14px;
}

.config-form :deep(.el-input-number) {
  width: 100%;
}

.key-state {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  color: var(--law-muted);
  font-size: 12px;
}

.key-state svg {
  color: #16a34a;
}

.card-actions {
  min-height: 42px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: auto;
  padding-top: 4px;
}

.action-buttons {
  display: inline-flex;
  gap: 8px;
  margin-left: auto;
}

.test-result {
  min-width: 0;
  display: grid;
  gap: 3px;
  color: #dc2626;
  font-size: 12px;
}

.test-result.success {
  color: #15803d;
}

.test-result span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.test-result em {
  color: var(--law-muted);
  font-style: normal;
}

/* Tavily 工具配置区: 视觉上与上方模型配置区分层, 卡片横跨整行, 仅一个 API Key 输入框。 */
.tool-section {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
  min-height: 0;
}

.tool-card {
  border-color: rgb(13 148 136 / 22%);
  background:
    linear-gradient(135deg, rgb(13 148 136 / 7%), transparent 52%),
    var(--law-card);
}

.tool-card .card-heading p {
  color: var(--law-muted);
}

.tavily-icon {
  color: #0d9488;
  background: rgb(13 148 136 / 12%);
}

@media (max-width: 1280px) {
  .settings-grid {
    grid-template-columns: 1fr;
  }

  .form-row.three {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .settings-header,
  .card-actions {
    flex-direction: column;
    align-items: stretch;
  }

  .settings-header {
    padding: 20px;
  }

  .card-heading {
    grid-template-columns: 38px minmax(0, 1fr);
  }

  .card-switch {
    grid-column: 1 / -1;
  }

  .form-row.two,
  .form-row.three {
    grid-template-columns: 1fr;
  }

  .action-buttons {
    width: 100%;
    justify-content: flex-end;
  }
}
</style>
