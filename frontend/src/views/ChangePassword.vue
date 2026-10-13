<script setup>
/**
 * ChangePassword — 修改密码 / 首次登录强制改密（FR-ACC-13、PRD 10.2）
 * ---------------------------------------------------------------------------
 * 规则与后端 schemas.ChangePasswordRequest 完全一致：8~20 位，至少含字母与数字，
 * 且不能与原密码相同；手机端规则提示常显（PRD 10.2「规则提示常显」）。
 *
 * 重要（后端约定）：改密成功后旧 token 立即失效（JWT 内含密码指纹，见 backend/app/security.py），
 * 因此改密成功后必须清本地登录态并跳登录页，让用户用新密码重新登录。
 */
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { useUserStore } from '@/stores/user'

const router = useRouter()
const userStore = useUserStore()

const formRef = ref(null)
const submitting = ref(false)
const errorMessage = ref('')

const forced = computed(() => userStore.mustChangePassword)

const form = reactive({
  old_password: '',
  new_password: '',
  confirm_password: '',
})

/** 实时规则状态：驱动"规则提示常显"里的勾选样式 */
const checks = computed(() => {
  const next = form.new_password || ''
  return {
    length: next.length >= 8 && next.length <= 20,
    mixed: /[A-Za-z]/.test(next) && /\d/.test(next),
    different: next.length > 0 && next !== form.old_password,
    matched: next.length > 0 && next === form.confirm_password,
  }
})

function validateNewPassword(_rule, value, callback) {
  if (!value) return callback(new Error('请输入新密码'))
  if (value.length < 8 || value.length > 20) return callback(new Error('新密码长度需为 8~20 位'))
  if (!/[A-Za-z]/.test(value) || !/\d/.test(value)) return callback(new Error('新密码需至少包含字母与数字'))
  if (value === form.old_password) return callback(new Error('新密码不能与原密码相同'))
  if (form.confirm_password) formRef.value?.validateField('confirm_password')
  return callback()
}

function validateConfirm(_rule, value, callback) {
  if (!value) return callback(new Error('请再次输入新密码'))
  if (value !== form.new_password) return callback(new Error('两次输入的新密码不一致'))
  return callback()
}

const rules = {
  old_password: [{ required: true, message: '请输入原密码', trigger: 'blur' }],
  new_password: [{ required: true, validator: validateNewPassword, trigger: 'blur' }],
  confirm_password: [{ required: true, validator: validateConfirm, trigger: 'blur' }],
}

async function onSubmit() {
  if (!formRef.value || submitting.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  errorMessage.value = ''
  try {
    await userStore.changePassword({
      old_password: form.old_password,
      new_password: form.new_password,
    })
    // 旧 token 已失效：清登录态并回登录页
    userStore.clearAuth()
    ElMessage.success('密码修改成功，请用新密码重新登录')
    await router.replace('/login')
  } catch (error) {
    errorMessage.value = error?.message || '密码修改失败，请稍后重试'
  } finally {
    submitting.value = false
  }
}

function goBack() {
  if (window.history.length > 1) router.back()
  else router.replace(userStore.homePath)
}

async function logout() {
  await userStore.logout()
  router.replace('/login')
}
</script>

<template>
  <div class="cp-page">
    <section class="cp-card">
      <header class="cp-head">
        <h1 class="cp-title">{{ forced ? '首次登录需修改密码' : '修改密码' }}</h1>
        <p class="cp-desc">
          {{
            forced
              ? '为保障账号安全，请先修改初始密码后再使用系统。'
              : '定期更换密码可降低账号风险。'
          }}
        </p>
      </header>

      <el-alert
        v-if="forced"
        class="cp-alert"
        type="warning"
        title="当前账号仍在使用初始密码，未修改前无法访问其它功能。"
        show-icon
        :closable="false"
      />

      <el-alert
        v-if="errorMessage"
        class="cp-alert"
        type="error"
        :title="errorMessage"
        show-icon
        :closable="false"
      />

      <el-form
        ref="formRef"
        class="cp-form"
        :model="form"
        :rules="rules"
        label-position="top"
        size="large"
        @submit.prevent="onSubmit"
      >
        <el-form-item label="原密码" prop="old_password">
          <el-input
            v-model="form.old_password"
            type="password"
            placeholder="请输入原密码"
            autocomplete="current-password"
            show-password
          />
        </el-form-item>

        <el-form-item label="新密码" prop="new_password">
          <el-input
            v-model="form.new_password"
            type="password"
            placeholder="请输入新密码"
            autocomplete="new-password"
            show-password
          />
        </el-form-item>

        <el-form-item label="确认新密码" prop="confirm_password">
          <el-input
            v-model="form.confirm_password"
            type="password"
            placeholder="请再次输入新密码"
            autocomplete="new-password"
            show-password
          />
        </el-form-item>

        <!-- 规则提示常显（PRD 10.2） -->
        <ul class="cp-rules">
          <li :class="{ 'is-ok': checks.length }">长度 8~20 位</li>
          <li :class="{ 'is-ok': checks.mixed }">至少包含字母与数字</li>
          <li :class="{ 'is-ok': checks.different }">不能与原密码相同</li>
          <li :class="{ 'is-ok': checks.matched }">两次输入一致</li>
        </ul>

        <div class="cp-actions">
          <el-button v-if="!forced" @click="goBack">返回</el-button>
          <el-button v-else @click="logout">退出登录</el-button>
          <el-button
            class="cp-submit"
            type="primary"
            size="large"
            native-type="submit"
            :loading="submitting"
          >
            确认修改
          </el-button>
        </div>
      </el-form>

      <p class="cp-tip">修改成功后需要使用新密码重新登录。</p>
    </section>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;
@use '@/styles/breakpoints' as bp;

.cp-page {
  display: flex;
  align-items: flex-start;
  justify-content: center;
  min-height: 100vh;
  padding: v.$sp-5 v.$sp-3;
  padding-top: calc(6vh + env(safe-area-inset-top, 0px));
  background: v.$surface-sunken;
}

.cp-card {
  width: 100%;
  max-width: 420px;
  padding: v.$sp-5 v.$sp-4 v.$sp-4;
  background: v.$surface;
  border: 1px solid v.$line;
  border-radius: v.$r-lg;
  box-shadow: v.$sh-1;
}

.cp-title {
  font-size: v.$fs-title;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.cp-desc {
  margin-top: v.$sp-1;
  font-size: v.$fs-sm;
  color: v.$ink-500;
}

.cp-head {
  padding-bottom: v.$sp-4;
  margin-bottom: v.$sp-4;
  border-bottom: 1px solid v.$line-soft;
}

.cp-alert {
  margin-bottom: v.$sp-4;
}

.cp-form {
  :deep(.el-form-item) {
    margin-bottom: v.$sp-4;
  }
}

.cp-rules {
  display: grid;
  gap: 5px;
  padding: v.$sp-3;
  margin-bottom: v.$sp-4;
  background: v.$surface-sunken;
  border: 1px solid v.$line-soft;
  border-radius: v.$r-md;
  font-size: v.$fs-xs;
  color: v.$ink-500;

  li {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  li::before {
    content: '';
    flex: none;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: v.$ink-300;
  }

  li.is-ok {
    color: v.$ok;
  }

  li.is-ok::before {
    background: v.$ok;
  }
}

.cp-actions {
  display: flex;
  gap: v.$sp-2;

  :deep(.el-button) {
    margin-left: 0;
  }
}

.cp-submit {
  flex: 1;
  height: 42px;
  font-size: v.$fs-body;
}

.cp-tip {
  margin-top: v.$sp-3;
  font-size: v.$fs-xs;
  color: v.$ink-400;
  text-align: center;
}

// —— 手机端：单列全宽 + 输入框 ≥16px（FR-RWD-08）——
@include bp.mobile {
  .cp-card {
    max-width: none;
    padding: v.$sp-4 v.$sp-3 v.$sp-3;
  }

  .cp-form {
    :deep(.el-input__inner) {
      font-size: v.$fs-input-mobile;
    }
  }

  .cp-actions {
    flex-wrap: wrap;

    :deep(.el-button) {
      min-height: v.$touch-target;
    }
  }
}

@include bp.tablet-up {
  .cp-page {
    align-items: center;
    padding-top: v.$sp-5;
  }
}
</style>
