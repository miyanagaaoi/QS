<script setup>
/**
 * SupplierUserMenu — 供货商侧用户入口（手机端没有左侧导航，登出必须可达）
 * ---------------------------------------------------------------------------
 * 顶栏右侧头像按钮 → 底部弹层：当前账号信息 / 修改密码 / 退出登录。
 * 退出登录二次确认（PRD 10.4 误操作防护）。
 */
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

import { useBodyScrollLock } from '@/composables/useBodyScrollLock'
import { useUserStore } from '@/stores/user'

defineOptions({ name: 'SupplierUserMenu' })

const router = useRouter()
const userStore = useUserStore()

const open = ref(false)
const confirmingLogout = ref(false)

useBodyScrollLock(open)

const name = computed(() => userStore.displayName || '供货商')
const supplierName = computed(() => userStore.supplierName || '')

function close() {
  open.value = false
  confirmingLogout.value = false
}

function goChangePassword() {
  close()
  router.push('/change-password')
}

async function doLogout() {
  close()
  await userStore.logout()
  router.replace('/login')
}
</script>

<template>
  <div class="sum">
    <button
      type="button"
      class="sum__avatar"
      :aria-label="`当前用户 ${name}，打开账号菜单`"
      @click="open = true"
    >
      {{ userStore.avatarText || '供' }}
    </button>

    <Teleport to="body">
      <div v-if="open" class="sum-mask" @click.self="close">
        <section class="sum-sheet" role="dialog" aria-modal="true" aria-label="账号菜单">
          <div class="sum-sheet__grip" aria-hidden="true" />
          <div class="sum-sheet__who">
            <span class="sum-sheet__avatar">{{ userStore.avatarText || '供' }}</span>
            <div class="sum-sheet__meta">
              <b>{{ name }}</b>
              <span>{{ userStore.roleLabel }}<template v-if="supplierName"> · {{ supplierName }}</template></span>
            </div>
          </div>

          <template v-if="!confirmingLogout">
            <button type="button" class="sum-item" @click="goChangePassword">修改密码</button>
            <button type="button" class="sum-item is-danger" @click="confirmingLogout = true">退出登录</button>
            <button type="button" class="sum-item is-ghost" @click="close">取消</button>
          </template>

          <template v-else>
            <p class="sum-sheet__ask">确认退出登录？未保存的填写内容会保留在本机草稿。</p>
            <button type="button" class="sum-item is-danger" @click="doLogout">确认退出</button>
            <button type="button" class="sum-item is-ghost" @click="confirmingLogout = false">返回</button>
          </template>
        </section>
      </div>
    </Teleport>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;

.sum__avatar {
  display: grid;
  place-items: center;
  flex: none;
  width: 30px;
  height: 30px;
  margin-right: -4px;
  font-size: 11.5px;
  font-weight: 700;
  color: #fff;
  background: rgba(255, 255, 255, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.34);
  border-radius: 50%;
  cursor: pointer;
}

.sum-mask {
  position: fixed;
  inset: 0;
  z-index: v.$z-drawer;
  display: flex;
  align-items: flex-end;
  background: rgba(15, 20, 25, 0.42);
}

.sum-sheet {
  width: 100%;
  padding: 8px v.$sp-3 calc(12px + env(safe-area-inset-bottom, 0px));
  background: v.$surface;
  border-radius: 14px 14px 0 0;
  box-shadow: v.$sh-3;
}

.sum-sheet__grip {
  width: 40px;
  height: 4px;
  margin: 0 auto 12px;
  background: v.$line-strong;
  border-radius: 100px;
}

.sum-sheet__who {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 2px 12px;
  margin-bottom: v.$sp-2;
  border-bottom: 1px solid v.$line-soft;
}

.sum-sheet__avatar {
  display: grid;
  place-items: center;
  flex: none;
  width: 38px;
  height: 38px;
  font-size: v.$fs-sm;
  font-weight: 700;
  color: v.$brand-800;
  background: v.$brand-100;
  border-radius: 50%;
}

.sum-sheet__meta {
  min-width: 0;

  b {
    display: block;
    font-size: v.$fs-sm;
    color: v.$ink-900;
  }

  span {
    font-size: 11.5px;
    color: v.$ink-500;
  }
}

.sum-item {
  display: block;
  width: 100%;
  min-height: 46px;
  margin-top: v.$sp-2;
  font-family: inherit;
  font-size: v.$fs-body;
  font-weight: 600;
  color: v.$ink-700;
  background: v.$surface;
  border: 1px solid v.$line-strong;
  border-radius: v.$r-md;
  cursor: pointer;

  &.is-danger {
    color: v.$danger;
    border-color: v.$danger-line;
  }

  &.is-ghost {
    color: v.$ink-500;
    background: transparent;
    border-color: transparent;
  }
}

.sum-sheet__ask {
  margin: 0 2px 6px;
  font-size: v.$fs-xs;
  line-height: 1.5;
  color: v.$ink-500;
}
</style>
