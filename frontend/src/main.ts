// 应用启动文件，集中注册 Vue、Pinia、Router、Element Plus 与全局样式。
import '@unocss/reset/tailwind.css'
import 'virtual:uno.css'
import 'element-plus/dist/index.css'
import './styles/index.css'

import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import { createPinia } from 'pinia'

import App from './App.vue'
import { router } from './router'

// 当前版本只提供浅色主题，启动时清理旧版本保存在页面根节点上的深色标记。
document.documentElement.classList.remove('dark')

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(ElementPlus, {
  locale: zhCn,
})

app.mount('#app')
