<script setup>
/**
 * Login — 登录页（PRD 10.2）
 * ---------------------------------------------------------------------------
 * 桌面：居中卡片 400px；手机：单列全宽、顶部对齐（键盘弹出不遮挡按钮）。
 * 输入框字号 ≥16px 由 styles/element-overrides.scss 在手机端统一保证（FR-RWD-08），
 * 本页再显式声明一次，确保这两张关键表单页不受其它样式影响。
 */
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Lock, User } from '@element-plus/icons-vue'

import { resolveHome } from '@/router/menu'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const formRef = ref(null)
const submitting = ref(false)
const errorMessage = ref('')

const form = reactive({
  username: '',
  password: '',
})

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

const redirectTarget = computed(() => (typeof route.query.redirect === 'string' ? route.query.redirect : ''))

/** 我方侧路径前缀：供货商不得进入（与 router/index.js 的守卫保持同一规则） */
const INTERNAL_PREFIXES = ['/purchase', '/system']

function isInternalPath(path) {
  return INTERNAL_PREFIXES.some((prefix) => path === prefix || path.startsWith(`${prefix}/`))
}

/**
 * 计算登录后的落地路由 —— 只做「登录后首次跳转」的角色回落。
 *
 * 场景：用户从日志/聊天里点了一个角色不匹配的链接（如内部账号点了供货商链接），
 * 守卫会先把他带到 /login?redirect=/supplier/quotes；若登录后照原样跳过去，
 * 访问控制会（正确地）渲染整页 /403 —— 一次误点看起来像系统故障。
 * 因此这里在跳转前校验目标路由是否属于当前角色：不属于就回落到该角色首页。
 *
 * 注意：**已登录**用户直接访问无权路由，仍由路由守卫返回 403（正确的访问控制提示，不在此处改动）。
 */
function resolvePostLoginTarget() {
  const role = userStore.role
  const fallback = resolveHome(role)
  const target = redirectTarget.value
  if (!target || target === '/login') return fallback

  let resolved
  try {
    resolved = router.resolve(target)
  } catch {
    return fallback
  }

  // 供货商访问我方侧路由 → 回落（与守卫的拦截规则一致）
  if (role === 'supplier' && isInternalPath(resolved.path)) return fallback

  // 目标路由声明了 roles 且不含当前角色 → 回落（vue-router 已合并父子路由的 meta）
  const roles = resolved.meta?.roles
  if (Array.isArray(roles) && roles.length && !roles.includes(role)) return fallback

  return target
}

async function onSubmit() {
  if (!formRef.value || submitting.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  errorMessage.value = ''
  try {
    await userStore.login({ username: form.username, password: form.password })
    await router.replace(resolvePostLoginTarget())
    ElMessage.success(`欢迎回来，${userStore.displayName || userStore.username}`)
  } catch (error) {
    // 后端不区分"账号不存在"与"密码错误"（PRD TC-01），这里原样展示提示
    errorMessage.value = error?.message || '登录失败，请稍后重试'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <section class="login-card">
      <header class="login-brand">
        <span class="login-brand__mark">询</span>
        <div class="login-brand__text">
          <h1 class="login-brand__name">询价报价系统</h1>
          <p class="login-brand__desc">内部采购比价与供货商报价平台</p>
        </div>
      </header>

      <el-alert
        v-if="errorMessage"
        class="login-alert"
        type="error"
        :title="errorMessage"
        show-icon
        :closable="false"
      />

      <el-form
        ref="formRef"
        class="login-form"
        :model="form"
        :rules="rules"
        label-position="top"
        size="large"
        @submit.prevent="onSubmit"
      >
        <el-form-item label="用户名" prop="username">
          <el-input
            v-model="form.username"
            placeholder="请输入用户名"
            autocomplete="username"
            :prefix-icon="User"
            clearable
          />
        </el-form-item>

        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="请输入密码"
            autocomplete="current-password"
            :prefix-icon="Lock"
            show-password
          />
        </el-form-item>

        <el-button
          class="login-submit"
          type="primary"
          size="large"
          native-type="submit"
          :loading="submitting"
        >
          登录
        </el-button>
      </el-form>

      <footer class="login-foot">内网系统 · 账号问题请联系管理员</footer>
    </section>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;
@use '@/styles/breakpoints' as bp;

.login-page {
  display: flex;
  // 手机：顶部对齐，软键盘弹出时按钮不被遮住；大屏再垂直居中
  align-items: flex-start;
  justify-content: center;
  min-height: 100vh;
  padding: v.$sp-5 v.$sp-3;
  padding-top: calc(6vh + env(safe-area-inset-top, 0px));
  background: v.$surface-sunken;
}

.login-card {
  width: 100%;
  max-width: 400px;
  padding: v.$sp-5 v.$sp-4 v.$sp-4;
  background: v.$surface;
  border: 1px solid v.$line;
  border-radius: v.$r-lg;
  box-shadow: v.$sh-1;
}

.login-brand {
  display: flex;
  align-items: center;
  gap: v.$sp-3;
  padding-bottom: v.$sp-4;
  margin-bottom: v.$sp-4;
  border-bottom: 1px solid v.$line-soft;
}

.login-brand__mark {
  display: grid;
  place-items: center;
  flex: none;
  width: 36px;
  height: 36px;
  font-size: v.$fs-body;
  font-weight: 800;
  color: #fff;
  background: v.$brand-500;
  border-radius: v.$r-md;
}

.login-brand__text {
  min-width: 0;
}

.login-brand__name {
  font-size: v.$fs-title;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: v.$ink-900;
}

.login-brand__desc {
  margin-top: 2px;
  font-size: v.$fs-xs;
  color: v.$ink-500;
}

.login-alert {
  margin-bottom: v.$sp-4;
}

.login-form {
  :deep(.el-form-item) {
    margin-bottom: v.$sp-4;
  }

  :deep(.el-form-item__label) {
    font-size: v.$fs-sm;
    color: v.$ink-700;
  }
}

.login-submit {
  width: 100%;
  height: 42px;
  font-size: v.$fs-body;
}

.login-foot {
  margin-top: v.$sp-4;
  font-size: v.$fs-xs;
  color: v.$ink-400;
  text-align: center;
}

// —— 手机端：单列全宽 + 输入框 ≥16px（防 iOS 聚焦放大，FR-RWD-08）——
@include bp.mobile {
  .login-page {
    padding-right: v.$sp-3;
    padding-left: v.$sp-3;
  }

  .login-card {
    max-width: none;
    padding: v.$sp-4 v.$sp-3 v.$sp-3;
  }

  .login-form {
    :deep(.el-input__inner) {
      font-size: v.$fs-input-mobile;
    }
  }
}

@include bp.tablet-up {
  .login-page {
    align-items: center;
    padding-top: v.$sp-5;
  }
}
</style>
