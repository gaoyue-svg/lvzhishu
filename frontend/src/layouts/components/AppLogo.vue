<!-- 品牌标识组件，用于侧栏与顶部区域保持统一识别。 -->
<template>
  <div
    class="app-logo"
    :class="{ compact }"
  >
    <div class="logo-mark">
      <img
        :src="brandLogo"
        alt="律智枢 天秤与法槌标志"
      >
    </div>
    <div
      v-if="!compact"
      class="logo-text"
    >
      <strong>律智枢</strong>
      <span>法律智能助手</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import brandLogo from '@/assets/brand/lawagent-balance-gavel-v3.png'

defineProps<{
  compact?: boolean
}>()
</script>

<style scoped>
.app-logo {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.app-logo.compact {
  justify-content: center;
}

/* 品牌徽章: 白底 + 鎏金描边, 图标原色清晰可见。 */
.app-logo .logo-mark {
  position: relative;
  width: 36px;
  height: 36px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  overflow: hidden;
  border: 1px solid rgba(201, 169, 110, 0.6);
  border-radius: 10px;
  background: linear-gradient(160deg, #ffffff 0%, #f5f7fb 100%);
  box-shadow:
    0 4px 14px rgba(15, 38, 68, 0.10),
    inset 0 1px 0 rgba(255, 255, 255, 1);
}

.app-logo .logo-mark img {
  width: 28px;
  height: 28px;
  display: block;
  object-fit: contain;
}

.app-logo .logo-text {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.app-logo .logo-text strong {
  color: var(--law-text);
  font-size: 15px;
  line-height: 1.1;
  font-weight: 700;
  letter-spacing: 0.01em;
}

.app-logo .logo-text span {
  color: var(--law-muted-soft);
  font-size: 12px;
  line-height: 1.2;
}
</style>
