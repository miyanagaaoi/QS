/**
 * usePmScope — 参考表子页的「作用域」状态（CH-005）
 * ---------------------------------------------------------------------------
 * 三个子页（施工步骤 / 预算管理点 / 配套单据）共用同一套作用域逻辑：
 *  - 项目模式：`projectId` = 当前项目，接口带 `?project_id=`，读写该项目的副本；
 *  - 模板模式：`projectId` = null，接口不传 `project_id`，读写全公司标准模板（仅管理员）。
 *
 * 作用域写进 URL query，保证刷新/分享后仍在同一项目同一模式：
 *   /pm/processes?project_id=3            → 项目 3 的副本
 *   /pm/processes?mode=template           → 标准模板（仅管理员可用）
 *
 * 子页只需 `watch(scopeKey, load)`，scopeKey 变化即代表"该重新拉数据了"。
 */
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { listProjects } from '@/api/pm'
import { useUserStore } from '@/stores/user'

export function usePmScope() {
  const route = useRoute()
  const router = useRouter()
  const userStore = useUserStore()

  const isAdmin = computed(() => userStore.isAdmin)
  const projects = ref([])
  const loadingProjects = ref(false)

  /** 模板模式仅管理员可用；非管理员即便 URL 带了也忽略 */
  const mode = ref(
    route.query.mode === 'template' && userStore.isAdmin ? 'template' : 'project',
  )
  const projectId = ref(route.query.project_id ? Number(route.query.project_id) : null)

  /** 传给接口的作用域名：模板模式为 null */
  const scopeKey = computed(() => (mode.value === 'template' ? null : projectId.value))
  const isTemplate = computed(() => mode.value === 'template')
  const currentProject = computed(
    () => projects.value.find((p) => p.id === projectId.value) || null,
  )

  /** URL query 与实际作用域保持一致 */
  function syncQuery() {
    const query = { ...route.query }
    delete query.project_id
    delete query.mode
    if (mode.value === 'template') query.mode = 'template'
    else if (projectId.value) query.project_id = String(projectId.value)
    router.replace({ query }).catch(() => {})
  }

  function setMode(next) {
    if (next === 'template' && !userStore.isAdmin) return
    mode.value = next
    if (next === 'project' && !projectId.value && projects.value.length) {
      projectId.value = projects.value[0].id
    }
    syncQuery()
  }

  function setProjectId(id) {
    projectId.value = id ? Number(id) : null
    if (projectId.value) mode.value = 'project'
    syncQuery()
  }

  async function loadProjects() {
    loadingProjects.value = true
    try {
      projects.value = await listProjects()
      if (!projectId.value && projects.value.length) projectId.value = projects.value[0].id
      // 深链接带了不存在的项目 id：回落到第一个项目，避免空白页
      if (projectId.value && !projects.value.some((p) => p.id === projectId.value)) {
        projectId.value = projects.value[0]?.id ?? null
      }
      syncQuery()
    } catch {
      // request.js 已统一提示
    } finally {
      loadingProjects.value = false
    }
  }

  watch(mode, syncQuery)

  return {
    isAdmin,
    projects,
    loadingProjects,
    mode,
    projectId,
    scopeKey,
    isTemplate,
    currentProject,
    setMode,
    setProjectId,
    loadProjects,
  }
}
