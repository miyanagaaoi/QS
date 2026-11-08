/**
 * 设备管理页面配置（CH-014）
 * ---------------------------------------------------------------------------
 * 用配置驱动渲染，避免 5 张台账各写一遍表格与表单。
 *
 * 列定义字段：
 *   prop      字段名
 *   label     表头
 *   width/minWidth
 *   kind      text | date | money | asset | status | days | badge | bool | tags
 *   daysOf    当 kind=days 时，取哪个派生天数字段（负数为超期）
 *   warnDays  预警阈值（默认取字典；质保 30 天，检定/检验 15 天）
 *
 * 表单字段定义：
 *   prop / label / type(input|textarea|date|select|number|switch) / options / required / span / placeholder
 */

// ---------------------------------------------------------------------------
// 设备主台账
// ---------------------------------------------------------------------------
export const ASSET_COLUMNS = [
  { prop: 'asset_no', label: '台账编号', width: 150, kind: 'asset' },
  { prop: 'name', label: '设备名称', minWidth: 150 },
  { prop: 'model', label: '规格型号', minWidth: 140 },
  { prop: 'category', label: '类别', width: 90 },
  { prop: 'importance', label: '等级', width: 66, kind: 'badge' },
  { prop: 'location', label: '安装地点', minWidth: 130 },
  { prop: 'status', label: '当前状态', width: 92, kind: 'status' },
  { prop: 'warranty_end', label: '质保到期', width: 112, kind: 'date' },
  { prop: 'days_to_warranty', label: '距质保(天)', width: 104, kind: 'days', daysOf: 'days_to_warranty', warnDays: 30 },
  { prop: 'owner', label: '责任人', width: 90 },
  { prop: 'child_count', label: '子记录', width: 96, kind: 'childCount' },
]

export const ASSET_FORM_FIELDS = [
  { prop: 'asset_no', label: '台账编号', type: 'input', required: true, span: 12, placeholder: '如 TY-RS-HX-001' },
  { prop: 'finance_no', label: '资产编号', type: 'input', span: 12, placeholder: '与财务固定资产一致' },
  { prop: 'name', label: '设备名称', type: 'input', required: true, span: 12 },
  { prop: 'model', label: '规格型号', type: 'input', span: 12 },
  { prop: 'category', label: '设备类别', type: 'input', span: 12, placeholder: '换热器 / 水泵 / 阀门 / 仪表…' },
  { prop: 'importance', label: '重要等级', type: 'select', span: 12, optionsKey: 'importance' },
  { prop: 'is_special', label: '是否特种设备', type: 'switch', span: 12 },
  { prop: 'special_reg_no', label: '特种设备登记号', type: 'input', span: 12, placeholder: '是特种设备时必填' },
  { prop: 'location', label: '安装地点/站点', type: 'input', span: 12 },
  { prop: 'system_name', label: '所属系统', type: 'input', span: 12 },
  { prop: 'commission_date', label: '投用日期', type: 'date', span: 8 },
  { prop: 'warranty_start', label: '质保起始日', type: 'date', span: 8 },
  { prop: 'warranty_end', label: '质保到期日', type: 'date', span: 8 },
  { prop: 'design_life_years', label: '设计使用年限(年)', type: 'number', span: 8 },
  { prop: 'scrap_date', label: '预计报废日期', type: 'date', span: 8 },
  { prop: 'purchase_value', label: '采购原值(元)', type: 'number', span: 8 },
  { prop: 'supplier', label: '供应商', type: 'input', span: 12 },
  { prop: 'status', label: '当前状态', type: 'select', span: 12, optionsKey: 'asset_status' },
  { prop: 'owner', label: '属地责任人', type: 'input', span: 12 },
  { prop: 'remark', label: '备注', type: 'textarea', span: 24 },
]

// ---------------------------------------------------------------------------
// 四类子台账
// ---------------------------------------------------------------------------
export const CHILD_CONFIG = {
  events: {
    key: 'events',
    title: '设备动态事件台账',
    hint: '一条事件一行；计划完成日期进入 15 天窗口标橙、逾期未完成标红',
    columns: [
      { prop: 'asset_no', label: '台账编号', width: 140, kind: 'asset' },
      { prop: 'asset_name', label: '设备名称', minWidth: 130 },
      { prop: 'event_type', label: '事件类型', width: 110, kind: 'tag' },
      { prop: 'occur_date', label: '发生日期', width: 108, kind: 'date' },
      { prop: 'plan_date', label: '计划完成', width: 108, kind: 'date' },
      { prop: 'actual_date', label: '实际完成', width: 108, kind: 'date' },
      { prop: 'days_to_plan', label: '距计划(天)', width: 104, kind: 'days', daysOf: 'days_to_plan', warnDays: 15 },
      { prop: 'content', label: '事件简述', minWidth: 200, showOverflow: true },
      { prop: 'executor', label: '执行单位/人', minWidth: 130 },
      { prop: 'cost', label: '费用(元)', width: 100, kind: 'money' },
      { prop: 'accept_result', label: '验收结论', width: 96 },
      { prop: 'reporter', label: '提报人', width: 88 },
    ],
    fields: [
      { prop: 'asset_id', label: '所属设备', type: 'asset', required: true, span: 12 },
      { prop: 'event_type', label: '事件类型', type: 'select', required: true, span: 12, optionsKey: 'event_types' },
      { prop: 'occur_date', label: '事件发生日期', type: 'date', span: 8 },
      { prop: 'plan_date', label: '计划完成日期', type: 'date', span: 8 },
      { prop: 'actual_date', label: '实际完成日期', type: 'date', span: 8 },
      { prop: 'reporter', label: '提报人', type: 'input', span: 8 },
      { prop: 'executor', label: '执行单位/执行人', type: 'input', span: 8 },
      { prop: 'cert_no', label: '证书/报告编号', type: 'input', span: 8 },
      { prop: 'content', label: '事件简述内容', type: 'textarea', span: 24 },
      { prop: 'cost', label: '费用(元)', type: 'number', span: 8 },
      { prop: 'accept_result', label: '验收结论', type: 'select', span: 8, optionsKey: 'accept_results' },
      { prop: 'acceptor', label: '验收人', type: 'input', span: 8 },
      { prop: 'accept_date', label: '验收日期', type: 'date', span: 8 },
      { prop: 'corrective', label: '整改措施', type: 'textarea', span: 24 },
      { prop: 'attachment_path', label: '附件存储路径', type: 'input', span: 24 },
      { prop: 'remark', label: '备注', type: 'input', span: 24 },
    ],
  },
  meters: {
    key: 'meters',
    title: '计量器具检定台账',
    hint: '强检器具检定记录；有效期进入 15 天窗口标橙、超期标红',
    columns: [
      { prop: 'asset_no', label: '台账编号', width: 140, kind: 'asset' },
      { prop: 'asset_name', label: '设备名称', minWidth: 130 },
      { prop: 'name', label: '器具名称', minWidth: 130 },
      { prop: 'model', label: '规格型号', minWidth: 130 },
      { prop: 'accuracy', label: '精度等级', width: 90 },
      { prop: 'is_mandatory', label: '强检', width: 64, kind: 'bool' },
      { prop: 'cycle_months', label: '周期(月)', width: 84 },
      { prop: 'last_check_date', label: '上次检定', width: 108, kind: 'date' },
      { prop: 'valid_until', label: '有效期至', width: 108, kind: 'date' },
      { prop: 'days_to_expire', label: '距到期(天)', width: 104, kind: 'days', daysOf: 'days_to_expire', warnDays: 15 },
      { prop: 'org', label: '检定机构', minWidth: 150 },
      { prop: 'status', label: '状态', width: 84, kind: 'status' },
      { prop: 'owner', label: '责任人', width: 88 },
    ],
    fields: [
      { prop: 'asset_id', label: '所属设备', type: 'asset', required: true, span: 12 },
      { prop: 'name', label: '器具名称', type: 'input', required: true, span: 12 },
      { prop: 'model', label: '规格型号', type: 'input', span: 12 },
      { prop: 'accuracy', label: '精度等级', type: 'input', span: 12 },
      { prop: 'is_mandatory', label: '是否强检', type: 'switch', span: 8 },
      { prop: 'cycle_months', label: '检定周期(月)', type: 'number', span: 8 },
      { prop: 'status', label: '状态', type: 'select', span: 8, optionsKey: 'meter_status' },
      { prop: 'last_check_date', label: '上次检定日期', type: 'date', span: 8 },
      { prop: 'valid_until', label: '有效期至', type: 'date', span: 8 },
      { prop: 'cert_no', label: '证书编号', type: 'input', span: 8 },
      { prop: 'org', label: '检定机构', type: 'input', span: 12 },
      { prop: 'owner', label: '责任人', type: 'input', span: 12 },
      { prop: 'remark', label: '备注', type: 'input', span: 24 },
    ],
  },
  specials: {
    key: 'specials',
    title: '特种设备定期检验台账',
    hint: '锅炉/压力容器/压力管道法定检验；有效期进入 15 天窗口标橙、超期标红',
    columns: [
      { prop: 'asset_no', label: '台账编号', width: 140, kind: 'asset' },
      { prop: 'asset_name', label: '设备名称', minWidth: 130 },
      { prop: 'name', label: '检验设备', minWidth: 130 },
      { prop: 'reg_no', label: '注册编号', width: 140 },
      { prop: 'check_type', label: '检验类型', width: 104, kind: 'tag' },
      { prop: 'cycle_months', label: '周期(月)', width: 84 },
      { prop: 'last_check_date', label: '上次检验', width: 108, kind: 'date' },
      { prop: 'valid_until', label: '有效期至', width: 108, kind: 'date' },
      { prop: 'days_to_expire', label: '距到期(天)', width: 104, kind: 'days', daysOf: 'days_to_expire', warnDays: 15 },
      { prop: 'report_no', label: '报告编号', width: 120 },
      { prop: 'org', label: '检验机构', minWidth: 150 },
      { prop: 'status', label: '状态', width: 84, kind: 'status' },
      { prop: 'owner', label: '责任人', width: 88 },
    ],
    fields: [
      { prop: 'asset_id', label: '所属设备', type: 'asset', required: true, span: 12 },
      { prop: 'name', label: '检验设备名称', type: 'input', span: 12 },
      { prop: 'reg_no', label: '注册编号', type: 'input', span: 12 },
      { prop: 'check_type', label: '检验类型', type: 'select', required: true, span: 12, optionsKey: 'check_types' },
      { prop: 'cycle_months', label: '检验周期(月)', type: 'number', span: 8 },
      { prop: 'status', label: '状态', type: 'select', span: 8, optionsKey: 'special_status' },
      { prop: 'owner', label: '责任人', type: 'input', span: 8 },
      { prop: 'last_check_date', label: '上次检验日期', type: 'date', span: 8 },
      { prop: 'valid_until', label: '有效期至', type: 'date', span: 8 },
      { prop: 'report_no', label: '报告编号', type: 'input', span: 8 },
      { prop: 'org', label: '检验机构', type: 'input', span: 12 },
      { prop: 'remark', label: '备注', type: 'input', span: 24 },
    ],
  },
  spares: {
    key: 'spares',
    title: '备件更换明细台账',
    hint: '备件更换记录、数量、单价、换下旧件处置',
    columns: [
      { prop: 'asset_no', label: '台账编号', width: 140, kind: 'asset' },
      { prop: 'asset_name', label: '设备名称', minWidth: 130 },
      { prop: 'part_name', label: '备件名称', minWidth: 130 },
      { prop: 'model', label: '规格型号', minWidth: 120 },
      { prop: 'origin_type', label: '原厂/替代', width: 96 },
      { prop: 'replace_date', label: '更换时间', width: 108, kind: 'date' },
      { prop: 'qty', label: '数量', width: 80, kind: 'money' },
      { prop: 'unit_price', label: '单价(元)', width: 100, kind: 'money' },
      { prop: 'amount', label: '金额(元)', width: 104, kind: 'money' },
      { prop: 'supplier', label: '供应商', minWidth: 140 },
      { prop: 'old_disposal', label: '旧件处置', width: 104 },
      { prop: 'executor', label: '执行人', width: 88 },
    ],
    fields: [
      { prop: 'asset_id', label: '所属设备', type: 'asset', required: true, span: 12 },
      { prop: 'part_name', label: '备件名称', type: 'input', required: true, span: 12 },
      { prop: 'model', label: '规格型号', type: 'input', span: 12 },
      { prop: 'origin_type', label: '原厂/替代件', type: 'select', span: 12, optionsKey: 'part_origins' },
      { prop: 'replace_date', label: '更换时间', type: 'date', span: 8 },
      { prop: 'qty', label: '更换数量', type: 'number', span: 8 },
      { prop: 'unit_price', label: '单价(元)', type: 'number', span: 8 },
      { prop: 'amount', label: '金额(元)', type: 'number', span: 8, placeholder: '留空按数量×单价自动算' },
      { prop: 'old_disposal', label: '换下旧件处置', type: 'select', span: 8, optionsKey: 'old_part_disposals' },
      { prop: 'executor', label: '执行人', type: 'input', span: 8 },
      { prop: 'supplier', label: '供应商', type: 'input', span: 12 },
      { prop: 'reason', label: '更换原因', type: 'textarea', span: 24 },
      { prop: 'remark', label: '备注', type: 'input', span: 24 },
    ],
  },
}

/** 主台账状态色（模板里的 9 种状态分三组着色） */
export const ASSET_STATUS_TONE = {
  在用: 'ok',
  备用: 'muted',
  闲置: 'muted',
  封存: 'muted',
  维修中: 'warn',
  待修: 'warn',
  调拨中: 'brand',
  待报废: 'danger',
  已报废: 'danger',
}
