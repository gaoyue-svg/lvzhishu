// 认证与用户资料接口模块，对齐后端 /api/auth 与 /api/user 路由。
import { httpGet, httpPost, httpPut } from './request'

import type { LoginPayload, RegisterPayload, TokenResponse, UserProfile } from '@/types/auth'

// 用户登录，返回访问令牌与刷新令牌。
export const login = (payload: LoginPayload) =>
  httpPost<TokenResponse>('/auth/login', payload)

// 用户注册，校验通过后直接签发令牌对。
export const register = (payload: RegisterPayload) =>
  httpPost<TokenResponse>('/auth/register', payload)

// 当前用户登出，将令牌加入 Redis 黑名单。
export const logout = () => httpPost<null>('/auth/logout')

// 获取当前登录用户的公开资料。
export const fetchProfile = () => httpGet<UserProfile>('/user/profile')

// 更新当前用户资料（用户名/邮箱/手机号）。
export const updateProfile = (payload: Partial<UserProfile>) =>
  httpPut<UserProfile>('/user/profile', payload)

// 修改当前用户密码。
export const updatePassword = (payload: { old_password: string; new_password: string }) =>
  httpPut<null>('/user/password', payload)
