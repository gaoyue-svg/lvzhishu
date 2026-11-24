// 访问令牌的轻量存储与内存缓存，供请求拦截器与 Pinia 共享，避免循环依赖。
// 与 stores/auth.ts 分离：本模块不依赖 Pinia，可被 request.ts 安全引入。

const STORAGE_KEY = 'lawrag.auth'

// 持久化结构：仅保存令牌相关字段，用户资料每次进入应用时从后端拉取。
export interface AuthStorage {
  access_token: string
  refresh_token: string
  expires_at: number
  username_hint: string
}

// 内存缓存：供同步读取，避免请求拦截器每次都访问 localStorage。
let cachedToken: string | null = readStorage()?.access_token ?? null

/** 从本地存储读取凭据，未登录时返回 null。 */
export function readStorage(): AuthStorage | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY) || sessionStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as AuthStorage) : null
  } catch {
    return null
  }
}

/** 写入凭据到指定存储，remember=false 时使用 sessionStorage。 */
export function writeStorage(data: AuthStorage, remember: boolean) {
  const raw = JSON.stringify(data)
  // 切换存储类型时清除另一边的旧值，避免凭据残留。
  localStorage.removeItem(STORAGE_KEY)
  sessionStorage.removeItem(STORAGE_KEY)
  const target = remember ? localStorage : sessionStorage
  target.setItem(STORAGE_KEY, raw)
  cachedToken = data.access_token
}

/** 清空两个存储位置的凭据并重置内存缓存。 */
export function clearStorage() {
  localStorage.removeItem(STORAGE_KEY)
  sessionStorage.removeItem(STORAGE_KEY)
  cachedToken = null
}

/** 同步读取当前访问令牌（请求拦截器使用）。 */
export function getToken(): string | null {
  return cachedToken
}

/** 供 stores/auth.ts 在登录后同步更新内存缓存。 */
export function setToken(token: string | null) {
  cachedToken = token
}

export { STORAGE_KEY }
