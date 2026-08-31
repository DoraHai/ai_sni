<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { addNegative, expandKeyword, fetchSearchTerms, syncSearchTerms } from '../../api/searchTerms'
import { session } from '../../store/session'
import { formatUtcTimestamp } from '../../utils/dateTime'

const TENANT_ID = computed(() => session.tenantId)
const loading = ref(false)
const syncing = ref(false)
const error = ref('')
const data = ref(null)
const emptyDiagnosis = computed(() => {
  if (!data.value || data.value.total) return null
  if (!data.value.window?.synced_at) return '搜索词尚未同步。该数据来自百度读取，与回写开关无关；请执行近 30 天同步。'
  return `最近已于 ${fmtTime(data.value.window.synced_at)} 完成读取，但当前窗口或筛选条件下没有搜索词。`
})

const STATUS_TABS = [
  { code: '', label: '全部' },
  { code: 'not_added', label: '未加成关键词' },
  { code: 'added', label: '已加成关键词' },
]

const filters = reactive({
  status: '',
  hasClick: null, // null=全部 true=有点击 false=零点击
  q: '',
  page: 1,
  pageSize: 50,
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await fetchSearchTerms({ tenantId: TENANT_ID.value, ...filters })
  } catch (e) {
    error.value = e.response?.data?.detail || e.message
  } finally {
    loading.value = false
  }
}

async function runSync() {
  syncing.value = true
  try {
    const res = await syncSearchTerms({ tenantId: TENANT_ID.value, days: 30 })
    ElMessage.success(`已同步 ${res.synced} 条搜索词（${res.window.start} ~ ${res.window.end}）`)
    filters.page = 1
    await load()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  } finally {
    syncing.value = false
  }
}

watch(() => [filters.status, filters.hasClick], () => { filters.page = 1; load() })
let qTimer = null
watch(() => filters.q, () => { clearTimeout(qTimer); qTimer = setTimeout(() => { filters.page = 1; load() }, 400) })
watch(() => [filters.page, filters.pageSize], load)
watch(TENANT_ID, () => { filters.page = 1; load() })
onMounted(load)

const fmtInt = (v) => (v == null ? '—' : Number(v).toLocaleString('zh-CN'))
const fmtMoney = (v) => (v == null ? '—' : '¥' + Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 2 }))
const fmtPct = (v) => (v == null ? '—' : Number(v).toFixed(2) + '%')
const fmtTime = (v) => formatUtcTimestamp(v)
const negDialogVisible = ref(false)
const negForm = ref({
  word: '',
  scope: 'adgroup',
  matchMode: 'exact',
  adgroupId: null,
  adgroupName: '',
  campaignId: null,
  campaignName: '',
})

// C 辅助：未加成关键词 + 有展现 + 零点击 → 疑似可否（烧展现没点击）
function suspectNegative(row) {
  return !row.is_added && (row.impression || 0) >= 20 && (row.click || 0) === 0
}

function dryRunTip(res, okMsg) {
  if (res.dry_run) ElMessage.warning('演练模式：已记入台账，未真改线上（管理员开启真写后方可生效）')
  else ElMessage.success(okMsg)
}

function addNeg(row) {
  if (!row.adgroup_id && !row.campaign_id) {
    return ElMessage.warning('该搜索词无所属计划/单元，无法加否词')
  }
  negForm.value = {
    word: row.query_word,
    scope: row.adgroup_id ? 'adgroup' : 'campaign',
    matchMode: 'exact',
    adgroupId: row.adgroup_id,
    adgroupName: row.adgroup_name,
    campaignId: row.campaign_id,
    campaignName: row.campaign_name,
  }
  negDialogVisible.value = true
}

async function submitNegative() {
  const f = negForm.value
  if (f.scope === 'adgroup' && !f.adgroupId) return ElMessage.warning('单元级否词需要单元')
  if (f.scope === 'campaign' && !f.campaignId) return ElMessage.warning('计划级否词需要计划')
  try {
    const res = await addNegative({
      tenantId: TENANT_ID.value,
      word: f.word,
      scope: f.scope,
      adgroupId: f.scope === 'adgroup' ? f.adgroupId : undefined,
      campaignId: f.scope === 'campaign' ? f.campaignId : undefined,
      matchMode: f.matchMode,
    })
    dryRunTip(res, '已加否词')
    negDialogVisible.value = false
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  }
}

async function expand(row) {
  if (!row.adgroup_id) return ElMessage.warning('该搜索词无所属单元，无法转拓词')
  let value
  try {
    const r = await ElMessageBox.prompt(
      `把「${row.query_word}」加成关键词到单元「${row.adgroup_name || row.adgroup_id}」（短语匹配）。\n请输入出价（元）：`,
      '转拓词', {
        confirmButtonText: '确认转拓词', cancelButtonText: '取消',
        inputPattern: /^\d+(\.\d{1,2})?$/, inputErrorMessage: '请输入有效出价（最多两位小数）',
      },
    )
    value = r.value
  } catch { return }
  try {
    const res = await expandKeyword({ tenantId: TENANT_ID.value, word: row.query_word, adgroupId: row.adgroup_id, price: Number(value), matchMode: 'phrase' })
    dryRunTip(res, '已转为关键词')
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  }
}

const statCards = computed(() => {
  const s = data.value?.summary
  if (!s) return []
  return [
    { label: '搜索词数', value: fmtInt(s.terms) },
    { label: '有点击', value: fmtInt(s.with_click), sub: '带来过点击的词' },
    { label: '展现合计', value: fmtInt(s.impression) },
    { label: '点击合计', value: fmtInt(s.click) },
    { label: '消费合计', value: fmtMoney(s.cost) },
  ]
})
</script>

<template>
  <div v-loading="loading">
    <div class="page-header">
      <div>
        <div class="page-title">搜索词报告</div>
        <div class="page-desc">
          数据源：百度搜索词报告（reportType 2307838，最大 91 天窗口）
          <template v-if="data?.window?.start"> · 窗口 {{ data.window.start }} ~ {{ data.window.end }}</template>
          <template v-if="data?.window?.synced_at"> · 同步于 {{ fmtTime(data.window.synced_at) }}</template>
        </div>
      </div>
      <el-button type="primary" :loading="syncing" @click="runSync">同步搜索词（近 30 天）</el-button>
    </div>
    <el-alert v-if="emptyDiagnosis" type="warning" :title="emptyDiagnosis" :closable="false" show-icon style="margin-bottom: 12px" />

    <el-alert v-if="error" :title="error" type="error" :closable="false" style="margin-bottom: 14px" />

    <div class="stat-grid">
      <div v-for="c in statCards" :key="c.label" class="stat-card">
        <div class="stat-label">{{ c.label }}</div>
        <div class="stat-value">{{ c.value }}</div>
        <div class="stat-sub">{{ c.sub || '' }}</div>
      </div>
    </div>

    <div class="filter-row">
      <div class="view-tabs">
        <div
          v-for="t in STATUS_TABS"
          :key="t.code"
          class="view-tab"
          :class="{ active: filters.status === t.code }"
          @click="filters.status = t.code"
        >{{ t.label }}</div>
      </div>
      <el-select v-model="filters.hasClick" placeholder="点击 · 全部" clearable style="width: 140px">
        <el-option label="有点击" :value="true" />
        <el-option label="零点击" :value="false" />
      </el-select>
      <el-input v-model="filters.q" placeholder="搜索词" clearable style="width: 220px" prefix-icon="Search" />
    </div>

    <div class="table-panel">
      <el-table :data="data?.search_terms || []" class="kw-table" row-key="id" :fit="true">
        <el-table-column label="搜索词" width="190">
          <template #header>
            <span class="th-help">
              搜索词
              <el-tooltip placement="top" content="用户实际在百度里搜索的词；下方的匹配关键词，是账户里触发这次展示的关键词。">
                <span class="help-dot">?</span>
              </el-tooltip>
            </span>
          </template>
          <template #default="{ row }">
            <div class="kw-cell-name">
              {{ row.query_word }}
              <span v-if="suspectNegative(row)" class="susp-pill" title="未加成关键词、有展现但零点击，疑似可否">疑似可否</span>
            </div>
            <el-tooltip
              placement="top"
              :disabled="!row.trigger_keyword"
              :content="`用户搜了「${row.query_word}」，系统匹配到账户关键词「${row.trigger_keyword}」后展示广告。`"
            >
              <div class="kw-cell-sub">
                <span class="sub-label">匹配关键词：</span>{{ row.trigger_keyword || '—' }}
              </div>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="88" align="center">
          <template #default="{ row }">
            <span class="st-pill" :class="row.is_added ? 'added' : 'notadded'">{{ row.status_label }}</span>
          </template>
        </el-table-column>
        <el-table-column label="计划 / 单元" width="160">
          <template #default="{ row }">
            <div class="plan-line">{{ row.campaign_name || '—' }}</div>
            <div class="kw-cell-sub">{{ row.adgroup_name || '—' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="展现" width="80" align="right">
          <template #default="{ row }"><span class="num">{{ fmtInt(row.impression) }}</span></template>
        </el-table-column>
        <el-table-column label="点击" width="70" align="right">
          <template #default="{ row }">
            <span class="num" :class="{ zero: !row.click }">{{ fmtInt(row.click) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="点击率" width="84" align="right">
          <template #header>
            <span title="CTR = 点击 ÷ 展现">点击率</span>
          </template>
          <template #default="{ row }"><span class="num">{{ fmtPct(row.ctr) }}</span></template>
        </el-table-column>
        <el-table-column label="点击成本" width="96" align="right">
          <template #header>
            <span title="CPC = 消费 ÷ 点击">点击成本</span>
          </template>
          <template #default="{ row }"><span class="num">{{ fmtMoney(row.cpc) }}</span></template>
        </el-table-column>
        <el-table-column label="消费" width="92" align="right">
          <template #default="{ row }"><span class="num">{{ fmtMoney(row.cost) }}</span></template>
        </el-table-column>
        <el-table-column label="转化" width="86" align="right">
          <template #header>
            <span title="CVR = 转化 ÷ 点击">转化</span>
          </template>
          <template #default="{ row }">
            <span class="num" :class="{ zero: !row.conversions }">{{ fmtInt(row.conversions) }}</span>
            <div class="kw-cell-sub">{{ fmtPct(row.cvr) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="156">
          <template #default="{ row }">
            <div class="search-term-actions">
              <el-button class="search-action is-negative" size="small" :disabled="!row.adgroup_id && !row.campaign_id" @click="addNeg(row)">待回写否词</el-button>
              <el-button class="search-action is-expand" size="small" :disabled="row.is_added || !row.adgroup_id" @click="expand(row)">待回写关键词</el-button>
            </div>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-line">{{ emptyDiagnosis || '当前筛选条件下没有搜索词。' }}</div>
        </template>
      </el-table>
      <div class="table-footer">
        <span>共 {{ fmtInt(data?.total || 0) }} 条</span>
        <el-pagination
          v-model:current-page="filters.page"
          v-model:page-size="filters.pageSize"
          :total="data?.total || 0"
          :page-sizes="[20, 50, 100, 200]"
          layout="sizes, prev, pager, next, jumper"
          background
          small
        />
      </div>
    </div>

    <el-dialog v-model="negDialogVisible" title="加入待回写否词" width="420px">
      <div class="neg-form">
        <p>将「{{ negForm.word }}」加为否词</p>

        <label>作用范围</label>
        <el-radio-group v-model="negForm.scope" class="neg-radio-stack">
          <el-radio label="adgroup" :disabled="!negForm.adgroupId">
            单元级（{{ negForm.adgroupName || negForm.adgroupId || '无单元' }}）
          </el-radio>
          <el-radio label="campaign" :disabled="!negForm.campaignId">
            计划级（{{ negForm.campaignName || negForm.campaignId || '无计划' }}）
          </el-radio>
        </el-radio-group>

        <label>匹配方式</label>
        <el-radio-group v-model="negForm.matchMode">
          <el-radio label="exact">精确否</el-radio>
          <el-radio label="phrase">短语否</el-radio>
        </el-radio-group>

        <div class="neg-tip">当前只读演练：仅加入待回写台账，不修改百度账户。</div>
      </div>
      <template #footer>
        <el-button @click="negDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitNegative">加入待回写</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-header { margin-bottom: 14px; display: flex; justify-content: space-between; align-items: flex-end; }
.page-title { font-size: 20px; font-weight: 600; color: var(--sem-text); }
.page-desc { font-size: 12px; color: var(--sem-text-sub); margin-top: 4px; }

.stat-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin-bottom: 14px; }
@media (max-width: 1100px) { .stat-grid { grid-template-columns: repeat(2, 1fr); } }
.stat-card { background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; padding: 14px 16px; }
.stat-label { font-size: 11px; color: var(--sem-text-sub); }
.stat-value { font-size: 22px; font-weight: 700; margin-top: 8px; font-variant-numeric: tabular-nums; }
.stat-sub { font-size: 11px; color: #9ca3af; margin-top: 6px; }

.filter-row { display: flex; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; align-items: center; }
.view-tabs { display: inline-flex; gap: 4px; background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; padding: 4px; }
.view-tab { padding: 6px 14px; border-radius: 5px; font-size: 12px; cursor: pointer; color: var(--sem-text-sub); font-weight: 500; user-select: none; }
.view-tab:hover { background: #f9fafb; color: var(--sem-primary); }
.view-tab.active { background: #eff4fb; color: var(--sem-primary); }

.table-panel { background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; overflow: hidden; }
.kw-table { font-size: 12px; }
.kw-table :deep(th.el-table__cell) { background: #fafbfc; font-weight: 500; color: var(--sem-text-sub); font-size: 11px; padding: 6px 0; white-space: nowrap; }
.kw-table :deep(td.el-table__cell) { padding: 8px 0; }
.th-help { display: inline-flex; align-items: center; gap: 4px; }
.help-dot {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #eff4fb;
  color: var(--sem-primary);
  font-size: 10px;
  line-height: 1;
  cursor: help;
}
.kw-cell-name { font-weight: 500; color: var(--sem-text); }
.kw-cell-sub { font-size: 10px; color: #9ca3af; margin-top: 2px; }
.sub-label { color: #6b7280; }
.plan-line { color: var(--sem-text); }
.num { font-variant-numeric: tabular-nums; }
.num.zero { color: #c0c4cc; }

.st-pill { font-size: 10px; padding: 1px 8px; border-radius: 10px; font-weight: 600; }
.st-pill.added { background: #e5f4ed; color: var(--sem-success); }
.st-pill.notadded { background: #eff4fb; color: var(--sem-primary); }
.susp-pill { font-size: 10px; padding: 1px 6px; border-radius: 3px; background: #fef1e1; color: #ba7517; margin-left: 6px; }
.op-todo { font-size: 11px; color: #c0c4cc; }

.search-term-actions { display: flex; align-items: center; gap: 6px; white-space: nowrap; }
.search-action { height: 26px; margin: 0 !important; padding: 0 8px; border-radius: 5px; font-size: 11px; font-weight: 600; transition: background .16s ease, border-color .16s ease, color .16s ease; }
.search-action.is-negative { background: #fff; border-color: #f0c998; color: #b86b16; }
.search-action.is-negative:not(:disabled):hover { background: #fff7ed; border-color: #e7a350; color: #9e5710; }
.search-action.is-expand { background: #edf5ff; border-color: #b7d4f2; color: #1768ad; }
.search-action.is-expand:not(:disabled):hover { background: #dfefff; border-color: #79addd; color: #10578f; }
.search-action:disabled { opacity: .48; }

.empty-line { font-size: 12px; color: #9ca3af; padding: 22px 0; }
.table-footer { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; background: #fafbfc; border-top: 1px solid #f3f4f6; font-size: 12px; color: var(--sem-text-sub); }
.neg-form { display: flex; flex-direction: column; gap: 8px; font-size: 13px; color: var(--sem-text); }
.neg-form p { margin: 0 0 4px; }
.neg-form label { font-size: 12px; color: var(--sem-text-sub); }
.neg-radio-stack { display: flex; flex-direction: column; align-items: flex-start; gap: 6px; }
.neg-tip { margin-top: 4px; color: #ba7517; font-size: 12px; }
</style>
