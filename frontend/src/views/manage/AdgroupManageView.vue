<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { fetchAdgroups, setAdgroupPause, setAdgroupBid, setAdgroupLandingUrl } from '../../api/manage'
import { session } from '../../store/session'

const TENANT_ID = computed(() => session.tenantId)

const loading = ref(false)
const error = ref('')
const data = ref(null)
const emptyDiagnosis = computed(() => {
  const sync = data.value?.sync
  if (!data.value || data.value.total) return ''
  if (!sync?.accounts) return '当前客户没有推广账户记录，请先核对客户与账户归属。'
  if (!sync.active_accounts) return '推广账户存在，但没有生效授权。'
  if (sync.status === 'failed') return `最近一次同步失败：${sync.error || '未知错误'}`
  if (!sync.last_synced_at) return '账户已授权但尚未完成首次同步。'
  return '账户已完成同步，但未拉到单元数据；请核对百度账户内是否存在单元。'
})
const savingId = ref(null)

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await fetchAdgroups({ tenantId: TENANT_ID.value })
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

watch(TENANT_ID, load)
onMounted(load)

const fmtMoney = (v) => (v == null ? '跟随计划' : '¥' + Number(v).toFixed(2))
const isPaused = (r) => r.pause || r.status === 23
const statusLabel = (r) => (isPaused(r) ? '已暂停' : (r.status === 21 ? '投放中' : '—'))
function landingRows(row) {
  const rows = []
  if (row.mobile_final_url) rows.push({ key: 'mobile', label: '移动端', url: row.mobile_final_url })
  if (row.pc_final_url && row.pc_final_url !== row.mobile_final_url) rows.push({ key: 'pc', label: '网页端', url: row.pc_final_url })
  if (row.pc_final_url && row.pc_final_url === row.mobile_final_url && rows[0]) rows[0].label = '移动/网页'
  return rows
}
const blankToNull = (v) => {
  const s = String(v ?? '').trim()
  return s ? s : null
}

const landingDialog = reactive({
  visible: false,
  submitting: false,
  row: null,
  pcFinalUrl: '',
  mobileFinalUrl: '',
  pcTrackParam: '',
  mobileTrackParam: '',
  pcTrackTemplate: '',
  mobileTrackTemplate: '',
})

function openLanding(row) {
  Object.assign(landingDialog, {
    visible: true,
    submitting: false,
    row,
    pcFinalUrl: row.pc_final_url || '',
    mobileFinalUrl: row.mobile_final_url || '',
    pcTrackParam: row.pc_track_param || '',
    mobileTrackParam: row.mobile_track_param || '',
    pcTrackTemplate: row.pc_track_template || '',
    mobileTrackTemplate: row.mobile_track_template || '',
  })
}

function copyPcToMobile() {
  landingDialog.mobileFinalUrl = landingDialog.pcFinalUrl
  landingDialog.mobileTrackParam = landingDialog.pcTrackParam
  landingDialog.mobileTrackTemplate = landingDialog.pcTrackTemplate
}

async function saveLanding() {
  const row = landingDialog.row
  if (!row) return
  landingDialog.submitting = true
  savingId.value = row.adgroup_id
  try {
    const res = await setAdgroupLandingUrl({
      tenantId: TENANT_ID.value,
      adgroupId: row.adgroup_id,
      pcFinalUrl: blankToNull(landingDialog.pcFinalUrl),
      mobileFinalUrl: blankToNull(landingDialog.mobileFinalUrl),
      pcTrackParam: blankToNull(landingDialog.pcTrackParam),
      mobileTrackParam: blankToNull(landingDialog.mobileTrackParam),
      pcTrackTemplate: blankToNull(landingDialog.pcTrackTemplate),
      mobileTrackTemplate: blankToNull(landingDialog.mobileTrackTemplate),
    })
    const tag = res.dry_run ? '（演练：未真改）' : ''
    if (res.status === 'failed') ElMessage.error('失败：' + (res.error_msg || '未知错误'))
    else ElMessage.success(`落地页设置已提交${tag}`)
    landingDialog.visible = false
    await load()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  } finally {
    landingDialog.submitting = false
    savingId.value = null
  }
}

async function editBid(row) {
  const { value } = await ElMessageBox.prompt(
    `单元「${row.adgroup_name}」当前出价 ${fmtMoney(row.max_price)}。\n输入新的单元出价（¥0.01 ~ 999.99，且不超过所属计划日预算）。当前为演练模式，只记台账不真改。`,
    '修改单元出价',
    {
      confirmButtonText: '加入待回写',
      cancelButtonText: '取消',
      inputValue: row.max_price != null ? String(row.max_price) : '',
      inputPattern: /^\d+(\.\d{1,2})?$/,
      inputErrorMessage: '请输入合法金额（最多两位小数）',
    },
  ).catch(() => ({ value: null }))
  if (value == null) return

  const v = Number(value)
  if (!Number.isFinite(v) || v < 0.01 || v > 999.99) {
    ElMessage.warning('单元出价需在 ¥0.01 ~ 999.99 之间')
    return
  }
  savingId.value = row.adgroup_id
  try {
    const res = await setAdgroupBid({ tenantId: TENANT_ID.value, adgroupId: row.adgroup_id, maxPrice: v })
    const tag = res.dry_run ? '（演练：未真改）' : ''
    if (res.status === 'failed') ElMessage.error('失败：' + (res.error_msg || '未知错误'))
    else ElMessage.success(`已写回：${fmtMoney(res.old_price)} → ${fmtMoney(res.new_price)}${tag}`)
    await load()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message)
  } finally {
    savingId.value = null
  }
}

async function togglePause(row) {
  const toPause = !isPaused(row)
  try {
    await ElMessageBox.confirm(
      `确认${toPause ? '暂停' : '恢复投放'}单元「${row.adgroup_name}」？当前为演练模式，只记台账不真改。`,
      toPause ? '暂停单元' : '恢复投放',
      { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }
  savingId.value = row.adgroup_id
  try {
    const res = await setAdgroupPause({ tenantId: TENANT_ID.value, adgroupId: row.adgroup_id, pause: toPause })
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
</script>

<template>
  <div v-loading="loading">
    <div class="page-header">
      <div>
        <div class="page-title">单元管理</div>
        <div class="page-desc">按单元设出价、启停。单元出价不超过所属计划日预算；预算在「计划管理」「账户与预算」页设。</div>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" style="margin-bottom: 14px" />
    <el-alert
      type="warning"
      :closable="false"
      show-icon
      style="margin-bottom: 14px"
      title="当前为演练模式：修改出价/启停只记台账、不会真改线上百度账户。"
    />

    <div class="table-panel">
      <el-table :data="data?.adgroups || []" class="kw-table" row-key="adgroup_id">
        <el-table-column label="单元" min-width="180">
          <template #default="{ row }">
            <div class="kw-cell-name">{{ row.adgroup_name || ('#' + row.adgroup_id) }}</div>
            <div class="kw-cell-sub">{{ row.campaign_name || '—' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <span class="status-pill" :class="isPaused(row) ? 'paused' : 'active'">{{ statusLabel(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="单元出价" width="130" align="right">
          <template #default="{ row }"><span class="num" :class="{ unlimited: row.max_price == null }">{{ fmtMoney(row.max_price) }}</span></template>
        </el-table-column>
        <el-table-column label="落地页" min-width="260">
          <template #default="{ row }">
            <div v-if="landingRows(row).length" class="url-list">
              <div v-for="item in landingRows(row)" :key="item.key" class="url-line">
                <span class="url-tag" :class="item.key">{{ item.label }}</span>
                <span class="url-cell">{{ item.url }}</span>
              </div>
            </div>
            <div v-else class="url-cell empty">未设置</div>
            <div class="kw-cell-sub">
              <template v-if="row.mobile_final_url && row.pc_final_url && row.mobile_final_url !== row.pc_final_url">移动/PC 分开设置</template>
              <template v-else-if="row.mobile_final_url || row.pc_final_url">单元最终访问网址</template>
              <template v-else>从创意或关键词层级继承</template>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="300" align="center">
          <template #default="{ row }">
            <el-button size="small" :loading="savingId === row.adgroup_id" @click="editBid(row)">出价建议</el-button>
            <el-button size="small" :loading="savingId === row.adgroup_id" @click="openLanding(row)">落地页建议</el-button>
            <el-button
              size="small"
              :type="isPaused(row) ? 'success' : 'warning'"
              plain
              :loading="savingId === row.adgroup_id"
              @click="togglePause(row)"
            >{{ isPaused(row) ? '恢复投放' : '暂停' }}</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-line">{{ emptyDiagnosis }}</div>
        </template>
      </el-table>
    </div>

    <el-dialog v-model="landingDialog.visible" title="设置单元落地页" width="640px" class="landing-dialog">
      <div class="dialog-context">
        <div class="kw-cell-name">{{ landingDialog.row?.adgroup_name || '单元' }}</div>
        <div class="kw-cell-sub">{{ landingDialog.row?.campaign_name || '—' }}</div>
      </div>
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="当前为演练模式：保存后只记台账，不会真改百度线上。"
        style="margin-bottom: 14px"
      />
      <el-form label-position="top">
        <div class="form-grid">
          <el-form-item label="PC 最终访问网址">
            <el-input v-model="landingDialog.pcFinalUrl" placeholder="https://..." clearable />
          </el-form-item>
          <el-form-item label="移动最终访问网址">
            <el-input v-model="landingDialog.mobileFinalUrl" placeholder="https://..." clearable />
          </el-form-item>
          <el-form-item label="PC 监控后缀">
            <el-input v-model="landingDialog.pcTrackParam" placeholder="utm_source=baidu" clearable />
          </el-form-item>
          <el-form-item label="移动监控后缀">
            <el-input v-model="landingDialog.mobileTrackParam" placeholder="utm_source=baidu" clearable />
          </el-form-item>
          <el-form-item label="PC 第三方追踪模板">
            <el-input v-model="landingDialog.pcTrackTemplate" placeholder="https://example.com?a={lpurl}" clearable />
          </el-form-item>
          <el-form-item label="移动第三方追踪模板">
            <el-input v-model="landingDialog.mobileTrackTemplate" placeholder="https://example.com?a={lpurl}" clearable />
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="copyPcToMobile">复制 PC 到移动</el-button>
        <el-button @click="landingDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="landingDialog.submitting" @click="saveLanding">保存设置</el-button>
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
.kw-cell-sub { font-size: 11px; color: #9ca3af; margin-top: 2px; }
.url-list {
  display: grid;
  gap: 4px;
}
.url-line {
  display: grid;
  grid-template-columns: 54px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
}
.url-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 20px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  line-height: 1;
}
.url-tag.mobile { background: #e5f4ed; color: #15835b; }
.url-tag.pc { background: #e8f1ff; color: #1d5ca8; }
.url-cell {
  color: #1d4f91;
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.url-cell.empty { color: #9ca3af; }
.num { font-variant-numeric: tabular-nums; font-weight: 600; }
.num.unlimited { color: #9ca3af; font-weight: 400; }
.status-pill { font-size: 11px; padding: 1px 9px; border-radius: 10px; font-weight: 600; }
.status-pill.active { background: #e5f4ed; color: var(--sem-success); }
.status-pill.paused { background: #fef1e1; color: #ba7517; }
.empty-line { font-size: 12px; color: #9ca3af; padding: 22px 0; }
.dialog-context { margin: -4px 0 14px; }
.form-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  column-gap: 14px;
}
.landing-dialog :deep(.el-form-item__label) {
  color: #6b7280;
  font-size: 12px;
}
</style>
