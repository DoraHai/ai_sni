<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  fetchCampaigns, fetchRegionOptions, setCampaignBudget, setCampaignPause,
  setCampaignRegion, setCampaignSchedule,
} from '../../api/manage'
import { WRITEBACK_CONFIRMATION } from '../../api/writeback'
import { session } from '../../store/session'
import { createLatestRequestGuard } from '../../utils/latestRequest'
import { chooseSemAccount } from '../../utils/accountScope'
import { isSemDemoIdentity, SEM_DEMO_ACCOUNTS } from '../../utils/semDemo'

const TENANT_ID = computed(() => session.tenantId)
const demoMode = computed(() => isSemDemoIdentity(session.user, TENANT_ID.value))
const currentTenant = computed(() => session.tenants.find((row) => row.id === TENANT_ID.value))
const readableAccounts = computed(() => (demoMode.value ? SEM_DEMO_ACCOUNTS : (currentTenant.value?.sem_accounts || [])).filter((row) => row.status !== 'archived'))
const activeAccountIds = computed(() => new Set(
  readableAccounts.value.filter((row) => row.status === 'active').map((row) => Number(row.id)),
))

const loading = ref(false)
const error = ref('')
const data = ref(null)
const savingId = ref(null)
const accountId = ref(null)
const selectedCampaigns = ref([])
const scheduleVisible = ref(false)
const scheduleForm = ref({ campaignId: null, campaignIds: [], campaignName: '', accountId: null, template: 'all', pause: false, days: [] })
const batchResult = ref(null)
const regions = ref([])
const regionVisible = ref(false)
const regionBatchResult = ref(null)
const regionForm = ref({
  campaignId: null, campaignIds: [], campaignName: '', accountId: null, accountName: '',
  regionTarget: [], factors: {}, geoLocationStatus: 0,
})
function resetActionForms() {
  scheduleForm.value = {
    campaignId: null, campaignIds: [], campaignName: '', accountId: null,
    template: 'all', pause: false, days: [],
  }
  regionForm.value = {
    campaignId: null, campaignIds: [], campaignName: '', accountId: null, accountName: '',
    regionTarget: [], factors: {}, geoLocationStatus: 0,
  }
}
const scopedContext = () => ({ tenantId: TENANT_ID.value, accountId: accountId.value, authRevision: session.authRevision })
const loadGuard = createLatestRequestGuard(scopedContext)
const actionGuard = createLatestRequestGuard(scopedContext)
const canWriteAccount = (value) => value != null
  && Number(value) === Number(accountId.value)
  && activeAccountIds.value.has(Number(value))
const batchSelectionWritable = computed(() => selectedCampaigns.value.length > 0
  && selectedCampaigns.value.every((row) => canWriteAccount(row.baidu_account_id)))

const WEEK_DAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const ALL_REGIONS_ID = 9999999
const REGION_CASCADER_PROPS = { multiple: true, checkStrictly: true, emitPath: false }
const SCHEDULE_TEMPLATES = [
  { value: 'all', label: '全天投放', days: [1, 2, 3, 4, 5, 6, 7], start: 0, end: 24 },
  { value: 'workday', label: '工作日 09:00-18:00', days: [1, 2, 3, 4, 5], start: 9, end: 18 },
  { value: 'weekend', label: '周末 09:00-18:00', days: [6, 7], start: 9, end: 18 },
  { value: 'holiday', label: '节假日 10:00-18:00', days: [1, 2, 3, 4, 5, 6, 7], start: 10, end: 18 },
  { value: 'holiday_pause', label: '节假日停投', days: [], start: 0, end: 0, pause: true },
  { value: 'custom', label: '自定义', days: [], start: 9, end: 18 },
]

async function load() {
  const attempt = loadGuard.begin()
  const { tenantId, accountId: selectedAccountId } = attempt.context
  if (!session.canView('manage.campaigns') || !tenantId) {
    data.value = null
    error.value = ''
    loading.value = false
    return
  }
  loading.value = true
  error.value = ''
  try {
    const result = await fetchCampaigns({ tenantId, baiduAccountId: selectedAccountId })
    if (!attempt.isCurrent()) return
    data.value = result
    selectedCampaigns.value = []
  } catch (e) {
    if (attempt.isCurrent()) error.value = e.message
  } finally {
    if (attempt.isCurrent()) loading.value = false
  }
}

watch(TENANT_ID, () => {
  loadGuard.invalidate()
  actionGuard.invalidate()
  data.value = null
  loading.value = false
  savingId.value = null
  const previousAccountId = accountId.value
  const activeIds = [...activeAccountIds.value]
  accountId.value = activeIds.length === 1 ? activeIds[0] : null
  selectedCampaigns.value = []
  scheduleVisible.value = false
  regionVisible.value = false
  batchResult.value = null
  regionBatchResult.value = null
  resetActionForms()
  if (accountId.value === previousAccountId) load()
}, { immediate: true })
watch(accountId, () => {
  loadGuard.invalidate()
  actionGuard.invalidate()
  data.value = null
  loading.value = false
  savingId.value = null
  selectedCampaigns.value = []
  scheduleVisible.value = false
  regionVisible.value = false
  batchResult.value = null
  regionBatchResult.value = null
  resetActionForms()
  load()
})
watch(() => session.tenantListRevision, () => {
  loadGuard.invalidate()
  actionGuard.invalidate()
  data.value = null
  loading.value = false
  savingId.value = null
  selectedCampaigns.value = []
  scheduleVisible.value = false
  regionVisible.value = false
  batchResult.value = null
  regionBatchResult.value = null
  resetActionForms()
  const previousAccountId = accountId.value
  accountId.value = chooseSemAccount(readableAccounts.value, previousAccountId)
  if (accountId.value === previousAccountId) load()
})
watch(() => session.authRevision, () => {
  loadGuard.invalidate()
  actionGuard.invalidate()
  data.value = null
  error.value = ''
  loading.value = false
  savingId.value = null
  selectedCampaigns.value = []
  scheduleVisible.value = false
  regionVisible.value = false
  batchResult.value = null
  regionBatchResult.value = null
  resetActionForms()
  if (session.canView('manage.campaigns')) load()
})
async function loadRegions() {
  try {
    regions.value = (await fetchRegionOptions()).regions || []
  } catch (e) {
    ElMessage.error('地域编码加载失败：' + (e.response?.data?.detail || e.message))
  }
}

onMounted(loadRegions)

const fmtMoney = (v) => (v == null ? '不限' : '¥' + Number(v).toFixed(2))
const min = computed(() => data.value?.min_budget ?? 50)
const max = computed(() => data.value?.max_budget ?? 10000000)
const regionLookup = computed(() => new Map(regions.value.map((item) => [item.id, item])))
const unknownSelectedRegions = computed(() => (
  regionForm.value.regionTarget.filter((id) => !regionLookup.value.has(id))
))
const regionTree = computed(() => {
  const children = new Map()
  for (const item of regions.value) {
    if (item.parent_id == null) continue
    if (!children.has(item.parent_id)) children.set(item.parent_id, [])
    children.get(item.parent_id).push({ value: item.id, label: item.name })
  }
  return regions.value
    .filter((item) => item.parent_id == null)
    .map((item) => {
      const childOptions = children.get(item.id) || []
      return {
        value: item.id,
        label: item.name,
        children: childOptions.length ? childOptions : undefined,
      }
    })
})
// status 23=暂停推广（文档 0040），pause=true 同义
const statusLabel = (r) => (r.pause ? '已暂停' : (r.status === 21 ? '投放中' : (r.status === 23 ? '已暂停' : '—')))

function emptyScheduleDays() {
  return WEEK_DAYS.map((name, index) => ({ weekDay: index + 1, name, enabled: false, start: 9, end: 18 }))
}

function applyScheduleTemplate(templateName) {
  const template = SCHEDULE_TEMPLATES.find((item) => item.value === templateName)
  if (!template) return
  scheduleForm.value.template = templateName
  scheduleForm.value.pause = Boolean(template.pause)
  if (templateName === 'custom') return
  scheduleForm.value.days = emptyScheduleDays().map((day) => ({
    ...day,
    enabled: template.days.includes(day.weekDay),
    start: template.start,
    end: template.end,
  }))
}

function openSchedule(row) {
  if (!session.canEdit('manage.campaigns')) return
  if (!canWriteAccount(row.baidu_account_id)) return ElMessage.warning('请先选择该计划所属的可用推广账户')
  batchResult.value = null
  scheduleForm.value = {
    campaignId: row.campaign_id,
    campaignIds: [row.campaign_id],
    campaignName: row.campaign_name || `#${row.campaign_id}`,
    accountId: row.baidu_account_id,
    template: 'custom',
    pause: false,
    days: emptyScheduleDays(),
  }
  const factors = row.schedule_price_factors || []
  if (factors.length) {
    const slots = new Set(factors.map((item) => Number(item.timeId)))
    scheduleForm.value.days.forEach((day) => {
      const hours = Array.from({ length: 24 }, (_, hour) => hour).filter((hour) => slots.has(day.weekDay * 100 + hour))
      if (hours.length) {
        day.enabled = true
        day.start = Math.min(...hours)
        day.end = Math.max(...hours) + 1
      }
    })
  } else {
    applyScheduleTemplate('all')
  }
  scheduleVisible.value = true
}

function openBatchSchedule() {
  if (!session.canEdit('manage.campaigns')) return
  if (!selectedCampaigns.value.length) {
    ElMessage.warning('请先选择需要统一设置时段的计划')
    return
  }
  const accountIds = new Set(selectedCampaigns.value.map((row) => row.baidu_account_id))
  if (accountIds.size !== 1 || accountIds.has(null) || accountIds.has(undefined)) {
    ElMessage.warning('批量设置只能选择同一个百度账户下的计划')
    return
  }
  const selectedAccount = [...accountIds][0]
  if (!canWriteAccount(selectedAccount)) return ElMessage.warning('请先选择这些计划所属的可用推广账户')
  batchResult.value = null
  scheduleForm.value = {
    campaignId: null,
    campaignIds: selectedCampaigns.value.map((row) => row.campaign_id),
    campaignName: `${selectedCampaigns.value.length} 个计划`,
    accountId: selectedAccount,
    template: 'all',
    pause: false,
    days: emptyScheduleDays(),
  }
  applyScheduleTemplate('all')
  scheduleVisible.value = true
}

function buildScheduleFactors(days = scheduleForm.value.days) {
  const factors = []
  for (const day of days) {
    if (!day.enabled) continue
    const start = Number(day.start)
    const end = Number(day.end)
    if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end > 24 || start >= end) {
      throw new Error(`${day.name}的开始时间必须早于结束时间`)
    }
    for (let hour = start; hour < end; hour += 1) {
      factors.push({ timeId: day.weekDay * 100 + hour, priceFactor: 1 })
    }
  }
  return factors
}

async function saveSchedule() {
  if (!session.canEdit('manage.campaigns')) return
  const attempt = actionGuard.begin()
  const form = structuredClone(scheduleForm.value)
  if (!attempt.isCurrent() || !canWriteAccount(form.accountId)) return
  let factors
  try {
    factors = buildScheduleFactors(form.days)
  } catch (e) {
    ElMessage.warning(e.message)
    return
  }
  if (!factors.length && !form.pause) {
    ElMessage.warning('请至少启用一个投放日，或选择“节假日停投”模板')
    return
  }
  const campaignIds = form.campaignIds.length ? form.campaignIds : [form.campaignId]
  savingId.value = campaignIds.length > 1 ? 'batch-schedule' : campaignIds[0]
  batchResult.value = null
  try {
    const results = []
    for (const campaignId of campaignIds) {
      if (!attempt.isCurrent()) return
      try {
        const res = await setCampaignSchedule({
          tenantId: attempt.context.tenantId,
          campaignId,
          schedulePriceFactors: factors,
          pause: form.pause,
        })
        if (!attempt.isCurrent()) return
        results.push({ campaignId, ...res })
      } catch (e) {
        if (!attempt.isCurrent()) return
        results.push({ campaignId, status: 'failed', error_msg: e.response?.data?.detail || e.message })
      }
    }
    const failed = results.filter((item) => item.status === 'failed')
    const succeeded = results.length - failed.length
    if (!attempt.isCurrent()) return
    batchResult.value = { total: results.length, succeeded, failed }
    if (failed.length) {
      ElMessage.warning(`时段设置完成：成功 ${succeeded} 个，失败 ${failed.length} 个`)
    } else {
      const dryRun = results.every((item) => item.dry_run)
      ElMessage.success(`已为 ${succeeded} 个计划应用时段模板${dryRun ? '（演练：未真改）' : ''}`)
      scheduleVisible.value = false
    }
    await load()
  } finally {
    if (attempt.isCurrent()) savingId.value = null
  }
}

function handleSelectionChange(rows) {
  selectedCampaigns.value = rows
}

function regionLabel(region) {
  const parent = regionLookup.value.get(region.parent_id)
  return parent ? `${parent.name} > ${region.name}` : region.name
}

function regionName(id) {
  const region = regionLookup.value.get(id)
  return region ? regionLabel(region) : `地域 #${id}`
}

function regionSummary(row) {
  const targets = row.region_target || []
  if (targets.includes(ALL_REGIONS_ID)) return '全部区域'
  return targets.length ? `${targets.length} 个地域` : '未设置'
}

function openRegion(row) {
  if (!session.canEdit('manage.campaigns')) return
  if (!canWriteAccount(row.baidu_account_id)) return ElMessage.warning('请先选择该计划所属的可用推广账户')
  regionBatchResult.value = null
  regionForm.value = {
    campaignId: row.campaign_id,
    campaignIds: [row.campaign_id],
    campaignName: row.campaign_name,
    accountId: row.baidu_account_id,
    accountName: row.baidu_account_name || `账户 #${row.baidu_account_id}`,
    regionTarget: [...(row.region_target || [])],
    factors: Object.fromEntries((row.region_price_factor || []).map((item) => [item.regionId, Number(item.priceFactor)])),
    geoLocationStatus: row.geo_location_status ?? 0,
  }
  regionVisible.value = true
}

function openBatchRegion() {
  if (!session.canEdit('manage.campaigns')) return
  if (!selectedCampaigns.value.length) {
    ElMessage.warning('请先选择需要统一设置地域的计划')
    return
  }
  const accountIds = new Set(selectedCampaigns.value.map((row) => row.baidu_account_id))
  if (accountIds.size !== 1 || accountIds.has(null) || accountIds.has(undefined)) {
    ElMessage.warning('批量设置只能选择同一个百度账户下的计划')
    return
  }
  const first = selectedCampaigns.value[0]
  if (!canWriteAccount(first.baidu_account_id)) return ElMessage.warning('请先选择这些计划所属的可用推广账户')
  regionBatchResult.value = null
  regionForm.value = {
    campaignId: null,
    campaignIds: selectedCampaigns.value.map((row) => row.campaign_id),
    campaignName: `${selectedCampaigns.value.length} 个计划`,
    accountId: first.baidu_account_id,
    accountName: first.baidu_account_name || `账户 #${first.baidu_account_id}`,
    regionTarget: [],
    factors: {},
    geoLocationStatus: 0,
  }
  regionVisible.value = true
}

function selectAllRegions() {
  regionForm.value.regionTarget = [ALL_REGIONS_ID]
  regionForm.value.factors = {}
}

function handleRegionChange(value) {
  let selected = Array.isArray(value) ? value : []
  if (selected.includes(ALL_REGIONS_ID) && selected.length > 1) {
    selected = selected[selected.length - 1] === ALL_REGIONS_ID
      ? [ALL_REGIONS_ID]
      : selected.filter((id) => id !== ALL_REGIONS_ID)
    regionForm.value.regionTarget = selected
  }
  regionForm.value.factors = Object.fromEntries(
    Object.entries(regionForm.value.factors).filter(([id]) => selected.includes(Number(id))),
  )
}

async function saveRegion() {
  if (!session.canEdit('manage.campaigns')) return
  const attempt = actionGuard.begin()
  const form = structuredClone(regionForm.value)
  if (!attempt.isCurrent() || !canWriteAccount(form.accountId)) return
  if (!form.regionTarget.length) {
    ElMessage.warning('请至少选择一个地域')
    return
  }
  if (unknownSelectedRegions.value.length) {
    ElMessage.warning(`当前计划包含地域码表外的 ID：${unknownSelectedRegions.value.join('、')}，请先核对百度地域编码`)
    return
  }
  if (form.regionTarget.includes(ALL_REGIONS_ID) && form.regionTarget.length > 1) {
    ElMessage.warning('“全部区域”不能与其他省市同时选择')
    return
  }
  const factors = Object.entries(form.factors)
    .filter(([id, factor]) => form.regionTarget.includes(Number(id)) && factor != null)
    .map(([id, factor]) => ({ region_id: Number(id), price_factor: Number(factor) }))
  const campaignIds = form.campaignIds.length ? form.campaignIds : [form.campaignId]
  const regionPreview = form.regionTarget.slice(0, 5).map(regionName).join('、')
  const more = form.regionTarget.length > 5 ? ` 等 ${form.regionTarget.length} 个地域` : ''
  try {
    await ElMessageBox.confirm(
      `即将完整覆盖「${form.accountName}」下 ${campaignIds.length} 个计划的投放地域为：${regionPreview}${more}。每个计划会独立写回并记录台账，是否继续？`,
      campaignIds.length > 1 ? '确认批量设置投放地域' : '确认设置投放地域',
      { confirmButtonText: '加入待回写', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }
  if (!attempt.isCurrent()) return
  savingId.value = campaignIds.length > 1 ? 'batch-region' : campaignIds[0]
  regionBatchResult.value = null
  try {
    const results = []
    for (const campaignId of campaignIds) {
      if (!attempt.isCurrent()) return
      try {
        const res = await setCampaignRegion({
          tenantId: attempt.context.tenantId,
          campaignId,
          regionTarget: form.regionTarget,
          regionPriceFactor: factors,
          geoLocationStatus: form.geoLocationStatus,
        })
        if (!attempt.isCurrent()) return
        if (res.baidu_account_id !== form.accountId) {
          results.push({ campaignId, status: 'failed', error_msg: '后端返回的百度账户与所选账户不一致' })
        } else {
          results.push({ campaignId, ...res })
        }
      } catch (e) {
        if (!attempt.isCurrent()) return
        results.push({ campaignId, status: 'failed', error_msg: e.response?.data?.detail || e.message })
      }
    }
    const failed = results.filter((item) => item.status === 'failed')
    const succeeded = results.length - failed.length
    if (!attempt.isCurrent()) return
    regionBatchResult.value = { total: results.length, succeeded, failed }
    if (failed.length) {
      ElMessage.warning(`地域设置完成：成功 ${succeeded} 个，失败 ${failed.length} 个`)
    } else {
      const dryRun = results.every((item) => item.dry_run)
      ElMessage.success(`已为 ${succeeded} 个计划设置投放地域${dryRun ? '（演练：未真改）' : ''}`)
      regionVisible.value = false
    }
    await load()
  } finally {
    if (attempt.isCurrent()) savingId.value = null
  }
}

async function editBudget(row) {
  if (!session.canEdit('manage.campaigns')) return
  if (!canWriteAccount(row.baidu_account_id)) return ElMessage.warning('请先选择该计划所属的可用推广账户')
  const attempt = actionGuard.begin()
  const asset = {
    campaignId: row.campaign_id,
    accountId: row.baidu_account_id,
    name: row.campaign_name,
    budget: row.budget,
    minBudget: min.value,
    maxBudget: max.value,
  }
  const { value } = await ElMessageBox.prompt(
    `计划「${asset.name}」当前日预算 ${fmtMoney(asset.budget)}。\n输入新的日预算（¥${min.value} ~ 不超过账户日预算）。实际执行模式由当前客户、推广账户和动作门禁决定。`,
    '修改计划日预算',
    {
      confirmButtonText: '加入待回写',
      cancelButtonText: '取消',
      inputValue: asset.budget != null ? String(asset.budget) : '',
      inputPattern: /^\d+(\.\d{1,2})?$/,
      inputErrorMessage: '请输入合法金额（最多两位小数）',
    },
  ).catch(() => ({ value: null }))
  if (value == null) return
  if (!attempt.isCurrent() || !canWriteAccount(asset.accountId)) return

  const v = Number(value)
  if (!Number.isFinite(v) || v < asset.minBudget || v > asset.maxBudget) {
    ElMessage.warning(`日预算需在 ¥${asset.minBudget} ~ ¥${asset.maxBudget} 之间`)
    return
  }
  savingId.value = asset.campaignId
  try {
    const res = await setCampaignBudget({
      tenantId: attempt.context.tenantId,
      campaignId: asset.campaignId,
      budget: v,
      confirmation: WRITEBACK_CONFIRMATION,
    })
    if (!attempt.isCurrent()) return
    if (res.status === 'dry_run') {
      ElMessage.success(`演练完成：${fmtMoney(res.old_budget)} → ${fmtMoney(res.new_budget)}（未真改，已记台账）`)
    } else if (res.status === 'success') {
      ElMessage.success(`已写回：${fmtMoney(res.old_budget)} → ${fmtMoney(res.new_budget)}`)
    } else if (['pending', 'reconcile'].includes(res.status)) {
      ElMessage.warning(res.error_msg || '百度执行结果未知，已转入人工对账')
    } else {
      ElMessage.error('写回失败：' + (res.error_msg || '未知错误'))
    }
    await load()
  } catch (e) {
    if (attempt.isCurrent()) ElMessage.error(e.response?.data?.detail || e.message)
  } finally {
    if (attempt.isCurrent()) savingId.value = null
  }
}

async function togglePause(row) {
  if (!session.canEdit('manage.campaigns')) return
  if (!canWriteAccount(row.baidu_account_id)) return ElMessage.warning('请先选择该计划所属的可用推广账户')
  const attempt = actionGuard.begin()
  const asset = { campaignId: row.campaign_id, accountId: row.baidu_account_id, name: row.campaign_name, pause: row.pause, status: row.status }
  const paused = asset.pause || asset.status === 23
  const toPause = !paused
  try {
    await ElMessageBox.confirm(
      `确认${toPause ? '暂停' : '恢复投放'}计划「${asset.name}」？实际执行模式由当前客户、推广账户和动作门禁决定，真实执行会修改百度账户。`,
      toPause ? '暂停计划' : '恢复投放',
      { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }
  if (!attempt.isCurrent() || !canWriteAccount(asset.accountId)) return
  savingId.value = asset.campaignId
  try {
    const res = await setCampaignPause({ tenantId: attempt.context.tenantId, campaignId: asset.campaignId, pause: toPause })
    if (!attempt.isCurrent()) return
    const tag = res.dry_run ? '（演练：未真改）' : ''
    if (res.status === 'failed') ElMessage.error('失败：' + (res.error_msg || '未知错误'))
    else ElMessage.success(`已${toPause ? '暂停' : '恢复投放'}${tag}`)
    await load()
  } catch (e) {
    if (attempt.isCurrent()) ElMessage.error(e.response?.data?.detail || e.message)
  } finally {
    if (attempt.isCurrent()) savingId.value = null
  }
}

onBeforeUnmount(() => {
  loadGuard.invalidate()
  actionGuard.invalidate()
})
</script>

<template>
  <div v-loading="loading">
    <div class="page-header">
      <div>
        <div class="page-title">计划管理</div>
        <div class="page-desc">
          按计划设置每日预算、启停与投放时段；节假日前可应用节假日模板统一调整投放窗口。
        </div>
      </div>
    </div>

    <el-alert v-if="demoMode" title="演示数据，仅供体验；操作不会影响真实投放。" type="info" :closable="false" show-icon style="margin-bottom: 14px" />
    <el-alert v-if="error" :title="error" type="error" :closable="false" style="margin-bottom: 14px" />
    <el-alert
      type="warning"
      :closable="false"
      show-icon
      style="margin-bottom: 14px"
      title="回写模式按客户、推广账户和动作门禁判定；已开放动作会真实修改百度账户。"
    />

    <div class="table-panel">
      <div class="account-toolbar">
        <div class="account-filter">
          <span>百度账户</span>
          <el-select v-model="accountId" clearable placeholder="全部账户（只读）" style="width: 240px">
            <el-option
              v-for="account in readableAccounts"
              :key="account.id"
              :label="`${account.username || account.name || ('账户 #' + account.id)}${account.status === 'active' ? '' : ' · 已停用（历史）'}`"
              :value="account.id"
            />
          </el-select>
        </div>
        <div class="batch-actions">
          <span>已选择 {{ selectedCampaigns.length }} 个计划</span>
          <el-button
            type="primary"
            :disabled="!batchSelectionWritable"
            :loading="savingId === 'batch-schedule'"
            @click="openBatchSchedule"
          >批量设置时段</el-button>
          <el-button
            type="primary"
            plain
            :disabled="!batchSelectionWritable"
            :loading="savingId === 'batch-region'"
            @click="openBatchRegion"
          >批量设置地域</el-button>
        </div>
      </div>
      <el-table
        :data="data?.campaigns || []"
        class="kw-table"
        row-key="campaign_id"
        @selection-change="handleSelectionChange"
      >
        <el-table-column type="selection" width="48" />
        <el-table-column label="百度账户" min-width="150">
          <template #default="{ row }">{{ row.baidu_account_name || ('账户 #' + (row.baidu_account_id || '未知')) }}</template>
        </el-table-column>
        <el-table-column label="计划" min-width="200">
          <template #default="{ row }"><span class="kw-cell-name">{{ row.campaign_name || ('#' + row.campaign_id) }}</span></template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <span class="status-pill" :class="row.pause || row.status === 23 ? 'paused' : 'active'">{{ statusLabel(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="日预算" width="140" align="right">
          <template #default="{ row }"><span class="num" :class="{ unlimited: row.budget == null }">{{ fmtMoney(row.budget) }}</span></template>
        </el-table-column>
        <el-table-column label="投放地域" width="110" align="center">
          <template #default="{ row }">{{ regionSummary(row) }}</template>
        </el-table-column>
        <el-table-column v-if="session.canEdit('manage.campaigns') && !demoMode" label="操作" width="390" align="center">
          <template #default="{ row }">
            <el-button size="small" :disabled="!canWriteAccount(row.baidu_account_id)" :loading="savingId === row.campaign_id" @click="editBudget(row)">预算建议</el-button>
            <el-button size="small" :disabled="!canWriteAccount(row.baidu_account_id)" :loading="savingId === row.campaign_id" @click="openSchedule(row)">时段建议</el-button>
            <el-button size="small" :disabled="!canWriteAccount(row.baidu_account_id)" :loading="savingId === row.campaign_id" @click="openRegion(row)">地域建议</el-button>
            <el-button
              size="small"
              :disabled="!canWriteAccount(row.baidu_account_id)"
              :type="(row.pause || row.status === 23) ? 'success' : 'warning'"
              plain
              :loading="savingId === row.campaign_id"
              @click="togglePause(row)"
            >{{ (row.pause || row.status === 23) ? '恢复投放' : '暂停' }}</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-line">暂无计划数据。请先在「授权与同步」或后台执行计划维度同步。</div>
        </template>
      </el-table>
    </div>

    <el-dialog v-model="scheduleVisible" title="设置投放时段" width="min(680px, calc(100vw - 32px))">
      <div class="schedule-form">
        <p>{{ scheduleForm.campaignIds.length > 1 ? '批量设置' : '计划' }}「{{ scheduleForm.campaignName }}」</p>
        <el-alert
          v-if="scheduleForm.campaignIds.length > 1"
          type="info"
          :closable="false"
          title="将按顺序逐个更新所选计划；每个计划独立记录操作台账，单个失败不会中断其他计划。"
        />
        <el-radio-group
          v-model="scheduleForm.template"
          class="template-list"
          @change="applyScheduleTemplate"
        >
          <el-radio-button v-for="item in SCHEDULE_TEMPLATES" :key="item.value" :value="item.value">
            {{ item.label }}
          </el-radio-button>
        </el-radio-group>
        <el-alert
          v-if="scheduleForm.pause"
          type="warning"
          :closable="false"
          title="节假日停投模板会暂停该计划；节后请应用其他模板并点击“恢复投放”。"
        />
        <div v-else class="schedule-days">
          <div v-for="day in scheduleForm.days" :key="day.weekDay" class="schedule-day">
            <el-checkbox v-model="day.enabled" @change="scheduleForm.template = 'custom'">{{ day.name }}</el-checkbox>
            <template v-if="day.enabled">
              <el-input-number v-model="day.start" :min="0" :max="23" :step="1" controls-position="right" />
              <span>时 至</span>
              <el-input-number v-model="day.end" :min="1" :max="24" :step="1" controls-position="right" />
              <span>时</span>
            </template>
            <span v-else class="off-label">不投放</span>
          </div>
        </div>
        <el-alert
          v-if="batchResult?.failed?.length"
          type="error"
          :closable="false"
          style="margin-top: 14px"
          :title="`成功 ${batchResult.succeeded} 个，失败 ${batchResult.failed.length} 个`"
        >
          <template #default>
            <div v-for="item in batchResult.failed" :key="item.campaignId">
              计划 #{{ item.campaignId }}：{{ item.error_msg || '未知错误' }}
            </div>
          </template>
        </el-alert>
      </div>
      <template #footer>
        <el-button @click="scheduleVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="savingId === scheduleForm.campaignId || savingId === 'batch-schedule'"
          @click="saveSchedule"
        >{{ scheduleForm.campaignIds.length > 1 ? '批量应用模板' : '应用模板' }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="regionVisible" title="设置投放地域" width="min(760px, calc(100vw - 32px))">
      <div class="region-form">
        <p>为「{{ regionForm.campaignName }}」选择投放地域，所属百度账户：{{ regionForm.accountName }}</p>
        <el-alert
          v-if="regionForm.campaignIds.length > 1"
          type="warning"
          :closable="false"
          title="批量操作会完整覆盖所选计划的地域设置；只能处理同一百度账户下的计划。"
        />
        <div class="region-actions">
          <el-button size="small" @click="selectAllRegions">全部区域</el-button>
          <el-button size="small" @click="regionForm.regionTarget = []; regionForm.factors = {}">清空</el-button>
          <span>已选择 {{ regionForm.regionTarget.length }} 个地域</span>
        </div>
        <el-cascader
          v-model="regionForm.regionTarget"
          :options="regionTree"
          :props="REGION_CASCADER_PROPS"
          filterable
          clearable
          collapse-tags
          collapse-tags-tooltip
          placeholder="按省/市层级选择，可搜索"
          style="width: 100%"
          @change="handleRegionChange"
        />
        <el-alert
          v-if="unknownSelectedRegions.length"
          type="error"
          :closable="false"
          style="margin-top: 10px"
          :title="`当前计划包含地域码表外的 ID：${unknownSelectedRegions.join('、')}，已阻止覆盖写回，请先核对或更新地域编码。`"
        />
        <div class="geo-status-section">
          <p>地域定向方式</p>
          <el-radio-group v-model="regionForm.geoLocationStatus">
            <el-radio :value="0">该地区内或搜索意图在该地区的所有用户</el-radio>
            <el-radio :value="1">仅该地区内的所有用户</el-radio>
          </el-radio-group>
        </div>
        <div v-if="regionForm.regionTarget.length" class="region-factor-list">
          <p class="factor-hint">可选：为已选地域单独设置出价系数（0.1~1.0，不设则默认 1.0）</p>
          <div v-for="id in regionForm.regionTarget" :key="id" class="factor-row">
            <span>{{ regionName(id) }}</span>
            <el-input-number v-model="regionForm.factors[id]" :min="0.1" :max="1" :step="0.1" :precision="1" placeholder="1.0" />
          </div>
        </div>
        <el-alert
          v-if="regionBatchResult?.failed?.length"
          type="error"
          :closable="false"
          style="margin-top: 14px"
          :title="`成功 ${regionBatchResult.succeeded} 个，失败 ${regionBatchResult.failed.length} 个`"
        >
          <template #default>
            <div v-for="item in regionBatchResult.failed" :key="item.campaignId">
              计划 #{{ item.campaignId }}：{{ item.error_msg || '未知错误' }}
            </div>
          </template>
        </el-alert>
      </div>
      <template #footer>
        <el-button @click="regionVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="savingId === regionForm.campaignId || savingId === 'batch-region'"
          @click="saveRegion"
        >{{ regionForm.campaignIds.length > 1 ? '批量加入待回写' : '加入待回写' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-header { margin-bottom: 14px; }
.page-title { font-size: 20px; font-weight: 600; color: var(--sem-text); }
.page-desc { font-size: 12px; color: var(--sem-text-sub); margin-top: 4px; }

.table-panel { background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; overflow: hidden; }
.account-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 12px 14px; border-bottom: 1px solid var(--sem-border); }
.account-filter, .batch-actions { display: flex; align-items: center; gap: 10px; color: var(--sem-text-sub); font-size: 12px; }
.kw-table { font-size: 13px; }
.kw-table :deep(th.el-table__cell) { background: #fafbfc; font-weight: 500; color: var(--sem-text-sub); font-size: 12px; }
.kw-cell-name { font-weight: 500; color: var(--sem-text); }
.num { font-variant-numeric: tabular-nums; font-weight: 600; }
.num.unlimited { color: #9ca3af; font-weight: 400; }
.status-pill { font-size: 11px; padding: 1px 9px; border-radius: 10px; font-weight: 600; }
.status-pill.active { background: #e5f4ed; color: var(--sem-success); }
.status-pill.paused { background: #fef1e1; color: #ba7517; }
.empty-line { font-size: 12px; color: #9ca3af; padding: 22px 0; }
.schedule-form > p { margin-top: 0; color: var(--sem-text-sub); }
.template-list { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 16px; }
.template-list :deep(.el-radio-button__inner) { border: 1px solid var(--sem-border); border-radius: 6px; }
.schedule-days { border: 1px solid var(--sem-border); border-radius: 8px; overflow: hidden; }
.schedule-day { min-height: 48px; padding: 7px 12px; display: grid; grid-template-columns: 90px 110px 48px 110px 24px; gap: 8px; align-items: center; border-bottom: 1px solid var(--sem-border); }
.schedule-day:last-child { border-bottom: 0; }
.schedule-day :deep(.el-input-number) { width: 110px; }
.off-label { grid-column: 2 / -1; color: #9ca3af; }
.region-form > p, .geo-status-section > p { color: var(--sem-text-sub); }
.region-actions { display: flex; align-items: center; gap: 8px; margin: 14px 0 10px; color: var(--sem-text-sub); font-size: 12px; }
.geo-status-section { margin-top: 16px; }
.geo-status-section :deep(.el-radio-group) { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; }
.region-factor-list { margin-top: 16px; }
.factor-hint { font-size: 12px; color: var(--sem-text-sub); }
.factor-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-top: 8px; }
.factor-row :deep(.el-input-number) { width: 130px; }
@media (max-width: 640px) {
  .account-toolbar { align-items: stretch; flex-direction: column; }
  .account-filter, .batch-actions { justify-content: space-between; }
  .schedule-day { grid-template-columns: 76px 1fr 40px 1fr 20px; padding: 7px 8px; gap: 4px; }
  .schedule-day :deep(.el-input-number) { width: 100%; }
}
</style>
