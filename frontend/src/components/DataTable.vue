<script setup>
/**
 * DataTable — 桌面表格 ↔ 手机卡片 双形态封装（FR-RWD-03 / FR-RWD-05 / PRD 9.1）
 * ---------------------------------------------------------------------------
 * 同一份 data：
 *   ≥768px  渲染 el-table（全列展示；列定义可用 hiddenOn 在平板隐藏次要列）
 *   <768px  渲染卡片列表（title + 4~5 个关键字段 + 操作区），避免"横向拖动才能看到核心信息"
 *
 * 断点判断全部来自 useBreakpoint（唯一来源 styles/breakpoints.scss），组件内不写像素断点。
 *
 * ── Props ─────────────────────────────────────────────────────────────────
 *  data         Array    行数据
 *  columns      Array    桌面列定义 { prop, label, slot, width, minWidth, align, sortable,
 *                        fixed, formatter(row), num, hiddenOn:['tablet'|'desktop'] }
 *                        slot 名与 prop 同名时，用 <template #prop="{ row }"> 自定义单元格
 *  cardFields   Array    手机卡片字段 { label, prop, slot, formatter(row), num }
 *                        不传时取 columns 前 5 个可显示列
 *  cardTitle    String|Function  手机卡片主标题（字段名或函数）
 *  rowKey       String|Function  默认 'id'
 *  loading      Boolean
 *  emptyText    String   空状态文案
 *  title        String   左上角标题（可选）
 *  selectable   Boolean  桌面端多选列
 *  indexColumn  Boolean  桌面端序号列
 *  actionsWidth String|Number 操作列宽（桌面）
 *  height/maxHeight      透传 el-table
 *  pagination   Object   { page, pageSize, total }；传了才显示分页
 *  mode         String   auto(默认) | table | card
 *
 * ── Slots ────────────────────────────────────────────────────────────────
 *  toolbar                标题右侧工具区（按钮组）
 *  actions        {row,index}  行操作；桌面渲染在"操作"列，手机渲染在卡片底部
 *  card           {row,index}  完全自定义手机卡片（覆盖默认结构）
 *  card-title     {row,index}  手机卡片标题区覆盖
 *  card-extra     {row,index}  手机卡片标题右侧（如状态徽标）
 *  card-<prop>    {row,index,field} 手机卡片某字段覆盖
 *  empty                       空状态覆盖
 *  <prop>         {row,column,$index} 桌面某列单元格覆盖
 *
 * ── Emits ────────────────────────────────────────────────────────────────
 *  selection-change(rows) / sort-change({prop,order}) / row-click(row)
 *  page-change({page,pageSize}) / update:page(page) / update:pageSize(size)
 */
import { computed, ref } from 'vue'

import { useBreakpoint } from '@/composables/useBreakpoint'

defineOptions({ name: 'DataTable', inheritAttrs: false })

const props = defineProps({
  data: { type: Array, default: () => [] },
  columns: { type: Array, default: () => [] },
  cardFields: { type: Array, default: () => [] },
  cardTitle: { type: [String, Function], default: '' },
  rowKey: { type: [String, Function], default: 'id' },
  loading: { type: Boolean, default: false },
  emptyText: { type: String, default: '暂无数据' },
  title: { type: String, default: '' },
  selectable: { type: Boolean, default: false },
  indexColumn: { type: Boolean, default: false },
  actionsWidth: { type: [String, Number], default: 170 },
  height: { type: [String, Number], default: undefined },
  maxHeight: { type: [String, Number], default: undefined },
  pagination: { type: Object, default: null },
  mode: { type: String, default: 'auto' },
})

const emit = defineEmits([
  'selection-change',
  'sort-change',
  'row-click',
  'page-change',
  'update:page',
  'update:pageSize',
])

const { isMobile, isTablet } = useBreakpoint()
const tableRef = ref(null)

/** 是否使用卡片形态（手机端默认卡片；mode 可强制） */
const useCard = computed(() => props.mode === 'card' || (props.mode === 'auto' && isMobile.value))

/** 平板端隐藏标记了 hiddenOn:'tablet' 的次要列 */
const tableColumns = computed(() =>
  props.columns.filter((col) => {
    const hiddenOn = col.hiddenOn || []
    return isTablet.value ? !hiddenOn.includes('tablet') : !hiddenOn.includes('desktop')
  }),
)

/** 手机卡片字段：未显式配置时取 columns 前 5 个 */
const cardFieldList = computed(() => {
  if (props.cardFields?.length) return props.cardFields
  return props.columns
    .filter((col) => col.prop && col.label && !(col.hiddenOn || []).includes('mobile'))
    .slice(0, 5)
    .map((col) => ({ label: col.label, prop: col.prop, formatter: col.formatter, num: col.num }))
})

const pageInfo = computed(() => {
  const source = props.pagination || {}
  const page = Number(source.page ?? source.pageNum ?? 1) || 1
  const pageSize = Number(source.pageSize ?? source.page_size ?? 20) || 20
  const total = Number(source.total ?? 0) || 0
  return { page, pageSize, total, pageCount: Math.max(1, Math.ceil(total / pageSize)) }
})

function keyOf(row, index) {
  const key = props.rowKey
  if (typeof key === 'function') return key(row, index)
  return row?.[key] ?? index
}

function cellValue(col, row) {
  if (typeof col.formatter === 'function') return col.formatter(row, col)
  const value = row?.[col.prop]
  return value === null || value === undefined || value === '' ? '—' : value
}

function fieldValue(field, row) {
  if (typeof field.formatter === 'function') return field.formatter(row, field)
  const value = row?.[field.prop]
  return value === null || value === undefined || value === '' ? '—' : value
}

function cardTitleText(row) {
  if (typeof props.cardTitle === 'function') return props.cardTitle(row)
  if (props.cardTitle) return row?.[props.cardTitle] ?? ''
  return row?.title ?? row?.name ?? row?.rfq_no ?? ''
}

function columnProps(col) {
  return {
    prop: col.prop,
    label: col.label,
    width: col.width,
    minWidth: col.minWidth || (col.width ? undefined : 120),
    align: col.align || 'left',
    headerAlign: col.headerAlign || col.align || 'left',
    fixed: col.fixed,
    sortable: col.sortable === true ? true : col.sortable || false,
    showOverflowTooltip: col.showOverflowTooltip === undefined ? true : col.showOverflowTooltip,
  }
}

function emitPage(page, pageSize = pageInfo.value.pageSize) {
  emit('page-change', { page, pageSize })
  emit('update:page', page)
  emit('update:pageSize', pageSize)
}

function goPrev() {
  if (pageInfo.value.page > 1) emitPage(pageInfo.value.page - 1)
}

function goNext() {
  if (pageInfo.value.page < pageInfo.value.pageCount) emitPage(pageInfo.value.page + 1)
}

function clearSelection() {
  tableRef.value?.clearSelection?.()
}

defineExpose({ clearSelection, tableRef })
</script>

<template>
  <div class="data-table">
    <header v-if="title || $slots.toolbar" class="data-table__head">
      <h3 v-if="title" class="data-table__title">{{ title }}</h3>
      <div v-if="$slots.toolbar" class="data-table__tools">
        <slot name="toolbar" />
      </div>
    </header>

    <!-- ============ 平板 / 桌面：表格 ============ -->
    <div v-if="!useCard" class="data-table__table">
      <el-table
        ref="tableRef"
        v-loading="loading"
        :data="data"
        :row-key="rowKey"
        :height="height"
        :max-height="maxHeight"
        stripe
        @selection-change="(rows) => emit('selection-change', rows)"
        @sort-change="(payload) => emit('sort-change', payload)"
        @row-click="(row, column, event) => emit('row-click', row, column, event)"
        v-bind="$attrs"
      >
        <el-table-column v-if="selectable" type="selection" width="44" />
        <el-table-column v-if="indexColumn" type="index" label="#" width="52" align="center" />

        <el-table-column
          v-for="col in tableColumns"
          :key="col.prop || col.slot || col.label"
          v-bind="columnProps(col)"
        >
          <template #default="scope">
            <slot :name="col.slot || col.prop" v-bind="scope">
              <span :class="{ num: col.num }">{{ cellValue(col, scope.row) }}</span>
            </slot>
          </template>
        </el-table-column>

        <el-table-column
          v-if="$slots.actions"
          label="操作"
          :width="actionsWidth"
          align="right"
          header-align="right"
          fixed="right"
        >
          <template #default="scope">
            <div class="data-table__ops">
              <slot name="actions" v-bind="scope" />
            </div>
          </template>
        </el-table-column>

        <template #empty>
          <slot name="empty">
            <el-empty :description="emptyText" :image-size="72" />
          </slot>
        </template>
      </el-table>

      <footer v-if="pagination" class="data-table__foot">
        <span class="data-table__foot-total num">共 {{ pageInfo.total }} 条</span>
        <el-pagination
          :current-page="pageInfo.page"
          :page-size="pageInfo.pageSize"
          :page-sizes="[10, 20, 50, 100]"
          :total="pageInfo.total"
          layout="sizes, prev, pager, next, jumper"
          background
          @current-change="(page) => emitPage(page)"
          @size-change="(size) => emitPage(1, size)"
        />
      </footer>
    </div>

    <!-- ============ 手机：卡片列表（FR-RWD-03） ============ -->
    <div v-else class="data-table__cards">
      <el-skeleton v-if="loading" :rows="4" animated />

      <template v-else>
        <div v-if="!data.length" class="data-table__empty">
          <slot name="empty">
            <el-empty :description="emptyText" :image-size="72" />
          </slot>
        </div>

        <article
          v-for="(row, index) in data"
          :key="keyOf(row, index)"
          class="dt-card"
          @click="emit('row-click', row)"
        >
          <slot name="card" :row="row" :index="index">
            <header class="dt-card__head">
              <slot name="card-title" :row="row" :index="index">
                <h4 class="dt-card__title">{{ cardTitleText(row) }}</h4>
              </slot>
              <div v-if="$slots['card-extra']" class="dt-card__extra">
                <slot name="card-extra" :row="row" :index="index" />
              </div>
            </header>

            <dl class="dt-card__fields">
              <div v-for="field in cardFieldList" :key="field.prop || field.label" class="dt-card__field">
                <dt>{{ field.label }}</dt>
                <dd :class="{ num: field.num !== false }">
                  <slot
                    :name="`card-${field.slot || field.prop}`"
                    :row="row"
                    :index="index"
                    :field="field"
                  >
                    {{ fieldValue(field, row) }}
                  </slot>
                </dd>
              </div>
            </dl>

            <footer v-if="$slots.actions" class="dt-card__foot" @click.stop>
              <slot name="actions" :row="row" :index="index" />
            </footer>
          </slot>
        </article>

        <!-- 手机端分页：上一页/下一页按钮，热区 ≥44px（FR-RWD-05/06） -->
        <nav v-if="pagination" class="dt-pager" aria-label="分页">
          <button type="button" class="dt-pager__btn" :disabled="pageInfo.page <= 1" @click="goPrev">
            上一页
          </button>
          <span class="dt-pager__info num">{{ pageInfo.page }} / {{ pageInfo.pageCount }}</span>
          <button
            type="button"
            class="dt-pager__btn"
            :disabled="pageInfo.page >= pageInfo.pageCount"
            @click="goNext"
          >
            下一页
          </button>
        </nav>
      </template>
    </div>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;
@use '@/styles/breakpoints' as bp;

.data-table {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.data-table__head {
  display: flex;
  align-items: center;
  gap: v.$sp-3;
  flex-wrap: wrap;
  margin-bottom: v.$sp-3;
}

.data-table__title {
  font-size: v.$fs-lg;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.data-table__tools {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: v.$sp-2;
  flex-wrap: wrap;
}

.data-table__table {
  min-width: 0;
}

.data-table__ops {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: v.$sp-1;
}

.data-table__foot {
  display: flex;
  align-items: center;
  gap: v.$sp-3;
  padding: v.$sp-3 0 0;

  .data-table__foot-total {
    font-size: v.$fs-sm;
    color: v.$ink-500;
  }

  :deep(.el-pagination) {
    margin-left: auto;
  }
}

.data-table__empty {
  padding: v.$sp-6 0;
}

// —— 手机卡片 ——
.data-table__cards {
  display: flex;
  flex-direction: column;
  gap: v.$sp-3;
}

.dt-card {
  background: v.$surface;
  border: 1px solid v.$line;
  border-radius: v.$r-lg;
  box-shadow: v.$sh-1;
  overflow: hidden;
}

.dt-card__head {
  display: flex;
  align-items: flex-start;
  gap: v.$sp-2;
  padding: v.$sp-3 v.$sp-4 v.$sp-2;
  border-bottom: 1px solid v.$line-soft;
}

.dt-card__title {
  flex: 1;
  min-width: 0;
  font-size: v.$fs-body;
  font-weight: 600;
  line-height: 1.4;
  word-break: break-word;
}

.dt-card__extra {
  flex: none;
}

.dt-card__fields {
  padding: v.$sp-2 v.$sp-4 v.$sp-3;
}

.dt-card__field {
  display: flex;
  // 窄容器下必须允许字段换行：使用方会把卡片放进两列小网格（单卡仅 ~154px），
  // 不换行的字段值（尤其是 StatusBadge 这种 white-space:nowrap 的元素）会撑出卡片，
  // 再被 .dt-card 的 overflow:hidden 静默裁掉 —— 页面不产生横向滚动条，极难发现。
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 2px v.$sp-2; // 换行时字段值独占一行，行间距 2px
  padding: 5px 0;
  font-size: v.$fs-sm;

  dt {
    flex: none;
    width: 5.5em;
    min-width: 0;
    max-width: 100%;
    color: v.$ink-500;
    overflow-wrap: anywhere;
  }

  dd {
    flex: 1 1 auto; // 换行到独立一行时自动占满整行
    min-width: 0; // flex 子项默认 min-width:auto 会拒绝收缩，是二次溢出的常见原因
    max-width: 100%;
    margin: 0;
    text-align: right;
    color: v.$ink-900;
    overflow-wrap: anywhere;
    word-break: break-word;
  }
}

.dt-card__foot {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: v.$sp-2;
  padding: v.$sp-2 v.$sp-4;
  border-top: 1px solid v.$line-soft;
  background: v.$surface-sunken;

  :deep(.el-button) {
    margin-left: 0;
  }
}

// —— 手机分页 ——
.dt-pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: v.$sp-2;
  padding: v.$sp-1 0 v.$sp-2;
}

.dt-pager__btn {
  flex: 1;
  min-height: v.$touch-target;
  padding: 0 v.$sp-3;
  font-size: v.$fs-body;
  font-weight: 600;
  color: v.$brand-700;
  background: v.$surface;
  border: 1px solid v.$line-strong;
  border-radius: v.$r-md;
  cursor: pointer;

  &:disabled {
    color: v.$ink-300;
    background: v.$surface-sunken;
    border-color: v.$line;
    cursor: not-allowed;
  }
}

.dt-pager__info {
  flex: none;
  font-size: v.$fs-sm;
  color: v.$ink-500;
}

// 平板及以上：卡片形态不出现（保险，防止强制 mode=card 时误用）
@include bp.tablet-up {
  .dt-card__field dd {
    text-align: left;
  }
}
</style>
