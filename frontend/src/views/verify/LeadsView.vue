<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { fetchLeads, createLead, updateLead, deleteLead, syncLeads } from '../../api/leads'
import { fetchCampaignList } from '../../api/keywords'
import { session } from '../../store/session'

const TENANT_ID = computed(() => session.tenantId)
const canEdit = computed(() => session.canEdit('verify.leads'))

const STATUS_OPTS = [
  { code: 'new', label: '新建' },
  { code: 'following', label: '跟进中' },
  { code: 'won', label: '已成交' },
  { code: 'invalid', label: '无效' },
]
const INTENT_OPTS = [
  { code: 'high', label: '高' },
  { code: 'mid', label: '中' },
  { code: 'low', label: '低' },
]
const STATUS_LABEL = Object.fromEntries(STATUS_OPTS.map((s) => [s.code, s.label]))

const loading = ref(false)
const error = ref('')
const data = ref(null)
const campaigns = ref([])

const filters = reactive({ status: null, campaignId: null, dateRange: null, page: 1, pageSize: 20 })

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [start, end] = filters.dateRange || []
    data.value = await fetchLeads({
      tenantId: TENANT_ID.value,
      status: filters.status,
      campaignId: filters.campaignId,
      startDate: start,
      endDate: end,
      page: filters.page,
      pageSize: filters.pageSize,
    })
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

const syncing = ref(false)
async function doSync() {
  syncing.value = true
  try {
    const res = await syncLeads({ tenantId: TENANT_ID.value })
    ElMessage.success(res.synced > 0 ? `已从百度同步 ${res.synced} 条新线索` : '已是最新，无新增线索')
    load()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  } finally {
    syncing.value = false
  }
}

async function loadCampaigns() {
  if (campaigns.value.length) return
  try {
    campaigns.value = (await fetchCampaignList({ tenantId: TENANT_ID.value })).campaigns || []
  } catch (e) {
    ElMessage.error('加载计划失败：' + (e.message || ''))
  }
}

const fmtInt = (v) => (v == null ? '—' : Number(v).toLocaleString('zh-CN'))
const fmtTime = (v) => (v ? v.slice(5, 16).replace('T', ' ') : '—')

const statCards = computed(() => {
  const s = data.value?.summary
  if (!s) return []
  return [
    { label: '线索总数', value: fmtInt(s.total), sub: '本客户全部录入线索' },
    { label: '跟进中', value: fmtInt(s.following), sub: '销售正在跟进' },
    { label: '已成交', value: fmtInt(s.won), sub: '成交率 ' + (s.win_rate ?? 0) + '%（按有效线索）' },
  ]
})

// ===== 录入 / 编辑弹框 =====
const dialog = reactive({ visible: false, submitting: false })
const blankForm = () => ({
  id: null, contact_name: '', phone: '', campaign_id: null,
  status: 'new', intent_level: null, lead_time: null, note: '',
})
const form = reactive(blankForm())

async function openCreate() {
  Object.assign(form, blankForm())
  dialog.visible = true
  await loadCampaigns()
}

async function openEdit(row) {
  Object.assign(form, {
    id: row.id, contact_name: row.contact_name || '', phone: row.phone || '',
    campaign_id: row.campaign_id, status: row.status, intent_level: row.intent_level,
    lead_time: row.lead_time, note: row.note || '',
  })
  dialog.visible = true
  await loadCampaigns()
}

async function submit() {
  if (!form.contact_name.trim() && !form.phone.trim()) {
    return ElMessage.warning('姓名和联系方式至少填一项')
  }
  dialog.submitting = true
  const payload = {
    contact_name: form.contact_name.trim() || null,
    phone: form.phone.trim() || null,
    campaign_id: form.campaign_id,
    campaign_name: campaigns.value.find((c) => c.campaign_id === form.campaign_id)?.campaign_name || null,
    status: form.status,
    intent_level: form.intent_level,
    lead_time: form.lead_time,
    note: form.note.trim() || null,
  }
  try {
    if (form.id) await updateLead({ tenantId: TENANT_ID.value, id: form.id, ...payload })
    else await createLead({ tenantId: TENANT_ID.value, ...payload })
    ElMessage.success(form.id ? '已更新' : '已录入')
    dialog.visible = false
    load()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  } finally {
    dialog.submitting = false
  }
}

// 表内行内改状态（销售快速流转）
async function changeStatus(row, status) {
  try {
    await updateLead({ tenantId: TENANT_ID.value, id: row.id, status })
    row.status = status
    row.status_label = STATUS_LABEL[status]
    load() // 刷新统计卡
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  }
}

async function removeLead(row) {
  try {
    await ElMessageBox.confirm(
      `删除线索「${row.contact_name || row.phone || '#' + row.id}」？此操作不可恢复。`,
      '删除线索', { confirmButtonText: '确认删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }
  try {
    await deleteLead({ tenantId: TENANT_ID.value, id: row.id })
    ElMessage.success('已删除')
    load()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  }
}

watch(() => [filters.status, filters.campaignId, filters.dateRange], () => { filters.page = 1; load() })
watch(() => [filters.page, filters.pageSize], load)
watch(TENANT_ID, () => { campaigns.value = []; filters.page = 1; load() })
onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <div class="page-header">
      <div>
        <div class="page-title">线索管理</div>
        <div class="page-desc">
          客户真线索台账。「从百度同步」拉基木鱼线索明细（含触发词、接通状态，按 clueId 去重）；
          线下/非基木鱼线索可手动录入。用于算真实线索成本与 ROI，也是小白模式的数据地基。
        </div>
      </div>
      <div v-if="canEdit" class="header-actions">
        <el-button :loading="syncing" @click="doSync">⟳ 从百度同步</el-button>
        <el-button type="primary" @click="openCreate">＋ 录入线索</el-button>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" style="margin-bottom: 14px" />

    <!-- 统计卡 -->
    <div class="stat-grid">
      <div v-for="c in statCards" :key="c.label" class="stat-card">
        <div class="stat-label">{{ c.label }}</div>
        <div class="stat-value">{{ c.value }}</div>
        <div class="stat-sub">{{ c.sub }}</div>
      </div>
    </div>

    <!-- 筛选 -->
    <div class="filter-row">
      <el-select v-model="filters.status" placeholder="全部状态" clearable style="width: 130px">
        <el-option v-for="s in STATUS_OPTS" :key="s.code" :label="s.label" :value="s.code" />
      </el-select>
      <el-select v-model="filters.campaignId" placeholder="全部归因计划" clearable filterable style="width: 200px" @visible-change="(v) => v && loadCampaigns()">
        <el-option v-for="c in campaigns" :key="c.campaign_id" :label="c.campaign_name" :value="c.campaign_id" />
      </el-select>
      <el-date-picker
        v-model="filters.dateRange"
        type="daterange"
        value-format="YYYY-MM-DD"
        range-separator="~"
        start-placeholder="线索日期起"
        end-placeholder="止"
        style="width: 260px"
      />
    </div>

    <!-- 列表 -->
    <div class="table-panel">
      <el-table :data="data?.leads || []" class="kw-table" row-key="id">
        <el-table-column label="录入时间" width="110">
          <template #default="{ row }"><span class="num">{{ fmtTime(row.created_at) }}</span></template>
        </el-table-column>
        <el-table-column label="联系人" min-width="150">
          <template #default="{ row }">
            <div class="kw-cell-name">{{ row.contact_name || '—' }}</div>
            <div class="kw-cell-sub">{{ row.phone || '—' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="76" align="center">
          <template #default="{ row }">
            <span class="src-pill" :class="row.source_channel">{{ row.source_label }}</span>
          </template>
        </el-table-column>
        <el-table-column label="触发词 / 计划" min-width="170">
          <template #default="{ row }">
            <div class="kw-cell-name">{{ row.keyword || '—' }}</div>
            <div class="kw-cell-sub">{{ row.campaign_name || '账户级' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="接通" width="64" align="center">
          <template #default="{ row }">
            <span v-if="row.connect === 1" class="connect-tag ok">接通</span>
            <span v-else-if="row.connect === 0" class="connect-tag no">未接</span>
            <span v-else class="dim">—</span>
          </template>
        </el-table-column>
        <el-table-column label="意向" width="70" align="center">
          <template #default="{ row }">
            <span v-if="row.intent_label" class="intent-pill" :class="row.intent_level">{{ row.intent_label }}</span>
            <span v-else class="dim">—</span>
          </template>
        </el-table-column>
        <el-table-column label="线索日期" width="100">
          <template #default="{ row }"><span class="num">{{ row.lead_time || '—' }}</span></template>
        </el-table-column>
        <el-table-column label="状态" width="120" align="center">
          <template #default="{ row }">
            <el-select
              v-if="canEdit"
              :model-value="row.status"
              size="small"
              class="status-select"
              @change="(v) => changeStatus(row, v)"
            >
              <el-option v-for="s in STATUS_OPTS" :key="s.code" :label="s.label" :value="s.code" />
            </el-select>
            <span v-else class="status-pill" :class="row.status">{{ row.status_label }}</span>
          </template>
        </el-table-column>
        <el-table-column label="备注" min-width="140">
          <template #default="{ row }"><span class="kw-cell-sub">{{ row.note || '—' }}</span></template>
        </el-table-column>
        <el-table-column v-if="canEdit" label="操作" width="110" align="center">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" size="small" @click="removeLead(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-line">还没有线索。点右上角「＋ 录入线索」把客户来的真线索登记进来。</div>
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

    <!-- 录入 / 编辑弹框 -->
    <el-dialog v-model="dialog.visible" :title="form.id ? '编辑线索' : '录入线索'" width="460px">
      <el-form label-width="80px" label-position="left">
        <el-form-item label="姓名">
          <el-input v-model="form.contact_name" placeholder="联系人称呼" />
        </el-form-item>
        <el-form-item label="联系方式">
          <el-input v-model="form.phone" placeholder="电话 / 微信 / QQ" />
        </el-form-item>
        <el-form-item label="归因计划">
          <el-select v-model="form.campaign_id" placeholder="不选=账户级" clearable filterable style="width: 100%">
            <el-option v-for="c in campaigns" :key="c.campaign_id" :label="c.campaign_name" :value="c.campaign_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="意向等级">
          <el-radio-group v-model="form.intent_level">
            <el-radio v-for="i in INTENT_OPTS" :key="i.code" :value="i.code">{{ i.label }}</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status" style="width: 100%">
            <el-option v-for="s in STATUS_OPTS" :key="s.code" :label="s.label" :value="s.code" />
          </el-select>
        </el-form-item>
        <el-form-item label="线索日期">
          <el-date-picker v-model="form.lead_time" type="date" value-format="YYYY-MM-DD" placeholder="线索发生日期" style="width: 100%" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.note" type="textarea" :rows="2" placeholder="跟进情况 / 需求等" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="dialog.submitting" @click="submit">{{ form.id ? '保存' : '录入' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-header { margin-bottom: 14px; display: flex; justify-content: space-between; align-items: flex-end; }
.page-title { font-size: 20px; font-weight: 600; color: var(--sem-text); }
.page-desc { font-size: 12px; color: var(--sem-text-sub); margin-top: 4px; max-width: 760px; }

.stat-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 14px; }
@media (max-width: 1100px) { .stat-grid { grid-template-columns: repeat(2, 1fr); } }
.stat-card { background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; padding: 14px 16px; }
.stat-label { font-size: 11px; color: var(--sem-text-sub); }
.stat-value { font-size: 22px; font-weight: 700; margin-top: 8px; font-variant-numeric: tabular-nums; }
.stat-sub { font-size: 11px; color: #9ca3af; margin-top: 6px; }

.filter-row { display: flex; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; align-items: center; }

.table-panel { background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; overflow: hidden; }
.kw-table { font-size: 12px; }
.kw-table :deep(th.el-table__cell) { background: #fafbfc; font-weight: 500; color: var(--sem-text-sub); font-size: 11px; padding: 6px 0; white-space: nowrap; }
.kw-table :deep(td.el-table__cell) { padding: 8px 0; }
.kw-table :deep(.el-table__row:hover > td.el-table__cell) { background: #fafbfc; }
.kw-cell-name { font-weight: 500; color: var(--sem-text); }
.kw-cell-sub { font-size: 10px; color: #9ca3af; margin-top: 2px; }
.num { font-variant-numeric: tabular-nums; }
.dim { color: #9ca3af; }

.header-actions { display: flex; gap: 8px; }
.src-pill { font-size: 10px; padding: 1px 7px; border-radius: 10px; font-weight: 600; }
.src-pill.manual { background: #f3f4f6; color: var(--sem-text-sub); }
.src-pill.baidu { background: #eff4fb; color: var(--sem-primary); }
.connect-tag { font-size: 10px; padding: 1px 6px; border-radius: 8px; font-weight: 600; }
.connect-tag.ok { background: #e5f4ed; color: var(--sem-success); }
.connect-tag.no { background: #fdeaea; color: var(--sem-danger); }

.intent-pill { font-size: 10px; padding: 1px 7px; border-radius: 10px; font-weight: 600; }
.intent-pill.high { background: #fdeaea; color: var(--sem-danger); }
.intent-pill.mid { background: #fef1e1; color: #ba7517; }
.intent-pill.low { background: #f3f4f6; color: var(--sem-text-sub); }

.status-select { width: 100px; }
.status-pill { font-size: 10px; padding: 1px 8px; border-radius: 10px; font-weight: 600; }
.status-pill.new { background: #eff4fb; color: var(--sem-primary); }
.status-pill.following { background: #fef1e1; color: #ba7517; }
.status-pill.won { background: #e5f4ed; color: var(--sem-success); }
.status-pill.invalid { background: #f3f4f6; color: var(--sem-text-sub); }

.empty-line { font-size: 12px; color: #9ca3af; padding: 22px 0; }
.table-footer { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; background: #fafbfc; border-top: 1px solid #f3f4f6; font-size: 12px; color: var(--sem-text-sub); }
</style>
