<!-- Dashboard 骨架屏组件，模拟首页首屏加载状态。 -->
<template>
  <div class="dashboard-skeleton">
    <el-skeleton animated>
      <template #template>
        <el-skeleton-item
          variant="rect"
          class="hero-skeleton"
        />
        <div class="skeleton-grid">
          <el-skeleton-item
            v-for="item in 4"
            :key="item"
            variant="rect"
            class="card-skeleton"
          />
        </div>
        <div class="skeleton-columns">
          <el-skeleton-item
            variant="rect"
            class="chart-skeleton"
          />
          <el-skeleton-item
            variant="rect"
            class="side-skeleton"
          />
        </div>
      </template>
    </el-skeleton>
  </div>
</template>

<style scoped>
.dashboard-skeleton {
  display: grid;
  gap: 18px;
}

.hero-skeleton {
  height: 210px;
  border-radius: 20px;
}

.skeleton-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.card-skeleton {
  height: 94px;
  border-radius: 16px;
}

.skeleton-columns {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) 360px;
  gap: 18px;
}

.chart-skeleton,
.side-skeleton {
  height: 330px;
  border-radius: 16px;
}

@media (max-width: 1180px) {
  .skeleton-grid,
  .skeleton-columns {
    grid-template-columns: 1fr;
  }
}
</style>
