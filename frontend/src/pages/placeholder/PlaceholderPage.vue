<!-- 占位页面：保证首页阶段所有导航入口可跳转，并保留企业后台的空状态体验。 -->
<template>
  <section class="placeholder-page">
    <el-empty :description="`${title} 页面正在开发中`">
      <el-button
        type="primary"
        @click="router.push('/')"
      >
        返回首页
      </el-button>
    </el-empty>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const title = computed(() => String(route.meta.title ?? '功能'))
</script>

<style scoped>
.placeholder-page {
  min-height: calc(100vh - 128px);
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--law-border);
  border-radius: 16px;
  background: var(--law-card);
  box-shadow: var(--law-shadow);
}
</style>
