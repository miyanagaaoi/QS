/**
 * 应用入口
 * ---------------------------------------------------------------------------
 * 顺序很重要：先装 Pinia（useUserStore 在组件外也要能用），
 * 再注入 authHandlers（登录态失效 / 强制改密时的跳转），最后装 router 并挂载。
 */
import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import { setAuthHandlers } from '@/api/request'
import { useUserStore } from '@/stores/user'

import './styles/index.scss'
import './styles/element-overrides.scss'

// —— 命令式组件的样式必须在全局引一次 ——
// Element Plus 按需引入（unplugin）只会自动注入**模板里用到**的组件样式；
// ElMessage / ElMessageBox 是通过函数调用的，不含在模板里，因此样式不会自动带上。
// 缺了它们会表现为"确认框出现在左上角、宽高为 0"（本项目实测：.el-overlay 尺寸 0×0），
// Toast 也会变成无样式文本。放在这里统一引入，新页面就不用再逐个记着引了。
import 'element-plus/es/components/message/style/css'
import 'element-plus/es/components/message-box/style/css'

const app = createApp(App)

app.use(createPinia())

// —— request.js 的登录态副作用（避免 request ↔ store ↔ router 循环依赖）——
setAuthHandlers({
  /** 40100：Token 失效 / 未登录 → 清本地登录态并回登录页（带 redirect） */
  onUnauthorized: () => {
    const userStore = useUserStore()
    userStore.clearAuth()
    const current = router.currentRoute.value
    if (current.name === 'login') return
    const redirect = current.fullPath && current.fullPath !== '/' ? current.fullPath : undefined
    router.replace({ path: '/login', query: redirect ? { redirect } : undefined })
  },
  /** 40101：初始密码未修改 → 强制跳改密页，且不可绕过 */
  onMustChangePassword: () => {
    const userStore = useUserStore()
    userStore.markMustChangePassword()
    if (router.currentRoute.value.name !== 'change-password') router.replace('/change-password')
  },
})

app.use(router)
app.mount('#app')
