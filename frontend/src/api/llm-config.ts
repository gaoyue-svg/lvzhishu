// 本文件封装模型动态配置接口，供系统设置页管理 chat、embedding 与 rerank 配置。

import { httpDelete, httpGet, httpPost, httpPut } from './request'
import type {
  ModelConfig,
  ModelConfigType,
  ModelProvider,
  SaveModelConfigPayload,
  TestModelConfigPayload,
  TestModelConfigResult,
} from '@/types/model-config'

export function listModelConfigs(): Promise<ModelConfig[]> {
  return httpGet<ModelConfig[]>('/llm/configs')
}

export function listModelProviders(): Promise<ModelProvider[]> {
  return httpGet<ModelProvider[]>('/llm/providers')
}

export function saveModelConfig(type: ModelConfigType, payload: SaveModelConfigPayload): Promise<ModelConfig> {
  return httpPut<ModelConfig>(`/llm/config/${type}`, payload)
}

export function deleteModelConfig(type: ModelConfigType): Promise<null> {
  return httpDelete<null>(`/llm/config/${type}`)
}

export function testModelConfig(payload: TestModelConfigPayload): Promise<TestModelConfigResult> {
  return httpPost<TestModelConfigResult>('/llm/test', payload)
}
