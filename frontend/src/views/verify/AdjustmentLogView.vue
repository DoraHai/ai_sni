<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { fetchOperationRecords, syncOperationRecords } from '../../api/operations'
import {
  decideWritebackApproval, fetchWritebackApprovals, fetchWritebacks,
} from '../../api/writeback'
import { fetchActions } from '../../api/searchTerms'
import { writebackKeyword } from '../../api/keywords'
import { setAccountBudget, setAdgroupBid, setCampaignBudget } from '../../api/manage'
import { session } from '../../store/session'
import {
  ACTION_TYPES,
  actionAccountLabel as resolveActionAccountLabel,
  actionChangeText,
  actionResultNote,
  formatActionMoney,
} from '../../utils/actionLedger'
import { formatLocalDate, formatUtcTimestamp } from '../../utils/dateTime'

const router = useRouter()
const TENANT_ID = computed(() => session.tenantId) // 当前客户，顶栏切换器驱动

// 顶层视图：baidu=百度后台操作记录（只读同步）｜writeback=平台主动发起的回写台账
const mainView = ref('baidu')
// 回写台账二级切换：bid=出价回写（bid_writebacks）｜action=动作回写（否词/拓词/启停）
const wbSub = ref('bid')
const WB_STATUS = { success: '已写回', failed: '失败', dry_run: '演练（未真改）' }
const wbData = ref(null)
const wbLoading = ref(false)
const approvalData = ref(null)
const approvalLoading = ref(false)
const APPROVAL_ACTIONS = {
  keyword_bid: '关键词出价',
  adgroup_bid: '单元出价',
  campaign_budget: '计划预算',
  account_budget: '账户预算',
}
const APPROVAL_STATUS = {
  pending: '待确认', approved: '已确认', rejected: '已取消', consumed: '已执行',
}
async function loadWb() {
  wbLoading.value = true
  try {
    wbData.value = await fetchWritebacks({ tenantId: TENANT_ID.value })
  } catch (e) {
    error.value = e.message
  } finally {
    wbLoading.value = false
  }
}

async function loadApprovals() {
  approvalLoading.value = true
  try {
    approvalData.value = await fetchWritebackApprovals({ tenantId: TENANT_ID.value })
  } catch (e) {
    error.value = e.message
  } finally {
    approvalLoading.value = false
  }
}

async function decideApproval(row, decision) {
  try {
    const { value } = await ElMessageBox.prompt(
      decision === 'approved' ? '确认这项资金回写？' : '请填写取消原因',
      decision === 'approved' ? '本人确认' : '取消确认',
      { inputPlaceholder: '确认备注（可选）', confirmButtonText: '确认', cancelButtonText: '返回' },
    )
    await decideWritebackApproval(row.id, decision, value || null)
    ElMessage.success(decision === 'approved' ? '资金回写已确认' : '资金回写已取消')
    await loadApprovals()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error(e?.message || '确认失败')
  }
}

async function executeApproval(row) {
  try {
    await ElMessageBox.confirm('确认按已绑定参数执行？确认记录执行后不可重复使用。', '执行资金回写', {
      type: 'warning', confirmButtonText: '确认执行', cancelButtonText: '取消',
    })
    const p = row.payload || {}
    if (row.action_type === 'keyword_bid') {
      await writebackKeyword({ keywordId: p.keyword_id, tenantId: row.tenant_id, price: p.new_bid, approvalId: row.id })
    } else if (row.action_type === 'adgroup_bid') {
      await setAdgroupBid({ tenantId: row.tenant_id, adgroupId: p.adgroup_id, maxPrice: p.new_price, approvalId: row.id })
    } else if (row.action_type === 'campaign_budget') {
      await setCampaignBudget({ tenantId: row.tenant_id, campaignId: p.campaign_id, budget: p.new_budget, approvalId: row.id })
    } else {
      await setAccountBudget({
        tenantId: row.tenant_id,
        baiduAccountId: p.baidu_account_id,
        budget: p.new_budget,
        approvalId: row.id,
      })
    }
    ElMessage.success('执行请求已完成')
    await loadApprovals()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error(e?.message || '执行失败')
  }
}

// ===== 动作回写台账（加否词/转拓词/删否词/启停） =====
const actType = ref('')
const actData = ref(null)
const actLoading = ref(false)

async function loadActions() {
  actLoading.value = true
  try {
    actData.value = await fetchActions({ tenantId: TENANT_ID.value, actionType: actType.value })
  } catch (e) {
    error.value = e.message
  } finally {
    actLoading.value = false
  }
}

// 动作回写状态计数（前端按当前结果聚合，接口未给 status_counts）
const actCounts = computed(() => {
  const c = { success: 0, dry_run: 0, failed: 0 }
  for (const r of actData.value?.actions || []) {
    if (c[r.status] != null) c[r.status] += 1
  }
  return c
})

const fmtMoney = (v) => (v == null ? '—' : '¥' + Number(v).toFixed(2))

function actionAccountLabel(row) {
  return resolveActionAccountLabel(session.tenants, TENANT_ID.value, row)
}

// 关键词级记录解析到唯一 keyword_id 时可跳详情页（带溯源参数）
function gotoKeyword(row) {
  if (!row.keyword_id) return
  router.push({ path: `/monitor/keywords/${row.keyword_id}`, query: { from: 'adjustments' } })
}

const loading = ref(false)
const syncingOperations = ref(false)
const error = ref('')
const data = ref(null)

const PERIODS = [
  { code: 'month', label: '本月' },
  { code: '7d', label: '近 7 天' },
  { code: '30d', label: '近 30 天' },
  { code: 'all', label: '全部' },
]

const filters = reactive({
  period: 'month',
  optLevel: null, // 5=关键词 1=单元 2=计划
  optContent: '',
  q: '',
  overLimit: false,
  page: 1,
  pageSize: 20,
})

function periodRange() {
  const today = new Date()
  const daysAgo = (days) => {
    const value = new Date(today)
    value.setDate(value.getDate() - days)
    return value
  }
  if (filters.period === 'month') {
    return { startDate: formatLocalDate(new Date(today.getFullYear(), today.getMonth(), 1)), endDate: formatLocalDate(today) }
  }
  if (filters.period === '7d') {
    return { startDate: formatLocalDate(daysAgo(6)), endDate: formatLocalDate(today) }
  }
  if (filters.period === '30d') {
    return { startDate: formatLocalDate(daysAgo(29)), endDate: formatLocalDate(today) }
  }
  return {}
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await fetchOperationRecords({ tenantId: TENANT_ID.value, ...filters, ...periodRange() })
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function syncBaiduOperations() {
  if (syncingOperations.value || !TENANT_ID.value) return
  syncingOperations.value = true
  error.value = ''
  const tenantId = TENANT_ID.value
  const today = new Date()
  const start = new Date(today)
  start.setDate(start.getDate() - 2)
  try {
    const result = await syncOperationRecords({
      tenantId,
      startDate: formatLocalDate(start),
      endDate: formatLocalDate(today),
    })
    if (result.status !== 'ok') throw new Error(result.message || '百度操作记录同步失败')
    if (tenantId !== TENANT_ID.value) return
    await load()
    ElMessage.success(`已同步近 3 天百度操作记录，拉取 ${Number(result.records_fetched || 0)} 条`)
  } catch (e) {
    if (tenantId !== TENANT_ID.value) return
    const message = e.response?.data?.detail || e.message || '百度操作记录同步失败'
    error.value = message
    ElMessage.error(message)
  } finally {
    syncingOperations.value = false
  }
}

watch(
  () => [filters.period, filters.optLevel, filters.optContent, filters.overLimit],
  () => { filters.page = 1; load() },
)
let qTimer = null
watch(() => filters.q, () => {
  clearTimeout(qTimer)
  qTimer = setTimeout(() => { filters.page = 1; load() }, 400)
})
watch(() => [filters.page, filters.pageSize], load)

const fmtInt = (v) => (v == null ? '—' : Number(v).toLocaleString('zh-CN'))
// 百度 optTime 和数据库 server_default 时间按业务本地时间返回；只有同步时间是裸 UTC。
const fmtTime = (v) => (v ? v.slice(5, 16).replace('T', ' ') : '—')
const fmtSyncTime = (v) => formatUtcTimestamp(v, { short: true })

const statCards = computed(() => {
  const s = data.value?.summary
  if (!s) return []
  return [
    { label: '本月操作', value: fmtInt(s.month_total), sub: '百度后台全量抓取' },
    { label: '关键词级', value: fmtInt(s.month_keyword_level), sub: '出价 / 启停 / 匹配模式' },
    { label: '系数与策略级', value: fmtInt(s.month_coef_level), sub: '计划 / 单元层操作' },
    { label: '⚡ 超 20% 上限', value: fmtInt(s.month_over_limit), sub: '单次调价硬上限覆盖', danger: s.month_over_limit > 0 },
  ]
})

function changeText(row) {
  if (!row.old_value && !row.new_value) return '—'
  const oldV = row.old_value ?? '—'
  const newV = row.new_value ?? '—'
  return `${oldV} → ${newV}`
}

// 切到回写台账 tab 时按需加载当前二级视图
watch(mainView, (v) => { if (v === 'writeback') loadWbSub() })
// 二级切换 / 动作类型筛选变化时按需加载
watch(wbSub, loadWbSub)
watch(actType, () => { if (mainView.value === 'writeback' && wbSub.value === 'action') loadActions() })

function loadWbSub() {
  if (wbSub.value === 'bid') loadWb()
  else if (wbSub.value === 'action') loadActions()
  else loadApprovals()
}

// 顶栏切换客户后重新拉当前视图的数
watch(TENANT_ID, () => {
  if (mainView.value === 'writeback') loadWbSub()
  else { filters.page = 1; load() }
})

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <div class="page-header">
      <div>
        <div class="page-title">调价台账</div>
        <div class="page-desc">
          数据源：百度 getOperationRecord（含百度后台直接操作）· 每日 02:00 自动增量同步，可手动同步近 3 天
          <template v-if="data?.last_synced_at"> · 同步于 {{ fmtSyncTime(data.last_synced_at) }}</template>
        </div>
      </div>
      <div class="header-actions">
        <el-button
          v-if="mainView === 'baidu' && session.canEdit('verify.adjustments')"
          :loading="syncingOperations"
          @click="syncBaiduOperations"
        >同步百度记录</el-button>
        <el-button
          v-if="session.canView('verify.adjustments')"
          type="warning" plain
          @click="router.push({ path: '/verify/pending', query: { mode: 'queue' } })"
        >人工对账队列</el-button>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" style="margin-bottom: 14px" />

    <!-- 顶层视图切换：百度后台操作记录 / 平台主动回写台账 -->
    <div class="view-tabs main-tabs">
      <div class="view-tab" :class="{ active: mainView === 'baidu' }" @click="mainView = 'baidu'">百度操作记录</div>
      <div class="view-tab" :class="{ active: mainView === 'writeback' }" @click="mainView = 'writeback'">平台回写台账</div>
    </div>

    <!-- ===== 百度后台操作记录（只读同步） ===== -->
    <template v-if="mainView === 'baidu'">
    <!-- 统计卡 -->
    <div class="stat-grid">
      <div v-for="c in statCards" :key="c.label" class="stat-card" :class="{ danger: c.danger }">
        <div class="stat-label">{{ c.label }}</div>
        <div class="stat-value">{{ c.value }}</div>
        <div class="stat-sub">{{ c.sub }}</div>
      </div>
    </div>

    <!-- 筛选行 -->
    <div class="filter-row">
      <div class="view-tabs">
        <div
          v-for="p in PERIODS"
          :key="p.code"
          class="view-tab"
          :class="{ active: filters.period === p.code }"
          @click="filters.period = p.code"
        >{{ p.label }}</div>
      </div>
      <el-select v-model="filters.optLevel" placeholder="全部层级" clearable style="width: 130px">
        <el-option label="关键词" :value="5" />
        <el-option label="单元" :value="1" />
        <el-option label="计划" :value="2" />
      </el-select>
      <el-select v-model="filters.optContent" placeholder="全部操作内容" clearable style="width: 170px">
        <el-option
          v-for="o in data?.content_options || []"
          :key="o.code"
          :label="o.label"
          :value="o.code"
        />
      </el-select>
      <el-input v-model="filters.q" placeholder="搜索关键词 / 对象" clearable style="width: 200px" />
      <el-checkbox v-model="filters.overLimit" class="over-limit-check">⚡ 只看超 20% 上限</el-checkbox>
    </div>

    <!-- 台账表 -->
    <div class="table-panel">
      <el-table :data="data?.records || []" class="kw-table" row-key="id">
        <el-table-column label="时间" width="110">
          <template #default="{ row }"><span class="num">{{ fmtTime(row.opt_time) }}</span></template>
        </el-table-column>
        <el-table-column label="对象" min-width="190">
          <template #default="{ row }">
            <div
              class="kw-cell-name"
              :class="{ 'kw-link': row.keyword_id }"
              @click="gotoKeyword(row)"
            >
              {{ row.opt_obj || '—' }}<span v-if="row.keyword_id" class="kw-arrow">›</span>
            </div>
            <div class="kw-cell-sub">
              {{ row.campaign_name || '—' }}<template v-if="row.adgroup_name"> / {{ row.adgroup_name }}</template>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作类型" width="150">
          <template #default="{ row }">
            <span class="content-pill" :class="'lv-' + row.opt_level">{{ row.content_label }}</span>
            <span class="kw-cell-sub" style="margin-left: 4px">{{ row.type_label }}</span>
          </template>
        </el-table-column>
        <el-table-column label="层级" width="76" align="center">
          <template #default="{ row }">{{ row.level_label || '—' }}</template>
        </el-table-column>
        <el-table-column label="调整内容" min-width="220">
          <template #default="{ row }">
            <span class="change-text">{{ changeText(row) }}</span>
            <span
              v-if="row.change"
              class="change-pct"
              :class="{ up: row.change.pct > 0, down: row.change.pct < 0, over: row.change.over_limit }"
            >
              {{ row.change.pct > 0 ? '+' : '' }}{{ row.change.pct }}%<template v-if="row.change.over_limit"> ⚡超上限</template>
            </span>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="96">
          <template #default="{ row }"><span class="source-pill">{{ row.source }}</span></template>
        </el-table-column>
        <template #empty>
          <div class="empty-line">当前筛选条件下没有操作记录。首次使用请先执行操作记录回灌（admin/sync-operation-records）。</div>
        </template>
      </el-table>
      <div class="table-footer">
        <span>共 {{ fmtInt(data?.total || 0) }} 条</span>
        <el-pagination
          v-model:current-page="filters.page"
          v-model:page-size="filters.pageSize"
          :total="data?.total || 0"
          :page-sizes="[10, 20, 50, 100]"
          layout="sizes, prev, pager, next, jumper"
          background
          small
        />
      </div>
    </div>
    </template>

    <!-- ===== 平台主动回写台账（出价回写 / 动作回写） ===== -->
    <template v-else>
      <!-- 二级切换：出价回写 ｜ 动作回写（否词/拓词/启停） -->
      <div class="filter-row">
        <div class="view-tabs">
          <div class="view-tab" :class="{ active: wbSub === 'bid' }" @click="wbSub = 'bid'">出价回写</div>
          <div class="view-tab" :class="{ active: wbSub === 'action' }" @click="wbSub = 'action'">动作回写</div>
          <div class="view-tab" :class="{ active: wbSub === 'approval' }" @click="wbSub = 'approval'">确认记录</div>
        </div>
        <el-select
          v-if="wbSub === 'action'"
          v-model="actType"
          placeholder="全部动作"
          style="width: 140px"
        >
          <el-option v-for="t in ACTION_TYPES" :key="t.code" :label="t.label" :value="t.code" />
        </el-select>
      </div>

      <!-- 出价回写（updateWord 留痕） -->
      <div v-if="wbSub === 'bid'" v-loading="wbLoading">
        <el-alert
          type="info"
          :closable="false"
          show-icon
          style="margin-bottom: 12px"
          title="平台主动发起的出价回写记录。「演练（未真改）」表示当前为 dry-run 演练模式，仅记台账、未真改线上出价。"
        />
        <div class="wb-counts">
          <span class="wb-count ok">已写回 {{ wbData?.status_counts?.success || 0 }}</span>
          <span class="wb-count dry">演练 {{ wbData?.status_counts?.dry_run || 0 }}</span>
          <span class="wb-count fail">失败 {{ wbData?.status_counts?.failed || 0 }}</span>
        </div>
        <div class="table-panel">
          <el-table :data="wbData?.writebacks || []" class="kw-table" row-key="id">
            <el-table-column label="时间" width="120">
              <template #default="{ row }"><span class="num">{{ fmtTime(row.created_at) }}</span></template>
            </el-table-column>
            <el-table-column label="关键词" min-width="190">
              <template #default="{ row }">
                <div class="kw-cell-name">{{ row.keyword || ('#' + row.keyword_id) }}</div>
                <div class="kw-cell-sub">{{ row.campaign_name || '—' }}</div>
              </template>
            </el-table-column>
            <el-table-column label="出价调整" min-width="180">
              <template #default="{ row }">
                <span class="change-text">{{ fmtMoney(row.old_bid) }} → {{ fmtMoney(row.new_bid) }}</span>
                <span
                  v-if="row.change_pct != null"
                  class="change-pct"
                  :class="{ up: row.change_pct > 0, down: row.change_pct < 0 }"
                >{{ row.change_pct > 0 ? '+' : '' }}{{ row.change_pct }}%</span>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="120" align="center">
              <template #default="{ row }">
                <span class="wb-pill" :class="row.status">{{ row.status_label || WB_STATUS[row.status] || row.status }}</span>
              </template>
            </el-table-column>
            <el-table-column label="操作人" width="110">
              <template #default="{ row }">{{ row.operator_name || '—' }}</template>
            </el-table-column>
            <el-table-column label="说明" min-width="160">
              <template #default="{ row }"><span class="kw-cell-sub">{{ row.error_msg || '—' }}</span></template>
            </el-table-column>
            <template #empty>
              <div class="empty-line">还没有回写记录。去「关键词工作台」对 AI 建议点「回写出价」即可在此留痕。</div>
            </template>
          </el-table>
        </div>
      </div>

      <!-- 动作回写（否词 / 拓词 / 启停，writeback_actions 留痕） -->
      <div v-else-if="wbSub === 'action'" v-loading="actLoading">
        <el-alert
          type="info"
          :closable="false"
          show-icon
          style="margin-bottom: 12px"
          title="平台主动发起的加否词 / 转拓词 / 删否词 / 启停记录。「演练（未真改）」表示当前为 dry-run 演练模式，仅记台账、未真改线上账户。"
        />
        <div class="wb-counts">
          <span class="wb-count ok">已执行 {{ actCounts.success }}</span>
          <span class="wb-count dry">演练 {{ actCounts.dry_run }}</span>
          <span class="wb-count fail">失败 {{ actCounts.failed }}</span>
        </div>
        <div class="table-panel">
          <el-table :data="actData?.actions || []" class="kw-table" row-key="id">
            <el-table-column label="时间" width="120">
              <template #default="{ row }"><span class="num">{{ fmtTime(row.created_at) }}</span></template>
            </el-table-column>
            <el-table-column label="动作" width="90">
              <template #default="{ row }">
                <span class="act-pill" :class="row.action_type">{{ row.action_label }}</span>
              </template>
            </el-table-column>
            <el-table-column label="词 / 对象" min-width="220">
              <template #default="{ row }">
                <div class="kw-cell-name">{{ row.word || '—' }}</div>
                <div class="kw-cell-sub">
                  {{ actionAccountLabel(row) }}<template v-if="row.campaign_name"> / {{ row.campaign_name }}</template><template v-if="row.adgroup_name"> / {{ row.adgroup_name }}</template>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="匹配 / 变更" min-width="170">
              <template #default="{ row }">
                <span v-if="row.match_label" class="content-pill lv-5">{{ row.match_label }}</span>
                <span v-if="row.price != null" class="change-text" style="margin-left: 6px">{{ formatActionMoney(row.price) }}</span>
                <span v-if="actionChangeText(row)" class="change-text">{{ actionChangeText(row) }}</span>
                <span v-if="!row.match_label && row.price == null && !actionChangeText(row)" class="dim">—</span>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="150" align="center">
              <template #default="{ row }">
                <span class="wb-pill" :class="row.status">{{ row.status_label || WB_STATUS[row.status] || row.status }}</span>
                <div class="kw-cell-sub">{{ row.execution_mode_label || (row.dry_run ? '演练（未修改百度）' : '真实执行') }}</div>
              </template>
            </el-table-column>
            <el-table-column label="操作人" width="110">
              <template #default="{ row }">{{ row.operator_name || '—' }}</template>
            </el-table-column>
            <el-table-column label="说明" min-width="160">
              <template #default="{ row }"><span class="kw-cell-sub">{{ actionResultNote(row) }}</span></template>
            </el-table-column>
            <template #empty>
              <div class="empty-line">还没有动作回写记录。去「搜索词报告」加否词 / 转拓词，或「关键词工作台」批量启停即可在此留痕。</div>
            </template>
          </el-table>
        </div>
      </div>

      <!-- 高风险资金回写确认审计 -->
      <div v-else v-loading="approvalLoading">
        <el-alert
          type="warning"
          :closable="false"
          show-icon
          style="margin-bottom: 12px"
          title="关键词/单元出价及计划/账户预算在操作页确认执行时，会自动生成、绑定并消费一次性确认记录；无需在此重复创建。本页保留完整审计记录，并兼容处理历史待确认记录。"
        />
        <div class="table-panel">
          <el-table :data="approvalData?.approvals || []" class="kw-table" row-key="id">
            <el-table-column label="申请时间" width="120">
              <template #default="{ row }"><span class="num">{{ fmtTime(row.created_at) }}</span></template>
            </el-table-column>
            <el-table-column label="资金动作" width="120">
              <template #default="{ row }">{{ APPROVAL_ACTIONS[row.action_type] || row.action_type }}</template>
            </el-table-column>
            <el-table-column label="确认参数" min-width="240">
              <template #default="{ row }"><code>{{ JSON.stringify(row.payload) }}</code></template>
            </el-table-column>
            <el-table-column label="状态" width="100" align="center">
              <template #default="{ row }">
                <span class="wb-pill" :class="row.status">{{ APPROVAL_STATUS[row.status] || row.status }}</span>
              </template>
            </el-table-column>
            <el-table-column label="操作用户" width="110">
              <template #default="{ row }">#{{ row.requested_by }}</template>
            </el-table-column>
            <el-table-column label="备注" min-width="150">
              <template #default="{ row }">{{ row.decision_note || row.request_note || '—' }}</template>
            </el-table-column>
            <el-table-column label="操作" width="150" fixed="right">
              <template #default="{ row }">
                <template v-if="row.status === 'pending'">
                  <el-button size="small" type="success" @click="decideApproval(row, 'approved')">确认</el-button>
                  <el-button size="small" type="danger" plain @click="decideApproval(row, 'rejected')">取消</el-button>
                </template>
                <el-button v-else-if="row.status === 'approved'" size="small" type="primary" @click="executeApproval(row)">执行</el-button>
                <span v-else class="dim">已处理</span>
              </template>
            </el-table-column>
            <template #empty><div class="empty-line">当前客户没有资金回写确认记录。</div></template>
          </el-table>
        </div>
      </div>
    </template>

  </div>
</template>

<style scoped>
.page-header { margin-bottom: 14px; display: flex; justify-content: space-between; align-items: flex-end; }
.page-title { font-size: 20px; font-weight: 600; color: var(--sem-text); }
.page-desc { font-size: 12px; color: var(--sem-text-sub); margin-top: 4px; }
.header-actions { display: flex; gap: 8px; align-items: center; }

.stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 14px; }
@media (max-width: 1100px) { .stat-grid { grid-template-columns: repeat(2, 1fr); } }
.stat-card { background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; padding: 14px 16px; }
.stat-card.danger { border-left: 4px solid var(--sem-danger); }
.stat-label { font-size: 11px; color: var(--sem-text-sub); }
.stat-value { font-size: 22px; font-weight: 700; margin-top: 8px; font-variant-numeric: tabular-nums; }
.stat-card.danger .stat-value { color: var(--sem-danger); }
.stat-sub { font-size: 11px; color: #9ca3af; margin-top: 6px; }

.filter-row { display: flex; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; align-items: center; }
.view-tabs { display: inline-flex; gap: 4px; background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; padding: 4px; }
.view-tab { padding: 6px 14px; border-radius: 5px; font-size: 12px; cursor: pointer; color: var(--sem-text-sub); font-weight: 500; user-select: none; }
.view-tab:hover { background: #f9fafb; color: var(--sem-primary); }
.view-tab.active { background: #eff4fb; color: var(--sem-primary); }
.over-limit-check :deep(.el-checkbox__label) { font-size: 12px; color: #ba7517; }

.table-panel { background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; overflow: hidden; }
.kw-table { font-size: 12px; }
.kw-table :deep(th.el-table__cell) {
  background: #fafbfc; font-weight: 500; color: var(--sem-text-sub);
  font-size: 11px; padding: 6px 0; white-space: nowrap;
}
.kw-table :deep(td.el-table__cell) { padding: 8px 0; }
.kw-table :deep(.el-table__row:hover > td.el-table__cell) { background: #fafbfc; }
.kw-cell-name { font-weight: 500; color: var(--sem-text); }
.kw-cell-name.kw-link { color: var(--sem-primary); cursor: pointer; }
.kw-cell-name.kw-link:hover { text-decoration: underline; }
.kw-arrow { margin-left: 3px; font-weight: 700; }
.kw-cell-sub { font-size: 10px; color: #9ca3af; margin-top: 2px; }
.num { font-variant-numeric: tabular-nums; }
.dim { color: #9ca3af; }

.content-pill { font-size: 10px; padding: 1px 7px; border-radius: 10px; font-weight: 600; display: inline-block; }
.content-pill.lv-5 { background: #eff4fb; color: var(--sem-primary); }
.content-pill.lv-1 { background: #e5f4ed; color: var(--sem-success); }
.content-pill.lv-2 { background: #f2ebfb; color: #6b47b5; }

.change-text { font-variant-numeric: tabular-nums; color: var(--sem-text); }
.change-pct { font-size: 11px; font-weight: 600; margin-left: 8px; font-variant-numeric: tabular-nums; }
.change-pct.up { color: var(--sem-danger); }
.change-pct.down { color: var(--sem-success); }
.change-pct.over { color: #fff; background: var(--sem-danger); padding: 1px 6px; border-radius: 3px; }

.source-pill { font-size: 10px; padding: 1px 7px; border-radius: 10px; background: #fef1e1; color: #ba7517; }

.main-tabs { margin-bottom: 14px; }
.wb-counts { display: flex; gap: 10px; margin-bottom: 12px; }
.wb-count { font-size: 12px; padding: 4px 12px; border-radius: 14px; background: #f3f4f6; color: var(--sem-text-sub); font-weight: 500; }
.wb-count.ok { background: #e5f4ed; color: var(--sem-success); }
.wb-count.dry { background: #fef1e1; color: #ba7517; }
.wb-count.fail { background: #fdeaea; color: var(--sem-danger); }
.wb-pill { font-size: 10px; padding: 1px 8px; border-radius: 10px; font-weight: 600; display: inline-block; }
.wb-pill.success { background: #e5f4ed; color: var(--sem-success); }
.wb-pill.dry_run { background: #fef1e1; color: #ba7517; }
.wb-pill.failed { background: #fdeaea; color: var(--sem-danger); }

.act-pill { font-size: 10px; padding: 1px 8px; border-radius: 10px; font-weight: 600; display: inline-block; }
.act-pill.negative { background: #fdeaea; color: var(--sem-danger); }
.act-pill.remove_negative { background: #f3f4f6; color: var(--sem-text-sub); }
.act-pill.add_word { background: #e5f4ed; color: var(--sem-success); }
.act-pill.pause { background: #fef1e1; color: #ba7517; }
.act-pill.enable { background: #eff4fb; color: var(--sem-primary); }

.empty-line { font-size: 12px; color: #9ca3af; padding: 22px 0; }
.table-footer {
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 16px; background: #fafbfc; border-top: 1px solid #f3f4f6;
  font-size: 12px; color: var(--sem-text-sub);
}
</style>
