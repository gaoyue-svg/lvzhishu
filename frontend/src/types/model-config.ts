// 本文件定义系统设置中模型动态配置相关的前端类型。

export type ModelConfigType = 'chat' | 'embedding' | 'rerank' | 'tavily'

export interface ModelProvider {
  name: string
  label: string
  config_types: ModelConfigType[]
  default_api_base: string
  popular_models: string[]
  default_dimension: number | null
  requires_api_key: boolean
}

export interface ModelConfig {
  id: number
  config_type: ModelConfigType
  provider: string
  model_name: string
  api_base: string
  api_key_masked: string
  has_api_key: boolean
  is_active: boolean
  temperature: number | null
  max_tokens: number | null
  timeout: number | null
  retry: number | null
  dimension: number | null
}

export interface SaveModelConfigPayload {
  config_type: ModelConfigType
  provider: string
  model_name: string
  api_base: string
  api_key?: string | null
  is_active: boolean
  temperature?: number | null
  max_tokens?: number | null
  timeout?: number | null
  retry?: number | null
  dimension?: number | null
}

export interface TestModelConfigPayload {
  config_type: ModelConfigType
  provider?: string | null
  model_name?: string | null
  api_base?: string | null
  api_key?: string | null
  dimension?: number | null
}

export interface TestModelConfigResult {
  success: boolean
  message: string
  latency_ms: number
}
