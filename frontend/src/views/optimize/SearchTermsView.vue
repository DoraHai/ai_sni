<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { addNegative, expandKeyword, fetchSearchTerms, syncSearchTerms } from '../../api/searchTerms'
import { session } from '../../store/session'

const TENANT_ID = computed(() => session.tenantId)
const loading = ref(false)
const syncing = ref(false)
const error = ref('')
const data = ref(null)

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
const fmtTime = (v) => (v ? v.slice(0, 16).replace('T', ' ') : '—')

// C 辅助：未加成关键词 + 有展现 + 零点击 → 疑似可否（烧展现没点击）
function suspectNegative(row) {
  return !row.is_added && (row.impression || 0) >= 20 && (row.click || 0) === 0
}

function dryRunTip(res, okMsg) {
  if (res.dry_run) ElMessage.warning('演练模式：已记入台账，未真改线上（管理员开启真写后方可生效）')
  else ElMessage.success(okMsg)
}

async function addNeg(row) {
  if (!row.adgroup_id) return ElMessage.warning('该搜索词无所属单元，无法加否词')
  try {
    await ElMessageBox.confirm(
      `将「${row.query_word}」加为单元「${row.adgroup_name || row.adgroup_id}」的精确否定词。\n` +
        `受 dry-run 保护，演练模式下不真改线上。`,
      '加否词', { confirmButtonText: '确认加否词', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }
  try {
    const res = await addNegative({ tenantId: TENANT_ID.value, word: row.query_word, adgroupId: row.adgroup_id, matchMode: 'exact' })
    dryRunTip(res, '已加否词')
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
      <el-table :data="data?.search_terms || []" class="kw-table" row-key="id">
        <el-table-column label="搜索词" min-width="200">
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
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <span class="st-pill" :class="row.is_added ? 'added' : 'notadded'">{{ row.status_label }}</span>
          </template>
        </el-table-column>
        <el-table-column label="计划 / 单元" min-width="150">
          <template #default="{ row }">
            <div class="plan-line">{{ row.campaign_name || '—' }}</div>
            <div class="kw-cell-sub">{{ row.adgroup_name || '—' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="展现" width="90" align="right">
          <template #default="{ row }"><span class="num">{{ fmtInt(row.impression) }}</span></template>
        </el-table-column>
        <el-table-column label="点击" width="90" align="right">
          <template #default="{ row }">
            <span class="num" :class="{ zero: !row.click }">{{ fmtInt(row.click) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="点击率" width="92" align="right">
          <template #header>
            <span title="CTR = 点击 ÷ 展现">点击率</span>
          </template>
          <template #default="{ row }"><span class="num">{{ fmtPct(row.ctr) }}</span></template>
        </el-table-column>
        <el-table-column label="点击成本" width="104" align="right">
          <template #header>
            <span title="CPC = 消费 ÷ 点击">点击成本</span>
          </template>
          <template #default="{ row }"><span class="num">{{ fmtMoney(row.cpc) }}</span></template>
        </el-table-column>
        <el-table-column label="消费" width="100" align="right">
          <template #default="{ row }"><span class="num">{{ fmtMoney(row.cost) }}</span></template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" :disabled="!row.adgroup_id" @click="addNeg(row)">加否词</el-button>
            <el-button link type="primary" size="small" :disabled="row.is_added || !row.adgroup_id" @click="expand(row)">转拓词</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-line">没有搜索词数据。点右上角「同步搜索词」从百度拉取。</div>
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

.empty-line { font-size: 12px; color: #9ca3af; padding: 22px 0; }
.table-footer { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; background: #fafbfc; border-top: 1px solid #f3f4f6; font-size: 12px; color: var(--sem-text-sub); }
</style>
