import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

/**
 * 全站断点唯一来源：src/styles/breakpoints.scss（PRD 10.1 / FR-RWD-01）。
 * 这里把 SCSS 里的断点数值解析出来注入 JS 常量 __XJ_BREAKPOINTS__，
 * 使 composables/useBreakpoint.js 与 CSS 媒体查询共用同一份定义，
 * 避免"CSS 一套、JS 又抄一套"导致的漂移。业务组件内禁止再写像素断点。
 */
function readBreakpoints(root) {
  const file = path.resolve(root, 'src/styles/breakpoints.scss')
  const src = fs.readFileSync(file, 'utf8')
  const read = (name) => {
    const matched = src.match(new RegExp(`\\$${name}\\s*:\\s*([0-9.]+)px`))
    if (!matched) throw new Error(`[breakpoints] 无法从 ${file} 读取 $${name}`)
    return Number(matched[1])
  }
  return { tablet: read('bp-tablet-min'), desktop: read('bp-desktop-min') }
}

export default defineConfig(({ mode }) => {
  const root = fileURLToPath(new URL('.', import.meta.url))
  const env = loadEnv(mode, root, '')
  const devPort = Number(env.VITE_DEV_PORT || 5173)
  const proxyTarget = env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000'

  return {
    plugins: [
      vue(),
      // Element Plus 按需引入（PRD 9.1：不全局引入，控制首屏包体）
      AutoImport({
        resolvers: [ElementPlusResolver()],
        dts: false,
        eslintrc: { enabled: false },
      }),
      Components({
        resolvers: [ElementPlusResolver()],
        dts: false,
        dirs: ['src/components'],
      }),
    ],
    resolve: {
      alias: { '@': path.resolve(root, 'src') },
    },
    define: {
      __XJ_BREAKPOINTS__: JSON.stringify(readBreakpoints(root)),
    },
    server: {
      host: true,
      port: devPort,
      strictPort: true,
      watch: {
        // 并行开发时编辑器/工具会在源码目录旁生成临时文件，Windows 上极易出现
        // EBUSY: resource busy or locked（watch 到被占用的 .tmp），会让 dev server
        // 直接退出。chokidar 5 已不支持 glob，因此用函数式忽略。
        ignored: (filePath) =>
          /\.tmpdir([\\/]|$)/.test(filePath) || filePath.endsWith('.tmp') || filePath.endsWith('.tmp~'),
      },
      proxy: {
        '/api': { target: proxyTarget, changeOrigin: true },
        // 后端接口文档与 OpenAPI 描述也要转发到后端。
        // 否则它们会落到 Vite 的 SPA 回退上：返回 index.html（HTTP 200），
        // Vue Router 找不到 /docs 路由 → 前端渲染 404 页面，看起来像"接口文档 404"。
        // 生产环境的 nginx 已代理这三个路径（见 frontend/nginx.conf），此处与之对齐。
        '/docs': { target: proxyTarget, changeOrigin: true },
        '/redoc': { target: proxyTarget, changeOrigin: true },
        '/openapi.json': { target: proxyTarget, changeOrigin: true },
      },
    },
    build: {
      outDir: 'dist',
      assetsDir: 'assets',
      sourcemap: false,
      chunkSizeWarningLimit: 1024,
    },
  }
})
