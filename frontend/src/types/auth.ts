// 认证与用户资料相关类型定义，与后端 schemas/auth.py 保持字段一致。

/** 登录/注册成功后返回的 JWT 令牌对。 */
export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

/** 当前登录用户的公开资料。 */
export interface UserProfile {
  id: number
  username: string
  email: string
  phone: string | null
  avatar: string | null
  role: string
  status: string
  created_at: string
}

/** 登录请求体，username 字段可传用户名或邮箱。 */
export interface LoginPayload {
  username: string
  password: string
}

/** 注册请求体。 */
export interface RegisterPayload {
  username: string
  email: string
  password: string
}
