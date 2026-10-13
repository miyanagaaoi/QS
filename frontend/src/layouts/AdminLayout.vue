<script setup>
/**
 * AdminLayout — 采购/管理侧自适应布局（FR-RWD-02 / PRD 10.2）
 * ---------------------------------------------------------------------------
 * ≥1200px 桌面：左侧导航常驻展开 200px
 * 768~1199px 平板：左侧导航折叠为 64px 图标栏（悬浮展开子菜单，可手动展开）
 * <768px 手机：顶部汉堡按钮 → 左侧抽屉弹出；抽屉打开时锁定背景滚动
 *
 * 菜单来源：stores/user.js 的 menus（已按角色过滤，采购员看不到「系统管理」）
 * 断点来源：composables/useBreakpoint（唯一来源 styles/breakpoints.scss）
 */
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Collection,
  Key,
  List,
  Menu as MenuIcon,
  Setting,
  ShoppingCart,
  SwitchButton,
  Tickets,
  TrendCharts,
  User,
} from '@element-plus/icons-vue'

import { useBodyScrollLock } from '@/composables/useBodyScrollLock'
import { useBreakpoint } from '@/composables/useBreakpoint'
import { resolveActiveMenu } from '@/router/menu'
import { useUserStore } from '@/stores/user'

defineOptions({ name: 'AdminLayout' })

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const { isMobile, isTablet, isDesktop } = useBreakpoint()

/** 菜单图标表（icon 名 → 组件），只引入用到的这些，保持包体可控 */
const ICONS = {
  ShoppingCart,
  Tickets,
  TrendCharts,
  Setting,
  User,
  Collection,
  List,
}
function iconOf(name) {
  return ICONS[name] || Tickets
}

const drawerOpen = ref(false)
const collapseOverride = ref(null)

const collapsed = computed(() => {
  if (isDesktop.value || isMobile.value) return false
  return collapseOverride.value ?? true
})

const activeMenu = computed(() => resolveActiveMenu(route.path))
const pageTitle = computed(() => route.meta?.title || '询价报价系统')

/** 面包屑：找到当前菜单所属分组 */
const activeGroupTitle = computed(() => {
  const group = userStore.menus.find((item) =>
    (item.children || []).some((child) => child.path === activeMenu.value),
  )
  return group?.title || '采购管理'
})

// 抽屉打开时锁定背景滚动（FR-RWD-02）
useBodyScrollLock(drawerOpen)

watch(isMobile, (mobile) => {
  if (!mobile) drawerOpen.value = false
})

watch(isTablet, () => {
  collapseOverride.value = null // 离开平板区间时恢复默认折叠策略
})

function onMenuSelect(path) {
  drawerOpen.value = false
  if (path && path !== route.path) router.push(path)
}

function toggleCollapse() {
  collapseOverride.value = !collapsed.value
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
  <div class="admin-layout">
    <!-- ===== 手机顶部栏（含汉堡菜单） ===== -->
    <header v-if="isMobile" class="al-topbar al-topbar--mobile">
      <button
        type="button"
        class="al-icon-btn"
        aria-label="打开导航菜单"
        @click="drawerOpen = true"
      >
        <el-icon :size="20"><MenuIcon /></el-icon>
      </button>
      <h1 class="al-topbar__title">{{ pageTitle }}</h1>
      <el-dropdown trigger="click" @command="onUserCommand">
        <!-- 44×44 透明热区包住 26px 圆形头像：FR-RWD-06 触控热区下限 -->
        <button type="button" class="al-avatar-btn" :aria-label="`当前用户 ${userStore.displayName}`">
          <span class="al-avatar">{{ userStore.avatarText }}</span>
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item disabled>
              {{ userStore.displayName }}（{{ userStore.roleLabel }}）
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
    </header>

    <!-- ===== 侧边导航（平板 / 桌面） ===== -->
    <aside v-else class="al-aside" :class="{ 'is-collapsed': collapsed }">
      <div class="al-brand">
        <span class="al-brand__mark">询</span>
        <span v-if="!collapsed" class="al-brand__name">询价报价系统</span>
      </div>

      <el-menu
        class="al-menu"
        :default-active="activeMenu"
        :collapse="collapsed"
        :collapse-transition="false"
        @select="onMenuSelect"
      >
        <el-sub-menu v-for="group in userStore.menus" :key="group.key" :index="group.key">
          <template #title>
            <el-icon><component :is="iconOf(group.icon)" /></el-icon>
            <span>{{ group.title }}</span>
          </template>
          <el-menu-item v-for="item in group.children" :key="item.key" :index="item.path">
            <el-icon><component :is="iconOf(item.icon)" /></el-icon>
            <template #title>{{ item.title }}</template>
          </el-menu-item>
        </el-sub-menu>
      </el-menu>

      <div class="al-side-foot">
        <span v-if="!collapsed">v1.0 · 内网部署</span>
      </div>
    </aside>

    <!-- ===== 主内容区 ===== -->
    <div class="al-body">
      <header v-if="!isMobile" class="al-topbar">
        <nav class="al-crumb" aria-label="面包屑">
          <span>{{ activeGroupTitle }}</span>
          <i>/</i>
          <b>{{ pageTitle }}</b>
        </nav>
        <div class="al-topbar__spacer" />
        <button
          v-if="isTablet"
          type="button"
          class="al-icon-btn"
          :aria-label="collapsed ? '展开导航' : '折叠导航'"
          @click="toggleCollapse"
        >
          <el-icon :size="18"><MenuIcon /></el-icon>
        </button>
        <el-dropdown trigger="click" @command="onUserCommand">
          <button type="button" class="al-who">
            <span class="al-avatar al-avatar--sm">{{ userStore.avatarText }}</span>
            <span class="al-who__name">{{ userStore.displayName }}</span>
            <span class="al-who__role">{{ userStore.roleLabel }}</span>
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="change-password">
                <el-icon><Key /></el-icon>修改密码
              </el-dropdown-item>
              <el-dropdown-item command="logout">
                <el-icon><SwitchButton /></el-icon>退出登录
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </header>

      <main class="al-main">
        <router-view />
      </main>
    </div>

    <!-- ===== 手机端抽屉导航 ===== -->
    <el-drawer
      v-if="isMobile"
      v-model="drawerOpen"
      direction="ltr"
      size="240px"
      :with-header="false"
      :lock-scroll="false"
      class="al-drawer"
    >
      <div class="al-brand">
        <span class="al-brand__mark">询</span>
        <span class="al-brand__name">询价报价系统</span>
      </div>
      <el-menu
        class="al-menu"
        :default-active="activeMenu"
        :collapse="false"
        @select="onMenuSelect"
      >
        <el-sub-menu v-for="group in userStore.menus" :key="group.key" :index="group.key">
          <template #title>
            <el-icon><component :is="iconOf(group.icon)" /></el-icon>
            <span>{{ group.title }}</span>
          </template>
          <el-menu-item v-for="item in group.children" :key="item.key" :index="item.path">
            <el-icon><component :is="iconOf(item.icon)" /></el-icon>
            <template #title>{{ item.title }}</template>
          </el-menu-item>
        </el-sub-menu>
      </el-menu>
    </el-drawer>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;
@use '@/styles/breakpoints' as bp;

.admin-layout {
  display: flex;
  // Mobile First：手机端结构是「顶部栏 + 内容区」上下排列。
  // 顶栏(.al-topbar--mobile)与内容区(.al-body)是同级 flex 子项，若沿用默认 row，
  // 两者会并排 → 内容区被压到约 156px，再被 body{overflow-x:hidden} 静默裁切
  // （scrollWidth 仍等于视口宽，按 scrollWidth 检测不到，必须按元素宽度判断）。
  flex-direction: column;
  align-items: stretch;
  min-height: 100vh;
  background: v.$surface-sunken;
}

// —— 侧边导航（颜色取自设计稿 04-pages-admin.html 的 .side） ——
.al-aside {
  display: flex;
  flex-direction: column;
  flex: none;
  width: v.$nav-w;
  height: 100vh;
  position: sticky;
  top: 0;
  background: v.$side-bg;
  color: v.$side-ink;
  transition: width 0.18s ease;

  &.is-collapsed {
    width: v.$nav-w-collapsed;
  }
}

.al-brand {
  display: flex;
  align-items: center;
  gap: 9px;
  flex: none;
  height: v.$topbar-h;
  padding: 0 v.$sp-4;
  border-bottom: 1px solid v.$side-line;
}

.al-brand__mark {
  display: grid;
  place-items: center;
  flex: none;
  width: 22px;
  height: 22px;
  font-size: 11px;
  font-weight: 800;
  color: #fff;
  background: v.$brand-500;
  border-radius: v.$r-md;
}

.al-brand__name {
  font-size: v.$fs-sm;
  font-weight: 600;
  color: #fff;
  white-space: nowrap;
}

.al-menu {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: v.$sp-2 0;
  border-right: none;
  background: transparent;

  --el-menu-bg-color: transparent;
  --el-menu-text-color: #{v.$side-ink};
  --el-menu-hover-bg-color: rgba(255, 255, 255, 0.08);
  --el-menu-active-color: #fff;
  --el-menu-item-height: 36px;
  --el-menu-sub-item-height: 34px;

  :deep(.el-sub-menu__title) {
    height: 36px;
    font-size: v.$fs-sm;
    color: v.$side-ink;

    &:hover {
      background: rgba(255, 255, 255, 0.08);
    }
  }

  :deep(.el-menu-item) {
    font-size: v.$fs-sm;
    border-left: 2px solid transparent;
  }

  :deep(.el-menu-item.is-active) {
    color: #fff;
    font-weight: 600;
    background: v.$side-active-bg;
    border-left-color: v.$side-active-bar;
  }
}

.al-side-foot {
  flex: none;
  padding: v.$sp-3 v.$sp-4;
  font-size: v.$fs-xs;
  color: v.$side-muted;
  border-top: 1px solid v.$side-line;
}

// —— 主区 ——
.al-body {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}

.al-topbar {
  display: flex;
  align-items: center;
  gap: v.$sp-3;
  flex: none;
  height: v.$topbar-h;
  padding: 0 v.$sp-4;
  background: v.$surface;
  border-bottom: 1px solid v.$line;
  position: sticky;
  top: 0;
  z-index: 10;
}

.al-topbar--mobile {
  gap: v.$sp-2;
  width: 100%;
  flex: none;
  // 刘海屏安全区
  padding-top: env(safe-area-inset-top, 0px);
  height: auto;
  min-height: v.$topbar-h;
}

.al-topbar__title {
  flex: 1;
  min-width: 0;
  font-size: v.$fs-lg;
  font-weight: 600;
  letter-spacing: -0.01em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.al-topbar__spacer {
  flex: 1;
}

.al-crumb {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  font-size: v.$fs-sm;
  color: v.$ink-400;

  i {
    font-style: normal;
  }

  b {
    color: v.$ink-900;
    font-weight: 600;
  }
}

.al-icon-btn {
  display: grid;
  place-items: center;
  flex: none;
  width: v.$touch-target;
  height: v.$touch-target;
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

// 用户菜单触发热区：44×44（FR-RWD-06），内部圆形头像保持 26px 视觉不变
.al-avatar-btn {
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

.al-avatar {
  display: grid;
  place-items: center;
  flex: none;
  width: 26px;
  height: 26px;
  font-size: 11px;
  font-weight: 700;
  color: v.$brand-800;
  background: v.$brand-100;
  border: none;
  border-radius: 50%;
  cursor: pointer;
}

.al-avatar--sm {
  cursor: inherit;
}

.al-who {
  display: flex;
  align-items: center;
  gap: v.$sp-2;
  padding: 2px 6px 2px 2px;
  font-size: v.$fs-sm;
  color: v.$ink-700;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 100px;
  cursor: pointer;

  &:hover {
    background: v.$surface-hover;
  }
}

.al-who__name {
  font-weight: 600;
  color: v.$ink-900;
}

.al-who__role {
  font-size: v.$fs-xs;
  color: v.$ink-500;
}

.al-main {
  flex: 1;
  min-width: 0;
  padding: v.$sp-3;
}

// —— 抽屉导航：复用暗色侧栏配色 ——
// el-drawer 内容被 teleport 到 body，scoped 的数据属性无法命中 .el-drawer__body，
// 因此这里用 :global 指定（.al-drawer 由 class 透传到 .el-drawer 根节点）。
:global(.al-drawer .el-drawer__body) {
  display: flex;
  flex-direction: column;
  padding: 0;
  background: v.$side-bg;
  color: v.$side-ink;
}

// —— 触屏断点：用户菜单触发热区补足 44px（FR-RWD-06）——
@include bp.mobile {
  .al-who {
    min-height: v.$touch-target;
  }
}

@include bp.tablet {
  .al-who {
    min-height: v.$touch-target;
  }
}

// —— 断点增强（Mobile First：手机样式在上，向上增强） ——
@include bp.tablet-up {
  // 平板 / 桌面：侧边导航与内容区并排（与手机端的上下结构互斥）
  .admin-layout {
    flex-direction: row;
  }

  .al-main {
    padding: v.$sp-4;
  }
}

@include bp.desktop-up {
  .al-topbar {
    padding: 0 v.$sp-5;
  }

  .al-main {
    padding: v.$sp-5;
  }
}
</style>
