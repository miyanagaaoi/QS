<script setup>
/**
 * AppStatePage — 404 / 403 等状态页（路由兜底与角色守卫命中时使用）
 * 用法（路由）：component: AppStatePage, props: { status: '403', ... }
 */
import { useRouter } from 'vue-router'

defineOptions({ name: 'AppStatePage' })

const props = defineProps({
  status: { type: [String, Number], default: '404' },
  title: { type: String, default: '页面不存在' },
  desc: { type: String, default: '链接可能已失效，或该页面已被移除。' },
  actionText: { type: String, default: '返回首页' },
  actionTo: { type: String, default: '' },
  secondaryText: { type: String, default: '' },
  secondaryTo: { type: String, default: '' },
})

const router = useRouter()

function goPrimary() {
  if (props.actionTo) router.push(props.actionTo)
  else router.push('/')
}

function goSecondary() {
  if (props.secondaryTo) router.push(props.secondaryTo)
}
</script>

<template>
  <div class="state-page">
    <div class="state-page__card">
      <div class="state-page__code num">{{ status }}</div>
      <h1 class="state-page__title">{{ title }}</h1>
      <p class="state-page__desc">{{ desc }}</p>
      <div class="state-page__actions">
        <el-button type="primary" @click="goPrimary">{{ actionText }}</el-button>
        <el-button v-if="secondaryText" @click="goSecondary">{{ secondaryText }}</el-button>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;

.state-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 60vh;
  padding: v.$sp-6 v.$sp-4;
}

.state-page__card {
  width: 100%;
  max-width: 420px;
  padding: v.$sp-6 v.$sp-5;
  text-align: center;
  background: v.$surface;
  border: 1px solid v.$line;
  border-radius: v.$r-lg;
  box-shadow: v.$sh-1;
}

.state-page__code {
  font-size: 2.75rem;
  font-weight: 700;
  line-height: 1.1;
  color: v.$brand-100;
}

.state-page__title {
  margin-top: v.$sp-2;
  font-size: v.$fs-title;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.state-page__desc {
  margin-top: v.$sp-2;
  font-size: v.$fs-sm;
  color: v.$ink-500;
}

.state-page__actions {
  display: flex;
  justify-content: center;
  gap: v.$sp-2;
  margin-top: v.$sp-5;
}
</style>
