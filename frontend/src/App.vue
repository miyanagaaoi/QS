<script setup>
/**
 * 应用根组件
 * ---------------------------------------------------------------------------
 * 只做两件事：
 *  1. ElConfigProvider 注入中文语言包（分页、日期选择器、确认框等文案）；
 *  2. 渲染路由出口。布局由各路由的 component 决定（AdminLayout / SupplierLayout）。
 */
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'

dayjs.locale('zh-cn')
</script>

<template>
  <el-config-provider :locale="zhCn">
    <router-view />
  </el-config-provider>
</template>
