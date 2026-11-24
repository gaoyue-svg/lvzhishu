// UnoCSS 原子样式配置，作为项目可扩展的轻量工具层。
import { defineConfig, presetAttributify, presetIcons, presetUno } from 'unocss'

export default defineConfig({
  presets: [presetUno(), presetAttributify(), presetIcons()],
  shortcuts: {
    'center-flex': 'flex items-center justify-center',
  },
})
