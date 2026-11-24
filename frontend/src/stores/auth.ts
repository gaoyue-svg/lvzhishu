// 鉴权状态管理：维护访问令牌、当前用户资料，并提供登录、注册、登出与持久化能力。
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { fetchProfile, login as apiLogin, logout as apiLogout, register as apiRegister } from '@/api/auth'
import {
  clearStorage,
  getToken,
  readStorage,
  setToken,
  writeStorage,
} from '@/utils/auth-token'
import type { LoginPayload, RegisterPayload, UserProfile } from '@/types/auth'

export const useAuthStore = defineStore('auth', () => {
  const accessToken = ref<string | null>(getToken())
  const refreshToken = ref<string | null>(readStorage()?.refresh_token ?? null)
  const expiresAt = ref<number>(readStorage()?.expires_at ?? 0)
  const user = ref<UserProfile | null>(null)
  const rememberMe = ref<boolean>(Boolean(localStorage.getItem('lawrag.auth')))

  // 是否已登录：内存中有令牌且未过期。
  const isAuthenticated = computed(() => {
    if (!accessToken.value) return false
    if (expiresAt.value && Date.now() > expiresAt.value) return false
    return true
  })

  // 用户显示名：优先用户名，回退到本地存储的用户名提示。
  const displayName = computed(() => user.value?.username || readStorage()?.username_hint || '未登录')

  // 用户头像，未设置时返回 null 由调用方降级为占位图。
  const avatar = computed(() => user.value?.avatar || null)

  /** 登录：调用后端接口，写入令牌并触发用户资料拉取。 */
  async function login(payload: LoginPayload) {
    const token = await apiLogin(payload)
    const expiresAtValue = Date.now() + token.expires_in * 1000
    accessToken.value = token.access_token
    refreshToken.value = token.refresh_token
    expiresAt.value = expiresAtValue
    setToken(token.access_token)
    writeStorage(
      {
        access_token: token.access_token,
        refresh_token: token.refresh_token,
        expires_at: expiresAtValue,
        username_hint: payload.username,
      },
      rememberMe.value,
    )
    // 登录成功后立即拉取用户资料，避免页面跳转后再次发起请求。
    await fetchUserProfile().catch(() => {
      // 资料拉取失败不阻塞登录主流程，进入应用后可重试。
    })
    return token
  }

  /** 注册：成功后自动写入令牌并拉取资料，等同于隐式登录。 */
  async function register(payload: RegisterPayload) {
    const token = await apiRegister(payload)
    const expiresAtValue = Date.now() + token.expires_in * 1000
    accessToken.value = token.access_token
    refreshToken.value = token.refresh_token
    expiresAt.value = expiresAtValue
    setToken(token.access_token)
    writeStorage(
      {
        access_token: token.access_token,
        refresh_token: token.refresh_token,
        expires_at: expiresAtValue,
        username_hint: payload.username,
      },
      rememberMe.value,
    )
    await fetchUserProfile().catch(() => {})
    return token
  }

  /** 拉取当前用户资料，用于刷新顶部头像与个人中心。 */
  async function fetchUserProfile() {
    if (!accessToken.value) return null
    const profile = await fetchProfile()
    user.value = profile
    return profile
  }

  /** 登出：通知后端加入黑名单并清理本地状态。 */
  async function logout() {
    try {
      if (accessToken.value) {
        await apiLogout()
      }
    } catch {
      // 即使后端登出失败也清除本地凭据，确保用户侧登出体验。
    } finally {
      clearStorage()
      accessToken.value = null
      refreshToken.value = null
      expiresAt.value = 0
      user.value = null
    }
  }

  /** 切换"记住我"选项，必要时把凭据从一种存储迁移到另一种。 */
  function setRememberMe(value: boolean) {
    rememberMe.value = value
    const current = readStorage()
    if (current) {
      writeStorage(current, value)
    }
  }

  return {
    accessToken,
    refreshToken,
    expiresAt,
    user,
    rememberMe,
    isAuthenticated,
    displayName,
    avatar,
    login,
    register,
    logout,
    fetchUserProfile,
    setRememberMe,
  }
})
