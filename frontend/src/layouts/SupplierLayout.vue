<script setup>
/**
 * SupplierLayout — 供货商侧布局（手机优先，PRD 9.3 / 10.2）
 * ---------------------------------------------------------------------------
 * 三种断点均为「顶部标题栏 + 单列内容」，差异只在留白：
 *   手机   ：顶部标题栏（含返回）+ 底部固定操作栏（由页面内的 StickyBar 提供）
 *   平板   ：同手机形态
 *   桌面   ：内容居中限宽，底部操作栏随流
 *
 * 页面主操作（保存 / 提交报价）请用 <StickyBar>（自动吸底并适配安全区），
 * 本布局已为其预留底部空间，不需要页面再算 padding。
 */
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Key, SwitchButton } from '@element-plus/icons-vue'

import { useBreakpoint } from '@/composables/useBreakpoint'
import { useUserStore } from '@/stores/user'

defineOptions({ name: 'SupplierLayout' })

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const { isMobile } = useBreakpoint()

const pageTitle = computed(() => route.meta?.title || '待报价')
const showBack = computed(() => route.meta?.back === true && isMobile.value)
/**
 * 页面自带顶栏时不重复渲染布局顶栏（避免"双头部"）。
 * 供货商页面使用设计稿 03 的暗色 appbar（views/supplier/components/SupplierAppBar.vue），
 * 因此这两条路由声明 meta.selfHeader=true；布局仍然负责外壳、内边距与
 * 底部吸底操作栏的安全区预留。
 */
const showLayoutHeader = computed(() => route.meta?.selfHeader !== true)

function goBack() {
  if (window.history.length > 1) router.back()
  else router.push(userStore.homePath)
}

function onUserCommand(command) {
  if (command === 'change-password') router.push('/change-password')
  else if (command === 'logout') logout()
}

async function logout() {
  await userStore.logout()
  router.replace('/login')
}
</script>

<template>
  <div class="supplier-layout">
    <header v-if="showLayoutHeader" class="sl-header">
      <button v-if="showBack" type="button" class="sl-icon-btn" aria-label="返回" @click="goBack">
        <el-icon :size="20"><ArrowLeft /></el-icon>
      </button>
      <h1 class="sl-header__title">{{ pageTitle }}</h1>
      <div class="sl-header__right">
        <slot name="header-right" />
        <el-dropdown trigger="click" @command="onUserCommand">
          <!-- 44×44 透明热区包住 32px 圆形头像：FR-RWD-06 触控热区下限 -->
          <button
            type="button"
            class="sl-avatar-btn"
            :aria-label="`当前用户 ${userStore.displayName}（${userStore.roleLabel}）`"
          >
            <span class="sl-avatar">{{ userStore.avatarText }}</span>
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item disabled>
                {{ userStore.displayName }}<template v-if="userStore.supplierName">
                  · {{ userStore.supplierName }}</template
                >
              </el-dropdown-item>
              <el-dropdown-item command="change-password" divided>
                <el-icon><Key /></el-icon>修改密码
              </el-dropdown-item>
              <el-dropdown-item command="logout">
                <el-icon><SwitchButton /></el-icon>退出登录
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <main class="sl-main">
      <router-view />
    </main>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;
@use '@/styles/breakpoints' as bp;

.supplier-layout {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  background: v.$surface-sunken;
}

.sl-header {
  display: flex;
  align-items: center;
  gap: v.$sp-2;
  flex: none;
  min-height: v.$topbar-h;
  padding: env(safe-area-inset-top, 0px) v.$sp-3 0;
  background: v.$surface;
  border-bottom: 1px solid v.$line;
  position: sticky;
  top: 0;
  z-index: 10;
}

.sl-header__title {
  flex: 1;
  min-width: 0;
  font-size: v.$fs-lg;
  font-weight: 600;
  letter-spacing: -0.01em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sl-header__right {
  display: flex;
  align-items: center;
  gap: v.$sp-2;
  flex: none;
}

.sl-icon-btn {
  display: grid;
  place-items: center;
  flex: none;
  width: v.$touch-target;
  height: v.$touch-target;
  margin-left: calc(-1 * #{v.$sp-1});
  color: v.$ink-700;
  background: transparent;
  border: 1px solid transparent;
  border-radius: v.$r-md;
  cursor: pointer;

  &:hover {
    color: v.$brand-700;
    background: v.$brand-50;
  }
}

// 用户菜单触发热区：44×44（FR-RWD-06），内部圆形头像保持 32px 视觉不变
.sl-avatar-btn {
  display: grid;
  place-items: center;
  flex: none;
  width: v.$touch-target;
  height: v.$touch-target;
  padding: 0;
  background: transparent;
  border: 0;
  border-radius: 50%;
  cursor: pointer;
}

.sl-avatar {
  display: grid;
  place-items: center;
  flex: none;
  width: 32px;
  height: 32px;
  font-size: v.$fs-xs;
  font-weight: 700;
  color: v.$brand-800;
  background: v.$brand-100;
  border: none;
  border-radius: 50%;
  cursor: pointer;
}

.sl-main {
  flex: 1;
  min-width: 0;
  padding: v.$sp-3;
  // 为页面内的 <StickyBar> 预留空间（含 iPhone 底部安全区），页面无需重复计算
  padding-bottom: calc(#{v.$bottom-bar-h} + #{v.$sp-5} + env(safe-area-inset-bottom, 0px));
}

@include bp.tablet-up {
  .sl-header {
    padding-right: v.$sp-4;
    padding-left: v.$sp-4;
  }

  .sl-main {
    padding: v.$sp-4;
  }
}

@include bp.desktop-up {
  .sl-main {
    padding: v.$sp-5;
  }

  // 桌面端底部操作栏随流，不需要额外预留吸底空间
  .sl-main {
    padding-bottom: v.$sp-5;
  }
}
</style>
