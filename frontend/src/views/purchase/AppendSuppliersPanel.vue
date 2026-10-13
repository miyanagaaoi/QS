<script setup>
/**
 * AppendSuppliersPanel — 「追加受邀供货商」表单主体（列表 / 报价进度 / 询价单详情三处复用）
 * ---------------------------------------------------------------------------
 * 需求："已发布报价单，未截止前，可编辑追加供货商"（task-11）。
 *
 * 本组件只渲染：说明条 + 候选多选框 + 家数汇总。
 * 弹层容器（桌面 el-dialog / 手机 el-drawer）与底部按钮由调用方负责 ——
 * 三处各写一套最容易出现"文案/校验漂移"，所以把主体抽到这里。
 *
 * 硬约束：候选**只列尚未被分派的供货商**。
 * 差集由调用方计算后通过 options 传入（页面已经拿到 RfqDetail.assignees），
 * 本组件不做取数，保证"一个数据源"。
 */
import { computed } from 'vue'

import { formatDateTime } from '@/composables/useFormat'

defineOptions({ name: 'AppendSuppliersPanel' })

const props = defineProps({
  /** 已选 supplier_id 数组（v-model） */
  modelValue: { type: Array, default: () => [] },
  /** 候选供货商档案 [{ id, name, contact_name, contact_phone }]；已受邀的应已在外部剔除 */
  options: { type: Array, default: () => [] },
  /** 当前已受邀家数（用于「追加后 N 家」） */
  invitedCount: { type: Number, default: 0 },
  /** 报价截止时间（展示用，可为空） */
  deadline: { type: String, default: '' },
  /** 提交中：禁用输入 */
  busy: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue'])

const selected = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})
</script>

<template>
  <div class="append-panel">
    <div class="append-panel__note">
      <span class="append-panel__i" aria-hidden="true">i</span>
      <div>
        仅<b>新增</b>受邀供货商：不改动明细行，也不影响已有报价；新追加的供货商在截止前可正常填报。
        <template v-if="deadline">
          截止时间 <b class="num">{{ formatDateTime(deadline) }}</b>。
        </template>
      </div>
    </div>

    <label class="append-panel__field">
      <span class="append-panel__label">
        选择要追加的供货商 <i>*</i>
        <em>已选 {{ selected.length }} 家</em>
      </span>
      <el-select
        v-model="selected"
        multiple
        filterable
        collapse-tags
        collapse-tags-tooltip
        :disabled="busy"
        placeholder="搜索供货商档案（已受邀的不会出现在这里）"
        style="width: 100%"
      >
        <el-option
          v-for="supplier in options"
          :key="supplier.id"
          :label="supplier.name"
          :value="supplier.id"
        >
          <span>{{ supplier.name }}</span>
          <span class="append-panel__opt">
            {{ supplier.contact_name || '—' }} · {{ supplier.contact_phone || '—' }}
          </span>
        </el-option>
      </el-select>
      <span v-if="!options.length" class="append-panel__hint">
        该单据已邀请全部启用的供货商，没有可追加的对象
      </span>
    </label>

    <p class="append-panel__summary">
      当前受邀 <b class="num">{{ invitedCount }}</b> 家，追加后
      <b class="num">{{ invitedCount + selected.length }}</b> 家
    </p>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables' as v;

.append-panel {
  display: flex;
  flex-direction: column;
  gap: v.$sp-3;
}

.append-panel__note {
  display: flex;
  gap: v.$sp-2;
  align-items: flex-start;
  padding: 11px 13px;
  font-size: v.$fs-sm;
  color: #154882;
  background: v.$info-bg;
  border: 1px solid v.$info-line;
  border-radius: v.$r-md;
}

.append-panel__i {
  flex: none;
  font-weight: 800;
  line-height: 1.3;
}

.append-panel__field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.append-panel__label {
  display: flex;
  align-items: center;
  gap: v.$sp-1;
  font-size: v.$fs-xs;
  font-weight: 600;
  color: v.$ink-500;

  i {
    font-style: normal;
    color: v.$danger;
  }

  em {
    font-style: normal;
    font-weight: 400;
    color: v.$ink-400;
  }
}

.append-panel__opt {
  float: right;
  margin-left: v.$sp-4;
  font-size: v.$fs-xs;
  color: v.$ink-400;
}

.append-panel__hint {
  font-size: v.$fs-xs;
  color: v.$danger;
}

.append-panel__summary {
  font-size: v.$fs-sm;
  color: v.$ink-500;
}
</style>
