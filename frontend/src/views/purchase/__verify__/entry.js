/**
 * 校验入口：只引入我方侧（purchase）的 4 个页面与 support.js。
 * 目的见 vite.config.mjs 顶部说明。
 */
import RfqEdit from '../RfqEdit.vue'
import RfqList from '../RfqList.vue'
import RfqProgress from '../RfqProgress.vue'
import RfqReport from '../RfqReport.vue'
import * as support from '../support.js'

export const PAGES = { RfqList, RfqEdit, RfqProgress, RfqReport }
export const HELPERS = support
export default PAGES
