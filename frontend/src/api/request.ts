// Axios 请求封装，负责统一 baseURL、Token 注入、响应解包与 401 跳转登录。
import axios, { type AxiosInstance, type AxiosRequestConfig, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'

import { clearStorage, getToken } from '@/utils/auth-token'

interface ApiResponse<T> {
  code: number
  message: string
  data: T
}

// 单例 Axios 实例，所有业务接口复用同一份拦截器配置。
const request: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 10000,
})

// 请求拦截器：自动附加 Bearer 令牌，避免每个调用方重复处理。
request.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = getToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器：统一解包 ApiResponse，业务层只需关心 data 字段。
request.interceptors.response.use(
  (response: AxiosResponse<ApiResponse<unknown>>) => {
    const body = response.data
    // 后端约定的业务失败（例如校验错误、参数异常），抛出后由调用方捕获。
    if (body && typeof body.code === 'number' && body.code !== 0) {
      const error = new Error(body.message || '请求失败')
      ;(error as Error & { code?: number }).code = body.code
      return Promise.reject(error)
    }
    return response
  },
  async (error) => {
    const status = error?.response?.status
    // 令牌过期或被吊销时清理本地凭据并跳转登录，避免后续请求继续 401。
    if (status === 401) {
      const wasAuthenticated = Boolean(getToken())
      clearStorage()
      if (wasAuthenticated && location.pathname !== '/login') {
        // 使用 location 跳转以重置 Pinia 与 Router 内部状态，避免脏数据残留。
        location.assign(`/login?redirect=${encodeURIComponent(location.pathname + location.search)}`)
      }
    }
    // 统一将后端 ApiResponse 形状的错误信息透传给业务层。
    const message = error?.response?.data?.message || error?.message || '网络异常，请稍后重试'
    return Promise.reject(new Error(message))
  },
)

// GET 请求便捷方法，直接返回 ApiResponse.data，简化业务调用。
export async function httpGet<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
  const response = await request.get<ApiResponse<T>>(url, config)
  return response.data.data
}

// POST 请求便捷方法，常用于登录、注册、创建资源等。
export async function httpPost<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
  const response = await request.post<ApiResponse<T>>(url, data, config)
  return response.data.data
}

// PUT 请求便捷方法，用于更新操作。
export async function httpPut<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
  const response = await request.put<ApiResponse<T>>(url, data, config)
  return response.data.data
}

// DELETE 请求便捷方法。
export async function httpDelete<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
  const response = await request.delete<ApiResponse<T>>(url, config)
  return response.data.data
}

export { request }
