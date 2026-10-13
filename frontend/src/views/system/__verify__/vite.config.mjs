/**
 * 系统管理页面的独立构建校验（task-6 自检用，非业务代码）
 * ---------------------------------------------------------------------------
 * 为什么要它：全局 `npm run build` 需要所有人的文件同时可编译。当其他人的文件
 * （如 views/supplier、views/purchase）先报错时，无法证明我负责的 4 个页面
 * 本身能否通过编译。本配置以 lib 模式只打包 views/system 下的页面 + admin API，
 * 用来回答"我这部分是否可编译"。
 *
 * 用法（在 frontend/ 目录下）：
 *   npx vite build --config src/views/system/__verify__/vite.config.mjs
 * 产物：src/views/system/__verify__/dist/（校验后可删除）
 *
 * 与全局构建的差异（不影响结论）：
 *   - 不启用 unplugin-vue-components / AutoImport，因此 `el-*` 组件与 `ElMessage`
 *     在产物中是运行时解析；本校验覆盖语法、模板编译、SCSS（含 @use 别名解析）
 *     与模块导入路径是否正确。
 *   - 子组件按相对路径正常打包（因此 SupplierImport / SupplierArchivePanel 一并被校验）。
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
      name: 'XjSystemVerify',
      formats: ['es'],
      fileName: () => 'verify.js',
    },
    rollupOptions: {
      external: ['vue', 'vue-router', 'pinia', 'element-plus'],
    },
  },
})
