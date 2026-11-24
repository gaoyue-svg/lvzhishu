<!-- 根组件：直接承载路由视图，避免页面级透明度过渡造成整体发白。 -->
<template>
  <RouterView v-slot="{ Component }">
    <component :is="Component" />
  </RouterView>
</template>
