/**
 * 我方侧页面的独立构建校验（task-3 自检用，非业务代码）
 * ---------------------------------------------------------------------------
 * 为什么要它：全局 `npm run build` 依赖所有人的文件同时可编译，其他人的文件
 * 出现问题时无法证明我方侧 4 个页面本身能否通过编译。本配置以 lib 模式只打包
 * frontend/src/views/purchase/ 下的 4 个页面 + support.js，用来回答
 * "我这部分是否可编译"。
 *
 * 用法（在 frontend/ 目录下）：
 *   npx vite build --config src/views/purchase/__verify__/vite.config.mjs
 * 产物：src/views/purchase/__verify__/dist/（校验后可删除）
 *
 * 注意：这里刻意不启用 unplugin-vue-components / AutoImport，
 * 因此 `el-*` 组件在产物中是运行时解析；本校验覆盖的是语法、
 * 模板编译、SCSS（含 @use '@/styles/...' 别名解析）与模块导入路径。
 */
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

const here = path.dirname(fileURLToPath(import.meta.url))
const frontendRoot = path.resolve(here, '../../../..')

export default defineConfig({
  root: frontendRoot,
  plugins: [vue()],
  resolve: {
    alias: { '@': path.resolve(frontendRoot, 'src') },
  },
  define: {
    __XJ_BREAKPOINTS__: JSON.stringify({ tablet: 768, desktop: 1200 }),
  },
  build: {
    outDir: path.resolve(here, 'dist'),
    emptyOutDir: true,
    cssCodeSplit: false,
    lib: {
      entry: path.resolve(here, 'entry.js'),
      name: 'XjPurchaseVerify',
      formats: ['es'],
      fileName: () => 'verify.js',
    },
    rollupOptions: {
      external: ['vue', 'vue-router', 'pinia', 'element-plus'],
    },
  },
})
