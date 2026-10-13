/**
 * 系统管理页面校验入口（task-6 自检用，非业务代码）
 * 逐个引入交付物，确保模板/脚本/SCSS 都能编译，且相对路径导入可解析。
 */
import AccountList from '../AccountList.vue'
import AuditLog from '../AuditLog.vue'
import DictList from '../DictList.vue'
import SupplierArchivePanel from '../SupplierArchivePanel.vue'
import SupplierImport from '../SupplierImport.vue'
import * as adminApi from '../adminApi'

export { AccountList, AuditLog, DictList, SupplierArchivePanel, SupplierImport, adminApi }

export default {
  AccountList,
  AuditLog,
  DictList,
  SupplierArchivePanel,
  SupplierImport,
  adminApi,
}
