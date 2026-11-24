<!-- 本文件实现个人中心页，对接后端 /api/user/profile 与 /api/user/password，提供资料编辑、密码修改与账户概览。 -->
<template>
  <div class="profile-page">
    <!-- 顶部 Hero：头像、用户名、角色徽章、账户统计 -->
    <header class="profile-hero">
      <div class="hero-pattern" aria-hidden="true" />
      <div class="hero-glow" aria-hidden="true" />

      <div
        v-loading="loading"
        class="hero-content"
      >
        <div class="hero-avatar">
          <img
            v-if="profile?.avatar"
            alt="用户头像"
            :src="profile.avatar"
          >
          <span
            v-else
            class="avatar-letter"
          >
            {{ avatarLetter }}
          </span>
          <span
            class="status-dot"
            :class="profile?.status || 'active'"
          />
        </div>

        <div class="hero-meta">
          <div class="hero-tagline">
            <Scale :size="13" />
            <span>个人中心</span>
          </div>
          <h1 class="hero-name">{{ profile?.username || '加载中…' }}</h1>
          <div class="hero-badges">
            <span
              class="badge role"
              :class="profile?.role || 'user'"
            >
              <ShieldCheck :size="13" />
              {{ roleLabel }}
            </span>
            <span class="badge status">
              <span
                class="dot"
                :class="profile?.status || 'active'"
              />
              {{ statusLabel }}
            </span>
            <span class="badge since">
              <CalendarDays :size="13" />
              加入于 {{ formattedCreatedAt }}
            </span>
          </div>
        </div>

        <div class="hero-stats">
          <div class="stat">
            <div class="stat-value">
              {{ completion }}<span class="percent">%</span>
            </div>
            <div class="stat-label">资料完整度</div>
          </div>
        </div>
      </div>
    </header>

    <!-- 加载错误提示 -->
    <el-alert
      v-if="loadError"
      class="profile-alert"
      :closable="false"
      type="error"
      :title="loadError"
      show-icon
    />

    <!-- 主体：左侧标签页 + 右侧账户概览 -->
    <div class="profile-body">
      <section class="profile-main">
        <el-tabs
          v-model="activeTab"
          class="profile-tabs"
        >
          <!-- 基础资料 -->
          <el-tab-pane name="profile">
            <template #label>
              <span class="tab-label">
                <UserCog :size="15" />
                基础资料
              </span>
            </template>

            <article class="panel-card">
              <header class="panel-heading">
                <div>
                  <h2>基础资料</h2>
                  <p>更新你的用户名、邮箱与手机号，保存后立即生效。</p>
                </div>
                <button
                  type="button"
                  class="ghost-btn"
                  :disabled="!profileFormDirty || savingProfile"
                  @click="resetProfileForm"
                >
                  <RotateCcw :size="15" />
                  还原
                </button>
              </header>

              <el-form
                ref="profileFormRef"
                :model="profileForm"
                :rules="profileRules"
                label-position="top"
                class="profile-form"
              >
                <el-form-item
                  label="用户名"
                  prop="username"
                >
                  <el-input
                    v-model="profileForm.username"
                    clearable
                    maxlength="50"
                    placeholder="2-50 位字符"
                  >
                    <template #prefix>
                      <AtSign :size="15" />
                    </template>
                  </el-input>
                </el-form-item>

                <el-form-item
                  label="邮箱"
                  prop="email"
                >
                  <el-input
                    v-model="profileForm.email"
                    clearable
                    maxlength="100"
                    placeholder="example@lawrag.com"
                  >
                    <template #prefix>
                      <Mail :size="15" />
                    </template>
                  </el-input>
                </el-form-item>

                <el-form-item
                  label="手机号"
                  prop="phone"
                >
                  <el-input
                    v-model="profileForm.phone"
                    clearable
                    maxlength="20"
                    placeholder="选填，11 位国内手机号"
                  >
                    <template #prefix>
                      <Phone :size="15" />
                    </template>
                  </el-input>
                </el-form-item>

                <footer class="panel-actions">
                  <div
                    v-if="profileFormDirty"
                    class="dirty-hint"
                  >
                    <Dot :size="14" />
                    有未保存的修改
                  </div>
                  <el-button
                    type="primary"
                    :icon="Save"
                    :loading="savingProfile"
                    :disabled="!profileFormDirty"
                    @click="handleSaveProfile"
                  >
                    保存修改
                  </el-button>
                </footer>
              </el-form>
            </article>
          </el-tab-pane>

          <!-- 账号安全 -->
          <el-tab-pane name="security">
            <template #label>
              <span class="tab-label">
                <ShieldCheck :size="15" />
                账号安全
              </span>
            </template>

            <article class="panel-card">
              <header class="panel-heading">
                <div>
                  <h2>修改密码</h2>
                  <p>建议定期更换密码，新密码不少于 6 位且包含字母与数字。</p>
                </div>
                <span
                  class="strength-chip"
                  :class="passwordStrength.level"
                >
                  <span class="chip-dot" />
                  {{ passwordStrength.label }}
                </span>
              </header>

              <el-form
                ref="passwordFormRef"
                :model="passwordForm"
                :rules="passwordRules"
                label-position="top"
                class="profile-form"
              >
                <el-form-item
                  label="当前密码"
                  prop="old_password"
                >
                  <el-input
                    v-model="passwordForm.old_password"
                    type="password"
                    show-password
                    clearable
                    placeholder="请输入当前密码"
                  >
                    <template #prefix>
                      <KeyRound :size="15" />
                    </template>
                  </el-input>
                </el-form-item>

                <el-form-item
                  label="新密码"
                  prop="new_password"
                >
                  <el-input
                    v-model="passwordForm.new_password"
                    type="password"
                    show-password
                    clearable
                    placeholder="至少 6 位字符"
                    @input="onPasswordInput"
                  >
                    <template #prefix>
                      <Lock :size="15" />
                    </template>
                  </el-input>
                  <!-- 密码强度进度条 -->
                  <div
                    v-if="passwordForm.new_password"
                    class="strength-bar"
                  >
                    <span
                      v-for="i in 4"
                      :key="i"
                      class="strength-seg"
                      :class="{
                        filled: i <= passwordStrength.score,
                        [passwordStrength.level]: i <= passwordStrength.score,
                      }"
                    />
                  </div>
                </el-form-item>

                <el-form-item
                  label="确认新密码"
                  prop="confirm_password"
                >
                  <el-input
                    v-model="passwordForm.confirm_password"
                    type="password"
                    show-password
                    clearable
                    placeholder="再次输入新密码"
                  >
                    <template #prefix>
                      <LockKeyhole :size="15" />
                    </template>
                  </el-input>
                </el-form-item>

                <footer class="panel-actions">
                  <div class="security-tips">
                    <CheckCircle2 :size="14" />
                    修改成功后当前令牌保持有效，无需重新登录。
                  </div>
                  <el-button
                    type="primary"
                    :icon="ShieldCheck"
                    :loading="savingPassword"
                    @click="handleChangePassword"
                  >
                    更新密码
                  </el-button>
                </footer>
              </el-form>
            </article>
          </el-tab-pane>
        </el-tabs>
      </section>

      <!-- 右侧账户概览 -->
      <aside class="profile-side">
        <article class="panel-card summary-card">
          <header class="panel-heading compact">
            <div>
              <h2>账户概览</h2>
              <p>账号关键信息一览</p>
            </div>
            <span class="summary-icon">
              <IdCard :size="18" />
            </span>
          </header>

          <dl class="summary-list">
            <div class="summary-item">
              <dt>
                <ShieldCheck :size="14" />
                账号角色
              </dt>
              <dd>
                <span
                  class="role-tag"
                  :class="profile?.role || 'user'"
                >
                  {{ roleLabel }}
                </span>
              </dd>
            </div>
            <div class="summary-item">
              <dt>
                <Activity :size="14" />
                账号状态
              </dt>
              <dd>
                <span
                  class="status-tag"
                  :class="profile?.status || 'active'"
                >
                  <span class="tag-dot" />
                  {{ statusLabel }}
                </span>
              </dd>
            </div>
            <div class="summary-item">
              <dt>
                <Mail :size="14" />
                邮箱
              </dt>
              <dd class="ellipsis">{{ profile?.email || '—' }}</dd>
            </div>
            <div class="summary-item">
              <dt>
                <Phone :size="14" />
                手机号
              </dt>
              <dd>{{ profile?.phone || '未绑定' }}</dd>
            </div>
            <div class="summary-item">
              <dt>
                <CalendarDays :size="14" />
                注册时间
              </dt>
              <dd>{{ formattedCreatedAt || '—' }}</dd>
            </div>
          </dl>

          <!-- 头像上传预告 -->
          <footer class="summary-footer">
            <ImagePlus :size="15" />
            <span>头像上传功能即将上线</span>
          </footer>
        </article>
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import {
  Activity,
  AtSign,
  CalendarDays,
  CheckCircle2,
  Dot,
  IdCard,
  ImagePlus,
  Lock,
  LockKeyhole,
  Mail,
  Phone,
  RotateCcw,
  Save,
  Scale,
  ShieldCheck,
  UserCog,
} from 'lucide-vue-next'

import { updatePassword, updateProfile } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'
import type { UserProfile } from '@/types/auth'

const authStore = useAuthStore()
const route = useRoute()
const router = useRouter()

// 当前用户资料（来自 authStore，只读引用）。
const profile = computed<UserProfile | null>(() => authStore.user)

const loading = ref(false)
const loadError = ref('')
const activeTab = ref<'profile' | 'security'>('profile')

// ====== 基础资料表单 ======
const profileFormRef = ref<FormInstance>()
const savingProfile = ref(false)
const profileForm = reactive({
  username: '',
  email: '',
  phone: '',
})

const profileRules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 2, max: 50, message: '用户名长度需为 2-50 位', trigger: 'blur' },
  ],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    {
      pattern: /^[^\s@]+@[^\s@]+\.[^\s@]+$/,
      message: '邮箱格式不正确',
      trigger: 'blur',
    },
  ],
  phone: [
    {
      pattern: /^1[3-9]\d{9}$|^$/,
      message: '请输入有效的 11 位手机号',
      trigger: 'blur',
    },
  ],
}

// 资料表单是否相对后端数据有改动，用于控制保存按钮可用态。
const profileFormDirty = computed(() => {
  if (!profile.value) return false
  return (
    profileForm.username !== profile.value.username ||
    profileForm.email !== profile.value.email ||
    profileForm.phone !== (profile.value.phone || '')
  )
})

function syncProfileForm() {
  if (!profile.value) return
  profileForm.username = profile.value.username
  profileForm.email = profile.value.email
  profileForm.phone = profile.value.phone || ''
}

function resetProfileForm() {
  syncProfileForm()
  profileFormRef.value?.clearValidate()
}

// ====== 密码表单 ======
const passwordFormRef = ref<FormInstance>()
const savingPassword = ref(false)
const passwordForm = reactive({
  old_password: '',
  new_password: '',
  confirm_password: '',
})

const passwordRules: FormRules = {
  old_password: [
    { required: true, message: '请输入当前密码', trigger: 'blur' },
    { min: 6, max: 100, message: '密码长度需为 6-100 位', trigger: 'blur' },
  ],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, max: 100, message: '密码长度需为 6-100 位', trigger: 'blur' },
  ],
  confirm_password: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (_rule, value: string, callback: (e?: Error) => void) => {
        if (value !== passwordForm.new_password) {
          callback(new Error('两次输入的新密码不一致'))
        } else {
          callback()
        }
      },
      trigger: 'blur',
    },
  ],
}

// 密码强度评估：基于长度与字符多样性，输出 score / level / label。
const passwordStrength = computed(() => {
  const pwd = passwordForm.new_password
  if (!pwd) return { score: 0, level: 'empty', label: '未填写' }

  let score = 0
  if (pwd.length >= 6) score += 1
  if (pwd.length >= 10) score += 1
  if (/[a-z]/.test(pwd) && /[A-Z]/.test(pwd)) score += 1
  if (/\d/.test(pwd) && /[^a-zA-Z0-9]/.test(pwd)) score += 1
  // 上限 4
  score = Math.min(score, 4)

  const map: Record<number, { level: string; label: string }> = {
    0: { level: 'weak', label: '过短' },
    1: { level: 'weak', label: '弱' },
    2: { level: 'medium', label: '中等' },
    3: { level: 'good', label: '良好' },
    4: { level: 'strong', label: '强' },
  }
  return { score, ...map[score] }
})

function onPasswordInput() {
  // 输入新密码时清除确认密码的校验态，避免提示错位。
  passwordFormRef.value?.clearValidate('confirm_password')
}

function resetPasswordForm() {
  passwordForm.old_password = ''
  passwordForm.new_password = ''
  passwordForm.confirm_password = ''
  passwordFormRef.value?.clearValidate()
}

// ====== 派生展示信息 ======
const avatarLetter = computed(() => {
  const name = profile.value?.username || ''
  return name ? name.charAt(0).toUpperCase() : '?'
})

const roleLabel = computed(() => {
  if (!profile.value) return '—'
  return profile.value.role === 'admin' ? '管理员' : '普通用户'
})

const statusLabel = computed(() => {
  if (!profile.value) return '—'
  return profile.value.status === 'active' ? '正常' : '已禁用'
})

const formattedCreatedAt = computed(() => {
  if (!profile.value?.created_at) return ''
  const date = new Date(profile.value.created_at)
  if (Number.isNaN(date.getTime())) return profile.value.created_at
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`
})

// 资料完整度：用户名、邮箱、手机号、头像四项加权。
const completion = computed(() => {
  if (!profile.value) return 0
  let filled = 0
  if (profile.value.username) filled += 1
  if (profile.value.email) filled += 1
  if (profile.value.phone) filled += 1
  if (profile.value.avatar) filled += 1
  return Math.round((filled / 4) * 100)
})

// ====== 业务方法 ======
async function loadProfile() {
  loading.value = true
  loadError.value = ''
  try {
    const data = await authStore.fetchUserProfile()
    if (data) syncProfileForm()
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : '用户资料加载失败'
  } finally {
    loading.value = false
  }
}

async function handleSaveProfile() {
  if (!profile.value) return
  const valid = await profileFormRef.value?.validate().catch(() => false)
  if (!valid) return

  // 仅提交发生变化的字段，避免覆盖未改动数据。
  const payload: Partial<Pick<UserProfile, 'username' | 'email' | 'phone'>> = {}
  if (profileForm.username !== profile.value.username) payload.username = profileForm.username
  if (profileForm.email !== profile.value.email) payload.email = profileForm.email
  if (profileForm.phone !== (profile.value.phone || '')) payload.phone = profileForm.phone

  if (Object.keys(payload).length === 0) return

  savingProfile.value = true
  try {
    const updated = await updateProfile(payload)
    // 同步 store，顶部头像与用户名随之更新。
    authStore.user = updated
    syncProfileForm()
    ElMessage.success('资料已更新')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存失败')
  } finally {
    savingProfile.value = false
  }
}

async function handleChangePassword() {
  const valid = await passwordFormRef.value?.validate().catch(() => false)
  if (!valid) return

  savingPassword.value = true
  try {
    await updatePassword({
      old_password: passwordForm.old_password,
      new_password: passwordForm.new_password,
    })
    ElMessage.success('密码已更新')
    resetPasswordForm()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '密码修改失败')
  } finally {
    savingPassword.value = false
  }
}

// ====== 路由 query 同步：支持 ?tab=security 直达安全标签 ======
watch(
  () => route.query.tab,
  (tab) => {
    if (tab === 'security' || tab === 'profile') {
      activeTab.value = tab
    }
  },
  { immediate: true },
)

watch(activeTab, (tab) => {
  // 切换标签时同步 URL，便于分享与刷新保持位置。
  if (route.query.tab !== tab) {
    router.replace({ path: '/profile', query: { tab } })
  }
})

onMounted(loadProfile)
</script>

<style scoped>
/* ============ 页面骨架 ============ */
.profile-page {
  display: grid;
  gap: 18px;
}

/* ============ Hero 顶部横幅 ============ */
.profile-hero {
  position: relative;
  overflow: hidden;
  border: 1px solid rgb(37 99 235 / 14%);
  border-radius: 20px;
  background:
    linear-gradient(135deg, rgb(37 99 235 / 12%), transparent 52%),
    var(--law-card);
  box-shadow: var(--law-shadow);
}

/* 几何线条纹理：模拟法律文书的细腻质感 */
.hero-pattern {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background-image:
    repeating-linear-gradient(
      45deg,
      rgb(37 99 235 / 4%) 0,
      rgb(37 99 235 / 4%) 1px,
      transparent 1px,
      transparent 14px
    ),
    repeating-linear-gradient(
      -45deg,
      rgb(37 99 235 / 3%) 0,
      rgb(37 99 235 / 3%) 1px,
      transparent 1px,
      transparent 22px
    );
  opacity: 0.9;
}

/* 蓝色径向光斑：制造空间纵深 */
.hero-glow {
  position: absolute;
  top: -60%;
  right: -10%;
  width: 60%;
  height: 220%;
  pointer-events: none;
  background: radial-gradient(
    ellipse at center,
    rgb(37 99 235 / 18%) 0%,
    rgb(37 99 235 / 6%) 35%,
    transparent 70%
  );
  filter: blur(8px);
}

.hero-content {
  position: relative;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 28px;
  align-items: center;
  padding: 32px 34px;
  animation: hero-rise 520ms cubic-bezier(0.22, 1, 0.36, 1);
}

@keyframes hero-rise {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* ---- 头像 ---- */
.hero-avatar {
  position: relative;
  width: 96px;
  height: 96px;
  flex-shrink: 0;
}

.hero-avatar img {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  object-fit: cover;
  border: 3px solid var(--law-card);
  box-shadow:
    0 0 0 1px rgb(37 99 235 / 28%),
    0 12px 32px rgb(37 99 235 / 18%);
}

.avatar-letter {
  width: 100%;
  height: 100%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  color: #fff;
  background: linear-gradient(135deg, #2563eb 0%, #1e40af 60%, #1e3a8a 100%);
  border: 3px solid var(--law-card);
  font-family: "Source Han Serif SC", "Noto Serif SC", "Songti SC", Georgia, serif;
  font-size: 40px;
  font-weight: 700;
  box-shadow:
    0 0 0 1px rgb(37 99 235 / 28%),
    0 12px 32px rgb(37 99 235 / 18%);
}

.status-dot {
  position: absolute;
  right: 4px;
  bottom: 4px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: 3px solid var(--law-card);
  background: #94a3b8;
}

.status-dot.active {
  background: #22c55e;
  box-shadow: 0 0 0 3px rgb(34 197 94 / 22%);
}

.status-dot.disabled {
  background: #ef4444;
}

/* ---- 元信息 ---- */
.hero-meta {
  min-width: 0;
}

.hero-tagline {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  padding: 4px 10px;
  border: 1px solid rgb(37 99 235 / 22%);
  border-radius: 999px;
  color: var(--law-primary);
  background: rgb(37 99 235 / 8%);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.hero-name {
  margin: 0 0 14px;
  font-family: "Source Han Serif SC", "Noto Serif SC", "Songti SC", "STSong", Georgia, serif;
  font-size: 38px;
  font-weight: 700;
  line-height: 1.1;
  letter-spacing: -0.01em;
  color: var(--law-text);
}

.hero-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 11px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
  border: 1px solid var(--law-border);
  background: var(--law-card);
  color: var(--law-muted);
}

.badge.role {
  color: #b45309;
  background: rgb(202 138 4 / 10%);
  border-color: rgb(202 138 4 / 28%);
}

.badge.role.admin {
  color: #b45309;
  background: rgb(202 138 4 / 12%);
  border-color: rgb(202 138 4 / 32%);
}

.badge.role.user {
  color: var(--law-primary);
  background: rgb(37 99 235 / 10%);
  border-color: rgb(37 99 235 / 26%);
}

.badge.status .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #94a3b8;
}

.badge.status .dot.active {
  background: #22c55e;
}

.badge.status .dot.disabled {
  background: #ef4444;
}

.badge.since {
  color: var(--law-muted);
}

/* ---- Hero 统计 ---- */
.hero-stats {
  display: flex;
  align-items: center;
  gap: 22px;
  padding: 18px 24px;
  border-radius: 16px;
  background: color-mix(in srgb, var(--law-card) 72%, transparent);
  border: 1px solid var(--law-border);
  backdrop-filter: blur(6px);
}

.stat {
  text-align: right;
}

.stat-value {
  font-family: "JetBrains Mono", "Source Code Pro", ui-monospace, monospace;
  font-size: 26px;
  font-weight: 700;
  line-height: 1;
  color: var(--law-text);
  letter-spacing: -0.02em;
}

.stat-value .percent {
  color: var(--law-primary);
  font-weight: 600;
}

.stat-label {
  margin-top: 6px;
  font-size: 12px;
  color: var(--law-muted);
  letter-spacing: 0.02em;
}

/* ============ 错误提示 ============ */
.profile-alert {
  border-radius: 12px;
}

/* ============ 主体布局 ============ */
.profile-body {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(280px, 1fr);
  gap: 18px;
  align-items: start;
}

.profile-main {
  min-width: 0;
}

/* ============ 标签页 ============ */
.profile-tabs :deep(.el-tabs__header) {
  margin: 0 0 16px;
}

.profile-tabs :deep(.el-tabs__nav-wrap::after) {
  height: 1px;
  background: var(--law-border);
}

.profile-tabs :deep(.el-tabs__item) {
  height: 46px;
  padding: 0 22px;
  font-size: 14px;
  font-weight: 500;
}

.tab-label {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}

.profile-tabs :deep(.el-tabs__active-bar) {
  height: 3px;
  border-radius: 3px 3px 0 0;
  background: linear-gradient(90deg, var(--law-primary), var(--law-primary-strong));
}

/* ============ 面板卡片 ============ */
.panel-card {
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 22px 24px;
  border: 1px solid var(--law-border);
  border-radius: 16px;
  background: var(--law-card);
  box-shadow: var(--law-shadow);
  animation: panel-rise 460ms cubic-bezier(0.22, 1, 0.36, 1) both;
}

@keyframes panel-rise {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.panel-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
}

.panel-heading.compact {
  align-items: center;
}

.panel-heading h2 {
  margin: 0 0 5px;
  font-size: 17px;
  font-weight: 700;
  line-height: 1.3;
  color: var(--law-text);
}

.panel-heading p {
  margin: 0;
  font-size: 13px;
  color: var(--law-muted);
  line-height: 1.5;
}

.ghost-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 7px 12px;
  border: 1px solid var(--law-border);
  border-radius: 10px;
  background: var(--law-card);
  color: var(--law-muted);
  font-size: 13px;
  cursor: pointer;
  transition:
    color 160ms ease,
    border-color 160ms ease,
    background 160ms ease;
}

.ghost-btn:hover:not(:disabled) {
  color: var(--law-primary);
  border-color: rgb(37 99 235 / 32%);
  background: rgb(37 99 235 / 6%);
}

.ghost-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ============ 表单 ============ */
.profile-form {
  display: grid;
  gap: 4px;
}

.profile-form :deep(.el-form-item) {
  margin-bottom: 16px;
}

.profile-form :deep(.el-form-item__label) {
  font-size: 13px;
  font-weight: 500;
  color: var(--law-text);
  padding-bottom: 6px;
}

.panel-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 6px;
  padding-top: 14px;
  border-top: 1px dashed var(--law-border);
}

.dirty-hint {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: #d97706;
  font-size: 12px;
  font-weight: 500;
}

.dirty-hint svg {
  color: #f59e0b;
}

.security-tips {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--law-muted);
  font-size: 12px;
}

.security-tips svg {
  color: #22c55e;
}

/* ============ 密码强度 ============ */
.strength-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 11px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  border: 1px solid var(--law-border);
  background: var(--law-card);
  color: var(--law-muted);
}

.strength-chip .chip-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}

.strength-chip.weak {
  color: #dc2626;
  background: rgb(220 38 38 / 8%);
  border-color: rgb(220 38 38 / 24%);
}

.strength-chip.medium {
  color: #d97706;
  background: rgb(217 119 6 / 10%);
  border-color: rgb(217 119 6 / 26%);
}

.strength-chip.good {
  color: #2563eb;
  background: rgb(37 99 235 / 10%);
  border-color: rgb(37 99 235 / 26%);
}

.strength-chip.strong {
  color: #16a34a;
  background: rgb(22 163 74 / 10%);
  border-color: rgb(22 163 74 / 28%);
}

.strength-bar {
  display: flex;
  gap: 4px;
  margin-top: 8px;
}

.strength-seg {
  flex: 1;
  height: 4px;
  border-radius: 2px;
  background: var(--law-border);
  transition: background 200ms ease;
}

.strength-seg.filled.weak {
  background: #dc2626;
}

.strength-seg.filled.medium {
  background: #d97706;
}

.strength-seg.filled.good {
  background: #2563eb;
}

.strength-seg.filled.strong {
  background: #16a34a;
}

/* ============ 概览侧卡 ============ */
.summary-card {
  position: sticky;
  top: 88px;
}

.summary-icon {
  width: 38px;
  height: 38px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 11px;
  color: var(--law-primary);
  background: rgb(37 99 235 / 10%);
}

.summary-list {
  display: grid;
  gap: 4px;
  margin: 0;
  padding: 0;
}

.summary-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  padding: 12px 0;
  border-bottom: 1px dashed var(--law-border);
}

.summary-item:last-child {
  border-bottom: 0;
}

.summary-item dt {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: var(--law-muted);
  font-size: 13px;
  font-weight: 500;
}

.summary-item dd {
  margin: 0;
  color: var(--law-text);
  font-size: 13px;
  font-weight: 500;
  text-align: right;
  max-width: 60%;
}

.summary-item dd.ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.role-tag {
  display: inline-flex;
  align-items: center;
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
}

.role-tag.admin {
  color: #b45309;
  background: rgb(202 138 4 / 12%);
}

.role-tag.user {
  color: var(--law-primary);
  background: rgb(37 99 235 / 10%);
}

.status-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
}

.status-tag .tag-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.status-tag.active {
  color: #16a34a;
  background: rgb(22 163 74 / 10%);
}

.status-tag.active .tag-dot {
  background: #22c55e;
  box-shadow: 0 0 0 2px rgb(34 197 94 / 24%);
}

.status-tag.disabled {
  color: #dc2626;
  background: rgb(220 38 38 / 10%);
}

.status-tag.disabled .tag-dot {
  background: #ef4444;
}

.summary-footer {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  margin-top: 4px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px dashed var(--law-border);
  background: rgb(148 163 184 / 6%);
  color: var(--law-muted);
  font-size: 12px;
}

/* ============ 响应式 ============ */
@media (max-width: 1180px) {
  .profile-body {
    grid-template-columns: 1fr;
  }

  .summary-card {
    position: static;
  }
}

@media (max-width: 880px) {
  .hero-content {
    grid-template-columns: auto minmax(0, 1fr);
    gap: 20px;
    padding: 24px;
  }

  .hero-stats {
    grid-column: 1 / -1;
    justify-content: space-between;
    margin-top: 4px;
  }

  .hero-name {
    font-size: 30px;
  }
}

@media (max-width: 640px) {
  .hero-content {
    grid-template-columns: 1fr;
    text-align: left;
    padding: 22px;
  }

  .hero-avatar {
    margin: 0;
  }

  .hero-name {
    font-size: 26px;
  }

  .hero-stats {
    gap: 14px;
    padding: 14px 16px;
  }

  .stat-value {
    font-size: 22px;
  }

  .panel-card {
    padding: 18px;
  }

  .panel-actions {
    flex-direction: column;
    align-items: stretch;
  }

  .panel-actions .el-button {
    width: 100%;
  }
}

:global(html.dark) .hero-pattern {
  opacity: 0.6;
}

:global(html.dark) .badge.role.admin {
  color: #fbbf24;
  background: rgb(251 191 36 / 10%);
  border-color: rgb(251 191 36 / 26%);
}

:global(html.dark) .role-tag.admin {
  color: #fbbf24;
  background: rgb(251 191 36 / 12%);
}
</style>
