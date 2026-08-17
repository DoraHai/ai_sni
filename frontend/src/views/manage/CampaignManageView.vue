<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  fetchCampaigns,
  fetchRegionOptions,
  setCampaignBudget,
  setCampaignPause,
  setCampaignRegion,
} from '../../api/manage'
import { session } from '../../store/session'

const TENANT_ID = computed(() => session.tenantId)

const loading = ref(false)
const error = ref('')
const data = ref(null)
const savingId = ref(null)
const regionOptions = ref([])
const regionDialogVisible = ref(false)
const regionForm = ref({ campaignId: null, campaignName: '', regionTarget: [], factors: {}, geoLocationStatus: null })

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await fetchCampaigns({ tenantId: TENANT_ID.value })
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function loadRegionOptions() {
  try {
    const res = await fetchRegionOptions()
    regionOptions.value = res.regions || []
  } catch (e) {
    ElMessage.error('地域编码加载失败：' + (e.response?.data?.detail || e.message))
  }
}

watch(TENANT_ID, load)
onMounted(async () => {
  await Promise.all([load(), loadRegionOptions()])
})

const fmtMoney = (v) => (v == null ? '不限' : '¥' + Number(v).toFixed(2))
const min = computed(() => data.value?.min_budget ?? 50)
const max = computed(() => data.value?.max_budget ?? 10000000)
// status 23=暂停推广（文档 0040），pause=true 同义
const statusLabel = (r) => (r.pause ? '已暂停' : (r.status === 21 ? '投放中' : (r.status === 23 ? '已暂停' : '—')))

async function editBudget(row) {
  const { value } = await ElMessageBox.prompt(
    `计划「${row.campaign_name}」当前日预算 ${fmtMoney(row.budget)}。\n输入新的日预算（¥${min.value} ~ 不超过账户日预算）。当前为演练模式，只记台账不真改。`,
    '修改计划日预算',
    {
      confirmButtonText: '确认写回',
      cancelButtonText: '取消',
      inputValue: row.budget != null ? String(row.budget) : '',
      inputPattern: /^\d+(\.\d{1,2})?$/,
      inputErrorMessage: '请输入合法金额（最多两位小数）',
    },
  ).catch(() => ({ value: null }))
  if (value == null) return

  const v = Number(value)
  if (!Number.isFinite(v) || v < min.value || v > max.value) {
    ElMessage.warning(`日预算需在 ¥${min.value} ~ ¥${max.value} 之间`)
    return
  }
  savingId.value = row.campaign_id
  try {
    const res = await setCampaignBudget({ tenantId: TENANT_ID.value, campaignId: row.campaign_id, budget: v })
    if (res.status === 'dry_run') {
      ElMessage.success(`演练完成：${fmtMoney(res.old_budget)} → ${fmtMoney(res.new_budget)}（未真改，已记台账）`)
    } else if (res.status === 'success') {
      ElMessage.success(`已写回：${fmtMoney(res.old_budget)} → ${fmtMoney(res.new_budget)}`)
    } else {
      ElMessage.error('写回失败：' + (res.error_msg || '未知错误'))
    }
    await load()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  } finally {
    savingId.value = null
  }
}

async function togglePause(row) {
  const paused = row.pause || row.status === 23
  const toPause = !paused
  try {
    await ElMessageBox.confirm(
      `确认${toPause ? '暂停' : '恢复投放'}计划「${row.campaign_name}」？当前为演练模式，只记台账不真改。`,
      toPause ? '暂停计划' : '恢复投放',
      { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }
  savingId.value = row.campaign_id
  try {
    const res = await setCampaignPause({ tenantId: TENANT_ID.value, campaignId: row.campaign_id, pause: toPause })
    const tag = res.dry_run ? '（演练：未真改）' : ''
    if (res.status === 'failed') ElMessage.error('失败：' + (res.error_msg || '未知错误'))
    else ElMessage.success(`已${toPause ? '暂停' : '恢复投放'}${tag}`)
    await load()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  } finally {
    savingId.value = null
  }
}

function regionLabel(region) {
  const parent = regionOptions.value.find((item) => item.id === region.parent_id)
  return parent ? `${parent.name} > ${region.name}` : region.name
}

function regionNameOf(id) {
  const region = regionOptions.value.find((item) => item.id === id)
  return region ? regionLabel(region) : `地域 #${id}`
}

function openRegionDialog(row) {
  const factors = Object.fromEntries(
    (row.region_price_factor || [])
      .filter((item) => item?.regionId != null && item.priceFactor != null)
      .map((item) => [item.regionId, Number(item.priceFactor)]),
  )
  regionForm.value = {
    campaignId: row.campaign_id,
    campaignName: row.campaign_name,
    regionTarget: [...(row.region_target || [])],
    factors,
    geoLocationStatus: row.geo_location_status ?? null,
  }
  regionDialogVisible.value = true
}

async function submitRegion() {
  const form = regionForm.value
  if (!form.regionTarget.length) {
    ElMessage.warning('请至少选择一个地域')
    return
  }
  const regionPriceFactor = Object.entries(form.factors)
    .filter(([regionId, priceFactor]) => form.regionTarget.includes(Number(regionId)) && priceFactor != null)
    .map(([regionId, priceFactor]) => ({ region_id: Number(regionId), price_factor: Number(priceFactor) }))

  savingId.value = form.campaignId
  try {
    const res = await setCampaignRegion({
      tenantId: TENANT_ID.value,
      campaignId: form.campaignId,
      regionTarget: form.regionTarget,
      regionPriceFactor: regionPriceFactor.length ? regionPriceFactor : undefined,
      geoLocationStatus: form.geoLocationStatus ?? undefined,
    })
    if (res.status === 'failed') {
      ElMessage.error('写回失败：' + (res.error_msg || '未知错误'))
      return
    }
    const tag = res.dry_run ? '（演练：未真改）' : ''
    ElMessage.success(`已设置 ${res.region_count} 个地域${tag}`)
    regionDialogVisible.value = false
    await load()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  } finally {
    savingId.value = null
  }
}
</script>

<template>
  <div v-loading="loading">
    <div class="page-header">
      <div>
        <div class="page-title">计划管理</div>
        <div class="page-desc">
          按计划设每日预算（分配各计划的花费上限）。计划日预算不能超过账户日预算——账户总闸在「账户与预算」页设。
        </div>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" style="margin-bottom: 14px" />
    <el-alert
      type="warning"
      :closable="false"
      show-icon
      style="margin-bottom: 14px"
      title="当前为演练模式：修改计划预算、地域或状态只记台账、不会真改线上百度账户。"
    />

    <div class="table-panel">
      <el-table :data="data?.campaigns || []" class="kw-table" row-key="campaign_id">
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
        <el-table-column label="操作" width="300" align="center">
          <template #default="{ row }">
            <el-button size="small" :loading="savingId === row.campaign_id" @click="editBudget(row)">改预算</el-button>
            <el-button size="small" :loading="savingId === row.campaign_id" @click="openRegionDialog(row)">设置地域</el-button>
            <el-button
              size="small"
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

    <el-dialog v-model="regionDialogVisible" title="设置投放地域" width="min(600px, calc(100vw - 32px))">
      <div class="region-form">
        <p>为计划「{{ regionForm.campaignName }}」选择投放地域：</p>
        <el-select
          v-model="regionForm.regionTarget"
          multiple
          filterable
          collapse-tags
          collapse-tags-tooltip
          placeholder="选择省/市（可多选）"
          style="width: 100%"
        >
          <el-option
            v-for="region in regionOptions"
            :key="region.id"
            :label="regionLabel(region)"
            :value="region.id"
          />
        </el-select>

        <div class="geo-status-section">
          <label>地域定向方式</label>
          <el-radio-group v-model="regionForm.geoLocationStatus">
            <el-radio :label="0">该地区内或搜索意图在该地区的所有用户</el-radio>
            <el-radio :label="1">仅该地区内的所有用户</el-radio>
          </el-radio-group>
        </div>

        <div v-if="regionForm.regionTarget.length" class="region-factor-list">
          <p class="factor-hint">可选：为已选地域单独设置出价系数（0.1~1.0，不设则默认 1.0）</p>
          <div v-for="regionId in regionForm.regionTarget" :key="regionId" class="factor-row">
            <span>{{ regionNameOf(regionId) }}</span>
            <el-input-number
              v-model="regionForm.factors[regionId]"
              :min="0.1"
              :max="1.0"
              :step="0.1"
              :precision="1"
              size="small"
            />
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="regionDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingId === regionForm.campaignId" @click="submitRegion">确认写回</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-header { margin-bottom: 14px; }
.page-title { font-size: 20px; font-weight: 600; color: var(--sem-text); }
.page-desc { font-size: 12px; color: var(--sem-text-sub); margin-top: 4px; }

.table-panel { background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; overflow: hidden; }
.kw-table { font-size: 13px; }
.kw-table :deep(th.el-table__cell) { background: #fafbfc; font-weight: 500; color: var(--sem-text-sub); font-size: 12px; }
.kw-cell-name { font-weight: 500; color: var(--sem-text); }
.num { font-variant-numeric: tabular-nums; font-weight: 600; }
.num.unlimited { color: #9ca3af; font-weight: 400; }
.status-pill { font-size: 11px; padding: 1px 9px; border-radius: 10px; font-weight: 600; }
.status-pill.active { background: #e5f4ed; color: var(--sem-success); }
.status-pill.paused { background: #fef1e1; color: #ba7517; }
.empty-line { font-size: 12px; color: #9ca3af; padding: 22px 0; }
.region-form > p { margin: 0 0 12px; color: var(--sem-text); font-size: 13px; }
.region-factor-list { margin-top: 16px; }
.geo-status-section { margin-top: 16px; }
.geo-status-section > label { display: block; margin-bottom: 8px; color: var(--sem-text); font-size: 13px; }
.geo-status-section :deep(.el-radio-group) { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; }
.factor-hint { color: var(--sem-text-sub); font-size: 12px; }
.factor-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; min-height: 34px; border-bottom: 1px solid var(--sem-border); }
.factor-row span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
</style>
