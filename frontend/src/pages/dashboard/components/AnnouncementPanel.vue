<!-- 公告组件，展示平台同步、模型升级等运营通知。 -->
<template>
  <SectionPanel
    title="公告"
    description="平台更新与法律数据同步动态"
  >
    <div class="announcement-list">
      <button
        v-for="item in announcements"
        :key="item.id"
        class="announcement-row"
        type="button"
        @click="openAnnouncement(item)"
      >
        <span :class="['announcement-mark', item.level]" />
        <span>
          <strong>{{ item.title }}</strong>
          <small>{{ item.content }}</small>
        </span>
      </button>
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="selected?.title"
      width="520px"
    >
      <p class="dialog-content">
        {{ selected?.content }}
      </p>
      <template #footer>
        <el-button
          type="primary"
          @click="dialogVisible = false"
        >
          知道了
        </el-button>
      </template>
    </el-dialog>
  </SectionPanel>
</template>

<script setup lang="ts">
import { ref } from 'vue'

import SectionPanel from './SectionPanel.vue'
import type { Announcement } from '@/types/dashboard'

defineProps<{
  announcements: Announcement[]
}>()

const dialogVisible = ref(false)
const selected = ref<Announcement>()

function openAnnouncement(item: Announcement) {
  selected.value = item
  dialogVisible.value = true
}
</script>

<style scoped>
.announcement-list {
  display: grid;
  gap: 10px;
}

.announcement-row {
  width: 100%;
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr);
  gap: 12px;
  align-items: start;
  padding: 12px;
  border: 1px solid var(--law-border);
  border-radius: 14px;
  color: var(--law-text);
  background: var(--law-bg-soft);
  text-align: left;
  cursor: pointer;
}

.announcement-mark {
  width: 8px;
  height: 8px;
  margin-top: 7px;
  border-radius: 999px;
  background: var(--law-primary);
}

.announcement-mark.warning {
  background: var(--law-gold-strong);
}

.announcement-row strong {
  display: block;
  margin-bottom: 4px;
  font-size: 14px;
}

.announcement-row small {
  display: -webkit-box;
  overflow: hidden;
  color: var(--law-muted);
  font-size: 12px;
  line-height: 1.55;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.dialog-content {
  margin: 0;
  color: var(--law-muted);
  line-height: 1.8;
}
</style>
