<!-- 登录/注册页：左侧品牌叙事区 + 右侧表单卡片，承担全站登录态入口。 -->
<template>
  <div class="login-stage">
    <!-- 背景装饰层：噪点纹理 + 渐变光斑，营造法律典籍的庄严氛围 -->
    <div class="stage-backdrop" aria-hidden="true">
      <div class="grain-layer" />
      <div class="halo halo-amber" />
      <div class="halo halo-blue" />
      <div class="grid-lines" />
    </div>

    <!-- 左侧品牌叙事区：天平徽记 + 法律箴言 + 特性列表 -->
    <aside class="brand-pane">
      <header class="brand-head">
        <div class="crest">
          <img
            :src="brandLogo"
            alt="律智枢 天秤与法槌"
          />
        </div>
        <div class="brand-text">
          <strong>律智枢</strong>
          <span>法律智能助手</span>
        </div>
      </header>

      <div class="brand-body">
        <p class="kicker">LEX · RATIO · VERITAS</p>
        <h1 class="manifesto">
          <span class="line">汇法律知识</span>
          <span class="line">启智能决策</span>
        </h1>
        <p class="lead">
          融合法规检索、案例分析、合同审查与文书生成，为法律从业者提供有依据、可溯源、可执行的智能辅助。
        </p>

        <ul class="pillar-list">
          <li>
            <BookOpen :size="18" />
            <div>
              <strong>权威法源</strong>
              <span>聚合现行法规、司法解释与裁判规则</span>
            </div>
          </li>
          <li>
            <Quote :size="18" />
            <div>
              <strong>智能研判</strong>
              <span>结合案情与检索依据生成专业分析</span>
            </div>
          </li>
          <li>
            <ShieldCheck :size="18" />
            <div>
              <strong>风险与文书</strong>
              <span>识别合同风险，辅助生成规范法律文书</span>
            </div>
          </li>
        </ul>
      </div>

      <footer class="brand-foot">
        <span>© 2026 律智枢</span>
        <span class="dot" />
        <span>京 ICP 备 0000000 号</span>
      </footer>
    </aside>

    <!-- 右侧表单区：玻璃拟态卡片承载登录/注册表单 -->
    <main class="form-pane">
      <div class="form-card">
        <div class="card-head">
          <button
            class="ghost-back"
            type="button"
            @click="goHome"
          >
            <ArrowLeft :size="16" />
            <span>返回首页</span>
          </button>
        </div>

        <!-- 模式切换：登录 / 注册 -->
        <div class="mode-tabs">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            type="button"
            class="mode-tab"
            :class="{ active: mode === tab.key }"
            @click="switchMode(tab.key)"
          >
            {{ tab.label }}
          </button>
          <span
            class="mode-ink"
            :style="{ transform: `translateX(${mode === 'login' ? '0%' : '100%'})` }"
          />
        </div>

        <div class="form-title">
          <h2>{{ mode === 'login' ? '欢迎回来' : '创建账户' }}</h2>
          <p>{{ mode === 'login' ? '登录以继续你的法律工作流' : '注册后即刻开启智能法律协作' }}</p>
        </div>

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          label-position="top"
          size="large"
          @submit.prevent="submit"
        >
          <!-- 注册模式：用户名 -->
          <el-form-item
            v-if="mode === 'register'"
            label="用户名"
            prop="username"
          >
            <el-input
              v-model="form.username"
              placeholder="2-50 位字符"
              :prefix-icon="UserIcon"
              clearable
              autocomplete="username"
            />
          </el-form-item>

          <!-- 登录模式：用户名或邮箱 -->
          <el-form-item
            v-else
            label="用户名 / 邮箱"
            prop="username"
          >
            <el-input
              v-model="form.username"
              placeholder="输入用户名或邮箱"
              :prefix-icon="UserIcon"
              clearable
              autocomplete="username"
              @keydown.enter="focusPassword"
            />
          </el-form-item>

          <!-- 注册模式：邮箱 -->
          <el-form-item
            v-if="mode === 'register'"
            label="邮箱"
            prop="email"
          >
            <el-input
              v-model="form.email"
              placeholder="name@example.com"
              :prefix-icon="MailIcon"
              clearable
              autocomplete="email"
            />
          </el-form-item>

          <!-- 密码 -->
          <el-form-item
            label="密码"
            prop="password"
          >
            <el-input
              ref="passwordRef"
              v-model="form.password"
              :type="passwordVisible ? 'text' : 'password'"
              placeholder="至少 6 位"
              :prefix-icon="LockIcon"
              autocomplete="current-password"
              @keydown.enter="submit"
            >
              <template #suffix>
                <button
                  type="button"
                  class="reveal-toggle"
                  :aria-label="passwordVisible ? '隐藏密码' : '显示密码'"
                  @click="passwordVisible = !passwordVisible"
                >
                  <Eye v-if="!passwordVisible" :size="16" />
                  <EyeOff v-else :size="16" />
                </button>
              </template>
            </el-input>
          </el-form-item>

          <!-- 注册模式：确认密码 -->
          <el-form-item
            v-if="mode === 'register'"
            label="确认密码"
            prop="confirmPassword"
          >
            <el-input
              v-model="form.confirmPassword"
              :type="confirmVisible ? 'text' : 'password'"
              placeholder="再次输入密码"
              :prefix-icon="LockIcon"
              autocomplete="new-password"
              @keydown.enter="submit"
            >
              <template #suffix>
                <button
                  type="button"
                  class="reveal-toggle"
                  @click="confirmVisible = !confirmVisible"
                >
                  <Eye v-if="!confirmVisible" :size="16" />
                  <EyeOff v-else :size="16" />
                </button>
              </template>
            </el-input>
          </el-form-item>

          <!-- 登录模式：记住我 + 忘记密码 -->
          <div
            v-if="mode === 'login'"
            class="form-row"
          >
            <el-checkbox v-model="remember">
              记住我
            </el-checkbox>
            <button
              type="button"
              class="text-link"
              @click="handleForgot"
            >
              忘记密码？
            </button>
          </div>

          <el-button
            type="primary"
            class="submit-btn"
            :loading="loading"
            @click="submit"
          >
            <span class="submit-label">{{ mode === 'login' ? '登 录' : '注 册 并 进 入' }}</span>
            <ArrowRight
              v-if="!loading"
              :size="18"
              class="submit-arrow"
            />
          </el-button>
        </el-form>

        <div class="form-foot">
          <template v-if="mode === 'login'">
            还没有账号？
            <button
              type="button"
              class="text-link strong"
              @click="switchMode('register')"
            >
              立即注册
            </button>
          </template>
          <template v-else>
            已有账号？
            <button
              type="button"
              class="text-link strong"
              @click="switchMode('login')"
            >
              直接登录
            </button>
          </template>
        </div>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Eye,
  EyeOff,
  Lock,
  Mail,
  Quote,
  ShieldCheck,
  User as UserIcon,
} from 'lucide-vue-next'

import brandLogo from '@/assets/brand/lawagent-balance-gavel-v3.png'
import { useAuthStore } from '@/stores/auth'

type Mode = 'login' | 'register'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const mode = ref<Mode>('login')
const loading = ref(false)
const passwordVisible = ref(false)
const confirmVisible = ref(false)
const remember = ref(authStore.rememberMe)

const formRef = ref<FormInstance>()
const passwordRef = ref<{ focus: () => void } | null>(null)

// 表单数据：登录与注册共用一份，根据 mode 切换字段。
const form = reactive({
  username: '',
  email: '',
  password: '',
  confirmPassword: '',
})

const MailIcon = Mail
const LockIcon = Lock

const tabs = [
  { key: 'login' as Mode, label: '登 录' },
  { key: 'register' as Mode, label: '注 册' },
]

// 确认密码自定义校验：必须与密码一致。
function validateConfirm(_rule: unknown, value: string, callback: (error?: Error) => void) {
  if (!value) {
    callback(new Error('请再次输入密码'))
    return
  }
  if (value !== form.password) {
    callback(new Error('两次输入的密码不一致'))
    return
  }
  callback()
}

// 表单校验规则：登录与注册动态切换。
const rules = computed<FormRules>(() => {
  if (mode.value === 'login') {
    return {
      username: [{ required: true, message: '请输入用户名或邮箱', trigger: 'blur' }],
      password: [
        { required: true, message: '请输入密码', trigger: 'blur' },
        { min: 6, max: 100, message: '密码长度为 6-100 位', trigger: 'blur' },
      ],
    }
  }
  return {
    username: [
      { required: true, message: '请输入用户名', trigger: 'blur' },
      { min: 2, max: 50, message: '用户名长度为 2-50 位', trigger: 'blur' },
    ],
    email: [
      { required: true, message: '请输入邮箱', trigger: 'blur' },
      { type: 'email', message: '邮箱格式不正确', trigger: 'blur' },
    ],
    password: [
      { required: true, message: '请输入密码', trigger: 'blur' },
      { min: 6, max: 100, message: '密码长度为 6-100 位', trigger: 'blur' },
    ],
    confirmPassword: [{ required: true, validator: validateConfirm, trigger: 'blur' }],
  }
})

// 切换登录/注册模式：重置表单与校验状态。
function switchMode(next: Mode) {
  if (mode.value === next) return
  mode.value = next
  formRef.value?.clearValidate()
  form.password = ''
  form.confirmPassword = ''
}

function focusPassword() {
  passwordRef.value?.focus?.()
}

// 提交表单：先校验，再调用对应接口，成功后跳转 redirect 或首页。
async function submit() {
  if (loading.value) return
  try {
    await formRef.value?.validate()
  } catch {
    return
  }

  authStore.setRememberMe(remember.value)
  loading.value = true
  try {
    if (mode.value === 'login') {
      await authStore.login({ username: form.username.trim(), password: form.password })
      ElMessage.success('登录成功，欢迎回来')
    } else {
      await authStore.register({
        username: form.username.trim(),
        email: form.email.trim(),
        password: form.password,
      })
      ElMessage.success('注册成功，已自动登录')
    }
    redirectToTarget()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '操作失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

// 优先跳转 query.redirect，避免开放重定向风险（仅允许站内路径）。
function redirectToTarget() {
  const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
  const safe = redirect.startsWith('/') && !redirect.startsWith('//') ? redirect : '/'
  router.replace(safe)
}

function goHome() {
  router.push('/')
}

function handleForgot() {
  ElMessage.info('找回密码功能即将上线，请联系管理员重置')
}
</script>

<style>
/* 字体引入：仅在登录页使用衬线显示字体，强化法律典籍仪式感。 */
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@500;600;700&family=Manrope:wght@400;500;600;700;800&display=swap');
</style>

<style scoped>
/* 主舞台：双栏栅格，左侧 1.1fr 叙事 + 右侧 0.9fr 表单。 */
.login-stage {
  position: relative;
  min-height: 100vh;
  display: grid;
  grid-template-columns: 1.1fr 0.9fr;
  overflow: hidden;
  background: #050914;
  color: #e7eefb;
  font-family: 'Manrope', ui-sans-serif, system-ui, sans-serif;
}

/* 背景装饰层：噪点 + 双光斑 + 经纬线，营造深邃法庭氛围。 */
.stage-backdrop {
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
}

.grain-layer {
  position: absolute;
  inset: 0;
  opacity: 0.32;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='3' stitchTiles='stitch'/%3E%3CfeColorMatrix values='0 0 0 0 0.9 0 0 0 0 0.85 0 0 0 0 0.7 0 0 0 0.6 0'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
  mix-blend-mode: overlay;
}

.halo {
  position: absolute;
  border-radius: 999px;
  filter: blur(80px);
  opacity: 0.55;
}

.halo-amber {
  width: 520px;
  height: 520px;
  top: -120px;
  left: -80px;
  background: radial-gradient(circle, rgba(212, 175, 55, 0.55), transparent 70%);
  animation: drift-amber 14s ease-in-out infinite alternate;
}

.halo-blue {
  width: 640px;
  height: 640px;
  bottom: -200px;
  right: -120px;
  background: radial-gradient(circle, rgba(37, 99, 235, 0.5), transparent 70%);
  animation: drift-blue 18s ease-in-out infinite alternate;
}

@keyframes drift-amber {
  from { transform: translate(0, 0); }
  to { transform: translate(60px, 40px); }
}

@keyframes drift-blue {
  from { transform: translate(0, 0); }
  to { transform: translate(-50px, -30px); }
}

.grid-lines {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(231, 238, 251, 0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(231, 238, 251, 0.04) 1px, transparent 1px);
  background-size: 56px 56px;
  mask-image: radial-gradient(ellipse at center, black 30%, transparent 80%);
}

/* 左侧品牌叙事区。 */
.brand-pane {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 56px 64px;
  border-right: 1px solid rgba(212, 175, 55, 0.18);
  background:
    radial-gradient(circle at 20% 0%, rgba(37, 99, 235, 0.16), transparent 50%),
    linear-gradient(160deg, #0a1428 0%, #050914 60%, #02050c 100%);
}

.brand-head {
  display: flex;
  align-items: center;
  gap: 14px;
  opacity: 0;
  animation: rise 0.8s 0.1s ease-out forwards;
}

.crest {
  width: 46px;
  height: 46px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 14px;
  background: linear-gradient(145deg, rgba(44, 82, 130, 0.35), rgba(15, 38, 68, 0.5));
  border: 1px solid rgba(212, 175, 55, 0.42);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.15),
    0 18px 36px rgba(30, 58, 95, 0.3);
}

.crest img {
  width: 32px;
  height: 32px;
  display: block;
  object-fit: contain;
  filter: drop-shadow(0 2px 6px rgba(0, 0, 0, 0.25));
}

.brand-text {
  display: grid;
  gap: 2px;
}

.brand-text strong {
  font-family: 'Cormorant Garamond', serif;
  font-size: 24px;
  font-weight: 600;
  letter-spacing: 0.5px;
  color: #f8efd6;
}

.brand-text span {
  font-size: 12px;
  letter-spacing: 2px;
  color: rgba(231, 238, 251, 0.6);
}

.brand-body {
  max-width: 480px;
  display: grid;
  gap: 28px;
}

.kicker {
  margin: 0;
  font-size: 11px;
  letter-spacing: 6px;
  color: rgba(212, 175, 55, 0.78);
  opacity: 0;
  animation: rise 0.8s 0.25s ease-out forwards;
}

.manifesto {
  margin: 0;
  font-family: 'Cormorant Garamond', serif;
  font-size: clamp(48px, 5.6vw, 84px);
  font-weight: 600;
  line-height: 1.02;
  letter-spacing: -1px;
  color: #fbf5e2;
}

.manifesto .line {
  display: block;
  opacity: 0;
  transform: translateY(20px);
  animation: rise 0.9s ease-out forwards;
}

.manifesto .line:first-child {
  animation-delay: 0.35s;
}

.manifesto .line:last-child {
  animation-delay: 0.5s;
  background: linear-gradient(135deg, #d4af37 0%, #f5e6b8 50%, #b8941f 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.lead {
  margin: 0;
  max-width: 420px;
  font-size: 15px;
  line-height: 1.85;
  color: rgba(231, 238, 251, 0.7);
  opacity: 0;
  animation: rise 0.8s 0.65s ease-out forwards;
}

.pillar-list {
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
  display: grid;
  gap: 16px;
}

.pillar-list li {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 16px 18px;
  border-radius: 16px;
  border: 1px solid rgba(231, 238, 251, 0.08);
  background: linear-gradient(160deg, rgba(231, 238, 251, 0.04), rgba(231, 238, 251, 0.01));
  backdrop-filter: blur(8px);
  opacity: 0;
  transform: translateX(-12px);
  animation: rise-x 0.8s ease-out forwards;
}

.pillar-list li:nth-child(1) { animation-delay: 0.8s; }
.pillar-list li:nth-child(2) { animation-delay: 0.95s; }
.pillar-list li:nth-child(3) { animation-delay: 1.1s; }

.pillar-list li :deep(svg) {
  flex-shrink: 0;
  margin-top: 2px;
  color: #d4af37;
}

.pillar-list strong {
  display: block;
  margin-bottom: 2px;
  font-size: 14px;
  font-weight: 600;
  color: #f8efd6;
}

.pillar-list span {
  font-size: 13px;
  color: rgba(231, 238, 251, 0.6);
}

.brand-foot {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: rgba(231, 238, 251, 0.4);
  opacity: 0;
  animation: rise 0.8s 1.3s ease-out forwards;
}

.brand-foot .dot {
  width: 3px;
  height: 3px;
  border-radius: 999px;
  background: rgba(212, 175, 55, 0.6);
}

@keyframes rise {
  from { opacity: 0; transform: translateY(16px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes rise-x {
  from { opacity: 0; transform: translateX(-12px); }
  to { opacity: 1; transform: translateX(0); }
}

/* 右侧表单区。 */
.form-pane {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48px 32px;
}

.form-card {
  width: 100%;
  max-width: 440px;
  padding: 36px 40px 32px;
  border-radius: 24px;
  border: 1px solid rgba(231, 238, 251, 0.1);
  background: linear-gradient(165deg, rgba(255, 255, 255, 0.04), rgba(255, 255, 255, 0.015));
  backdrop-filter: blur(24px);
  box-shadow:
    0 1px 0 rgba(255, 255, 255, 0.06) inset,
    0 40px 80px rgba(0, 0, 0, 0.4);
  opacity: 0;
  transform: translateY(20px);
  animation: card-in 0.7s 0.2s ease-out forwards;
}

@keyframes card-in {
  to { opacity: 1; transform: translateY(0); }
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 28px;
}

.ghost-back {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border: 0;
  border-radius: 10px;
  background: transparent;
  color: rgba(231, 238, 251, 0.6);
  font-size: 13px;
  cursor: pointer;
  transition: color 0.18s ease, background 0.18s ease;
}

.ghost-back:hover {
  color: #f8efd6;
  background: rgba(231, 238, 251, 0.06);
}

.icon-round {
  width: 34px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(231, 238, 251, 0.12);
  border-radius: 12px;
  background: rgba(231, 238, 251, 0.04);
  color: rgba(231, 238, 251, 0.78);
  cursor: pointer;
  transition: all 0.18s ease;
}

.icon-round:hover {
  color: #f8efd6;
  border-color: rgba(212, 175, 55, 0.4);
}

/* 模式切换 Tab：底部深蓝滑块跟随选中项，未选中项显式描边提示可点击。 */
.mode-tabs {
  position: relative;
  display: grid;
  grid-template-columns: 1fr 1fr;
  padding: 4px;
  margin-bottom: 28px;
  border-radius: 14px;
  background: rgba(231, 238, 251, 0.06);
  border: 1px solid rgba(231, 238, 251, 0.1);
}

.mode-tab {
  position: relative;
  z-index: 1;
  padding: 11px 0;
  border: 0;
  background: transparent;
  color: rgba(231, 238, 251, 0.7);
  font-size: 14px;
  font-weight: 500;
  letter-spacing: 1px;
  cursor: pointer;
  border-radius: 10px;
  transition:
    color 0.25s ease,
    background 0.25s ease;
}

.mode-tab:hover {
  color: #f8efd6;
  background: rgba(231, 238, 251, 0.06);
}

.mode-tab.active {
  color: #ffffff;
  font-weight: 600;
}

.mode-ink {
  position: absolute;
  top: 4px;
  left: 4px;
  width: calc(50% - 4px);
  height: calc(100% - 8px);
  border-radius: 11px;
  background: linear-gradient(135deg, #2c5282 0%, #1e3a5f 100%);
  box-shadow: 0 8px 18px rgba(30, 58, 95, 0.3);
  transition: transform 0.32s cubic-bezier(0.65, 0, 0.35, 1);
}

.form-title {
  margin-bottom: 24px;
}

.form-title h2 {
  margin: 0 0 6px;
  font-family: 'Cormorant Garamond', serif;
  font-size: 30px;
  font-weight: 600;
  color: #f8efd6;
  letter-spacing: 0.3px;
}

.form-title p {
  margin: 0;
  font-size: 13px;
  color: rgba(231, 238, 251, 0.55);
}

/* Element Plus 表单深色主题适配。 */
.form-card :deep(.el-form-item__label) {
  color: rgba(231, 238, 251, 0.78);
  font-size: 13px;
  font-weight: 500;
  padding-bottom: 6px;
}

.form-card :deep(.el-input__wrapper) {
  background: rgba(231, 238, 251, 0.04);
  border-radius: 12px;
  box-shadow: 0 0 0 1px rgba(231, 238, 251, 0.12) inset;
  transition: box-shadow 0.2s ease;
}

.form-card :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px rgba(212, 175, 55, 0.4) inset;
}

.form-card :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px #d4af37 inset, 0 0 0 4px rgba(212, 175, 55, 0.12) inset !important;
}

.form-card :deep(.el-input__inner) {
  color: #f8efd6;
  height: 46px;
  font-size: 14px;
}

.form-card :deep(.el-input__inner::placeholder) {
  color: rgba(231, 238, 251, 0.35);
}

.form-card :deep(.el-input__prefix),
.form-card :deep(.el-input__suffix) {
  color: rgba(231, 238, 251, 0.5);
}

.form-card :deep(.el-form-item__error) {
  color: #fca5a5;
  padding-top: 4px;
}

.reveal-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: inherit;
  cursor: pointer;
  transition: color 0.18s ease, background 0.18s ease;
}

.reveal-toggle:hover {
  color: #d4af37;
  background: rgba(212, 175, 55, 0.1);
}

.form-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: -8px 0 20px;
}

.form-card :deep(.el-checkbox__label) {
  color: rgba(231, 238, 251, 0.7);
  font-size: 13px;
}

.form-card :deep(.el-checkbox__input.is-checked .el-checkbox__inner) {
  background-color: #d4af37;
  border-color: #d4af37;
}

.form-card :deep(.el-checkbox__inner) {
  background-color: transparent;
  border-color: rgba(231, 238, 251, 0.3);
}

.text-link {
  border: 0;
  background: transparent;
  color: rgba(231, 238, 251, 0.55);
  font-size: 13px;
  cursor: pointer;
  transition: color 0.18s ease;
}

.text-link:hover {
  color: #d4af37;
}

.text-link.strong {
  color: #d4af37;
  font-weight: 600;
  padding: 4px 10px;
  margin-left: 4px;
  border-radius: 8px;
  background: rgba(212, 175, 55, 0.12);
  border: 1px solid rgba(212, 175, 55, 0.35);
}

.text-link.strong:hover {
  color: #f5e6b8;
  background: rgba(212, 175, 55, 0.22);
}

/* 提交按钮：金色渐变 + 箭头滑动微动效。 */
.submit-btn {
  width: 100%;
  height: 50px;
  margin-top: 4px;
  border: 0;
  border-radius: 14px;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 2px;
  color: #0b1020;
  background: linear-gradient(135deg, #f5e6b8 0%, #d4af37 50%, #b8941f 100%);
  box-shadow:
    0 1px 0 rgba(255, 255, 255, 0.4) inset,
    0 16px 32px rgba(212, 175, 55, 0.28);
  overflow: hidden;
  position: relative;
  transition: transform 0.18s ease, box-shadow 0.18s ease;
}

.submit-btn:hover {
  transform: translateY(-1px);
  box-shadow:
    0 1px 0 rgba(255, 255, 255, 0.4) inset,
    0 22px 40px rgba(212, 175, 55, 0.36);
}

.submit-btn:active {
  transform: translateY(0);
}

.submit-label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.submit-arrow {
  transition: transform 0.2s ease;
}

.submit-btn:hover .submit-arrow {
  transform: translateX(4px);
}

.form-foot {
  margin-top: 22px;
  text-align: center;
  font-size: 13px;
  color: rgba(231, 238, 251, 0.5);
}

/* 响应式：窄屏隐藏左侧叙事区，表单卡片全宽居中。 */
@media (max-width: 960px) {
  .login-stage {
    grid-template-columns: 1fr;
  }

  .brand-pane {
    display: none;
  }

  .form-pane {
    padding: 32px 18px;
  }

  .form-card {
    max-width: 480px;
    padding: 28px 24px 24px;
  }
}

@media (max-width: 480px) {
  .form-card {
    padding: 24px 18px 20px;
  }

  .form-title h2 {
    font-size: 26px;
  }
}

/* 浅色模式适配：保留金色点缀但整体提亮。 */
:global(html:not(.dark)) .login-stage {
  background: #f4f1ea;
  color: #1a2238;
}

:global(html:not(.dark)) .grain-layer {
  opacity: 0.18;
}

:global(html:not(.dark)) .halo-amber {
  background: radial-gradient(circle, rgba(212, 175, 55, 0.4), transparent 70%);
}

:global(html:not(.dark)) .halo-blue {
  background: radial-gradient(circle, rgba(37, 99, 235, 0.22), transparent 70%);
  opacity: 0.5;
}

:global(html:not(.dark)) .grid-lines {
  background-image:
    linear-gradient(rgba(26, 34, 56, 0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(26, 34, 56, 0.04) 1px, transparent 1px);
}

:global(html:not(.dark)) .brand-pane {
  background:
    radial-gradient(circle at 20% 0%, rgba(37, 99, 235, 0.1), transparent 50%),
    linear-gradient(160deg, #1a2238 0%, #0e1626 60%, #050914 100%);
}

:global(html:not(.dark)) .form-card {
  border-color: rgba(26, 34, 56, 0.1);
  background: rgba(255, 255, 255, 0.86);
  box-shadow:
    0 1px 0 rgba(255, 255, 255, 0.8) inset,
    0 30px 60px rgba(26, 34, 56, 0.12);
}

:global(html:not(.dark)) .ghost-back {
  color: rgba(26, 34, 56, 0.6);
}

:global(html:not(.dark)) .ghost-back:hover {
  background: rgba(26, 34, 56, 0.05);
}

:global(html:not(.dark)) .icon-round {
  border-color: rgba(26, 34, 56, 0.12);
  background: rgba(26, 34, 56, 0.04);
  color: rgba(26, 34, 56, 0.7);
}

:global(html:not(.dark)) .mode-tabs {
  background: rgba(26, 34, 56, 0.04);
  border-color: rgba(26, 34, 56, 0.08);
}

:global(html:not(.dark)) .mode-tab {
  color: rgba(26, 34, 56, 0.55);
}

:global(html:not(.dark)) .mode-tab.active {
  color: #1a2238;
}

:global(html:not(.dark)) .form-title h2 {
  color: #1a2238;
}

:global(html:not(.dark)) .form-title p {
  color: rgba(26, 34, 56, 0.55);
}

:global(html:not(.dark)) .form-card :deep(.el-form-item__label) {
  color: rgba(26, 34, 56, 0.75);
}

:global(html:not(.dark)) .form-card :deep(.el-input__wrapper) {
  background: rgba(26, 34, 56, 0.03);
  box-shadow: 0 0 0 1px rgba(26, 34, 56, 0.12) inset;
}

:global(html:not(.dark)) .form-card :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px rgba(212, 175, 55, 0.5) inset;
}

:global(html:not(.dark)) .form-card :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px #b8941f inset, 0 0 0 4px rgba(212, 175, 55, 0.15) inset !important;
}

:global(html:not(.dark)) .form-card :deep(.el-input__inner) {
  color: #1a2238;
}

:global(html:not(.dark)) .form-card :deep(.el-input__inner::placeholder) {
  color: rgba(26, 34, 56, 0.4);
}

:global(html:not(.dark)) .form-card :deep(.el-input__prefix),
:global(html:not(.dark)) .form-card :deep(.el-input__suffix) {
  color: rgba(26, 34, 56, 0.45);
}

:global(html:not(.dark)) .form-card :deep(.el-checkbox__label) {
  color: rgba(26, 34, 56, 0.7);
}

:global(html:not(.dark)) .form-card :deep(.el-checkbox__inner) {
  border-color: rgba(26, 34, 56, 0.3);
}

:global(html:not(.dark)) .text-link {
  color: rgba(26, 34, 56, 0.55);
}

:global(html:not(.dark)) .text-link.strong {
  color: #b8941f;
}

:global(html:not(.dark)) .form-foot {
  color: rgba(26, 34, 56, 0.5);
}

/* 单一浅色主题：覆盖旧版登录页固定的深色舞台与金色控件。 */
.login-stage {
  background: #f4f7f4;
}

.stage-backdrop {
  background:
    radial-gradient(circle at 18% 15%, rgba(8, 127, 114, 0.14), transparent 34%),
    radial-gradient(circle at 86% 80%, rgba(217, 164, 65, 0.12), transparent 32%),
    linear-gradient(135deg, #eef8f4, #faf9f3 58%, #f2f5f2);
}

.grain-layer,
.grid-lines {
  opacity: 0.16;
}

.form-card {
  border-color: var(--law-border);
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 26px 70px rgba(15, 38, 68, 0.14);
}

.mode-tabs {
  border-color: var(--law-border);
  background: var(--law-bg-soft);
}

.mode-ink {
  background: linear-gradient(135deg, #2c5282 0%, #1e3a5f 100%);
  box-shadow: 0 8px 18px rgba(30, 58, 95, 0.22);
}

.mode-tab {
  color: rgba(26, 34, 56, 0.65);
}

.mode-tab:hover {
  color: #1a2238;
  background: rgba(30, 58, 95, 0.06);
}

.mode-tab.active {
  color: #ffffff;
}

.form-title h2,
.form-card :deep(.el-input__inner) {
  color: var(--law-text);
}

.form-title p,
.ghost-back,
.form-foot,
.text-link {
  color: var(--law-muted-soft);
}

.form-card :deep(.el-form-item__label),
.form-card :deep(.el-checkbox__label) {
  color: var(--law-muted);
}

.form-card :deep(.el-input__wrapper) {
  background: #f8fafc;
  box-shadow: 0 0 0 1px var(--law-border) inset;
}

.form-card :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px var(--law-primary) inset, 0 0 0 4px rgba(30, 58, 95, 0.12) !important;
}

.submit-btn {
  color: #ffffff;
  background: linear-gradient(135deg, #2c5282 0%, #1e3a5f 100%);
  box-shadow: 0 12px 28px rgba(30, 58, 95, 0.22);
}

.text-link.strong {
  color: var(--law-primary);
  background: rgba(30, 58, 95, 0.08);
  border-color: rgba(30, 58, 95, 0.25);
}

.text-link.strong:hover {
  color: #ffffff;
  background: var(--law-primary);
}
</style>
