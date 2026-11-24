<!-- 首页 Dashboard 页面，聚合 LawAgent 的统计、图表、入口与工作动态。 -->
<template>
  <DashboardSkeleton v-if="loading" />

  <section
    v-else-if="error"
    class="state-panel"
  >
    <el-result
      icon="error"
      title="首页数据加载失败"
      :sub-title="error"
    >
      <template #extra>
        <el-button
          type="primary"
          @click="loadDashboard()"
        >
          重新加载
        </el-button>
      </template>
    </el-result>
  </section>

  <section
    v-else-if="!dashboard"
    class="state-panel"
  >
    <el-empty description="暂无首页数据" />
  </section>

  <div
    v-else
    class="dashboard-page"
  >
    <WelcomePanel :user-name="dashboard.userName" />
    <StatGrid :stats="dashboard.stats" />

    <SectionPanel
      title="快捷入口"
      description="高频法律工作流快速开始"
    >
      <QuickActionGrid :actions="dashboard.quickActions" />
    </SectionPanel>

    <div class="dashboard-grid primary">
      <SectionPanel
        title="今日使用趋势"
        description="AI问答与法规检索调用走势"
      >
        <template #action>
          <el-dropdown
            trigger="click"
            :disabled="trendLoading"
            @command="handleRangeCommand"
          >
            <el-button>
              最近{{ selectedRange }}天
              <ChevronDown :size="15" />
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="7">
                  最近7天
                </el-dropdown-item>
                <el-dropdown-item command="14">
                  最近14天
                </el-dropdown-item>
                <el-dropdown-item command="30">
                  最近30天
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </template>
        <div v-loading="trendLoading">
          <LawTrendChart :points="dashboard.usageTrend" />
        </div>
      </SectionPanel>

      <SectionPanel
        title="知识库分布"
        description="内容资产类型占比"
      >
        <KnowledgePieChart :slices="dashboard.knowledgePie" />
      </SectionPanel>
    </div>

    <div class="dashboard-grid secondary">
      <RecentChats :chats="dashboard.recentChats" />
      <SearchRecordList :records="dashboard.searchRecords" />
      <AnnouncementPanel :announcements="dashboard.announcements" />
    </div>

    <div class="dashboard-grid tertiary">
      <SystemStatusPanel :statuses="dashboard.systemStatus" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ChevronDown } from 'lucide-vue-next'

import { getDashboardOverview } from '@/api/dashboard'
import AnnouncementPanel from './components/AnnouncementPanel.vue'
import DashboardSkeleton from './components/DashboardSkeleton.vue'
import KnowledgePieChart from './components/KnowledgePieChart.vue'
import LawTrendChart from './components/LawTrendChart.vue'
import QuickActionGrid from './components/QuickActionGrid.vue'
import RecentChats from './components/RecentChats.vue'
import SearchRecordList from './components/SearchRecordList.vue'
import SectionPanel from './components/SectionPanel.vue'
import StatGrid from './components/StatGrid.vue'
import SystemStatusPanel from './components/SystemStatusPanel.vue'
import WelcomePanel from './components/WelcomePanel.vue'
import type { DashboardData } from '@/types/dashboard'

const dashboard = ref<DashboardData>()
const loading = ref(true)
const error = ref('')
const selectedRange = ref<7 | 14 | 30>(7)
const trendLoading = ref(false)

async function loadDashboard(days: 7 | 14 | 30 = selectedRange.value) {
  error.value = ''
  loading.value = !dashboard.value
  try {
    dashboard.value = await getDashboardOverview(days)
    selectedRange.value = days
  } catch (currentError) {
    error.value = currentError instanceof Error ? currentError.message : '未知错误'
  } finally {
    loading.value = false
  }
}

async function handleRangeCommand(range: string | number) {
  const days = Number(range) as 7 | 14 | 30
  if (![7, 14, 30].includes(days) || days === selectedRange.value || trendLoading.value) return
  trendLoading.value = true
  try {
    const nextDashboard = await getDashboardOverview(days)
    dashboard.value = nextDashboard
    selectedRange.value = days
  } catch (currentError) {
    ElMessage.error(currentError instanceof Error ? currentError.message : '趋势数据加载失败')
  } finally {
    trendLoading.value = false
  }
}

onMounted(loadDashboard)
</script>

<style scoped>
.dashboard-page {
  width: 100%;
  display: grid;
  gap: 18px;
}

.dashboard-grid {
  display: grid;
  gap: 18px;
}

.dashboard-grid.primary {
  grid-template-columns: minmax(0, 1.55fr) minmax(320px, 0.85fr);
}

.dashboard-grid.secondary {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.dashboard-grid.tertiary {
  grid-template-columns: minmax(0, 1fr);
}

.state-panel {
  min-height: calc(100vh - 128px);
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--law-border);
  border-radius: 16px;
  background: var(--law-card);
  box-shadow: var(--law-shadow);
}

@media (max-width: 1280px) {
  .dashboard-grid.secondary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 1180px) {
  .dashboard-grid.primary,
  .dashboard-grid.secondary,
  .dashboard-grid.tertiary {
    grid-template-columns: 1fr;
  }
}
</style>
