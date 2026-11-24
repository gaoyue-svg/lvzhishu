<!-- 通知抽屉组件，展示公告与系统事件。 -->
<template>
  <el-drawer
    v-model="visible"
    title="消息通知"
    size="360px"
  >
    <div class="notice-list">
      <article
        v-for="item in notices"
        :key="item.title"
        class="notice-item"
      >
        <span :class="['notice-dot', item.type]" />
        <div>
          <strong>{{ item.title }}</strong>
          <p>{{ item.description }}</p>
        </div>
        <time>{{ item.time }}</time>
      </article>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  modelValue: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const notices = [
  { title: '法规库同步完成', description: '新增 25 条有效法规与司法解释。', time: '10分钟前', type: 'success' },
  { title: '合同审查报告生成', description: '服务采购合同已生成风险报告。', time: '36分钟前', type: 'info' },
  { title: 'Embedding 队列提醒', description: '有 12 个文档正在等待向量化。', time: '今天', type: 'warning' },
]
</script>

<style scoped>
.notice-list {
  display: grid;
  gap: 12px;
}

.notice-item {
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: start;
  padding: 14px;
  border: 1px solid var(--law-border);
  border-radius: 14px;
  background: var(--law-card);
}

.notice-dot {
  width: 8px;
  height: 8px;
  margin-top: 6px;
  border-radius: 999px;
  background: #2563eb;
}

.notice-dot.success {
  background: #16a34a;
}

.notice-dot.warning {
  background: #d97706;
}

.notice-item strong {
  display: block;
  margin-bottom: 4px;
  font-size: 14px;
}

.notice-item p {
  margin: 0;
  color: var(--law-muted);
  font-size: 13px;
  line-height: 1.6;
}

.notice-item time {
  color: var(--law-muted);
  font-size: 12px;
}
</style>
