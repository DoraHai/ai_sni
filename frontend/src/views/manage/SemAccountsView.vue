<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { fetchSemAccounts, repairSemAccountAssets } from '../../api/moduleAssets'
import { currentTenantId } from '../../store/session'

const router = useRouter()
const route = useRoute()
const loading = ref(false)
const accounts = ref([])
const repairingKey = ref('')
const summary = ref({ total: 0, active: 0, ready: 0, attention: 0 })
let loadGeneration = 0
const stateLabels = {
  ready: '数据就绪', partial: '数据不完整', failed: '同步失败', syncing: '同步中',
  pending: '等待同步', not_synced: '尚未同步', empty: '已同步但无数据', inactive: '授权未生效',
}
const dimensionLabels = {
  campaigns: '计划', adgroups: '单元', keywords: '关键词', search_terms: '搜索词',
}
const dimensionStateLabels = {
  success: '同步成功', empty: '已同步无数据', preserved: '保留旧数据', failed: '同步失败',
  syncing: '同步中', pending: '等待同步', not_synced: '尚未同步',
}
const attentionAccounts = computed(() => accounts.value.filter((item) => !['ready', 'syncing', 'pending'].includes(item.data_state)))
const focusedAccountId = computed(() => Number(route.query.account_id) || null)
const accountRowClass = ({ row }) => row.id === focusedAccountId.value ? 'focused-account-row' : ''

function fmtTime(value) {
  return value ? value.slice(0, 16).replace('T', ' ') : '—'
}

async function load() {
  const generation = ++loadGeneration
  const tenantId = currentTenantId.value
  if (!tenantId) {
    accounts.value = []
    summary.value = { total: 0, active: 0, ready: 0, attention: 0 }
    loading.value = false
    return
  }
  loading.value = true
  try {
    const result = await fetchSemAccounts(tenantId)
    if (generation !== loadGeneration || tenantId !== currentTenantId.value) return
    accounts.value = result.accounts || []
    summary.value = result.summary || { total: accounts.value.length, active: 0, ready: 0, attention: 0 }
  } catch (error) {
    if (generation === loadGeneration && tenantId === currentTenantId.value) {
      accounts.value = []
      summary.value = { total: 0, active: 0, ready: 0, attention: 0 }
      ElMessage.error(error.message)
    }
  } finally {
    if (generation === loadGeneration) loading.value = false
  }
}

async function repair(row, dimension = null) {
  const key = `${row.id}:${dimension || 'all'}`
  repairingKey.value = key
  try {
    const result = await repairSemAccountAssets(
      currentTenantId.value, row.id, dimension,
    )
    const synced = result.result || {}
    const message = dimension
      ? `${dimensionLabels[dimension]}同步完成`
      : `同步完成：计划 ${synced.campaigns_synced || 0}、单元 ${synced.adgroups_synced || 0}、关键词 ${synced.keywords_synced || 0}、搜索词 ${synced.search_terms_synced || 0}`
    if (synced.status === 'partial') ElMessage.warning('部分维度同步失败，可展开账号后单独重试')
    else ElMessage.success(message)
    await load()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    repairingKey.value = ''
  }
}

watch(currentTenantId, load)
onMounted(load)
</script>

<template>
  <div class="asset-page" v-loading="loading">
    <header>
      <div>
        <h2>推广账号</h2>
        <p>当前客户可以维护多个百度推广账号，每个账号的数据独立同步和操作。</p>
      </div>
      <el-button type="primary" @click="router.push('/onboarding')">授权新账号</el-button>
    </header>
    <el-alert
      v-if="attentionAccounts.length"
      type="warning"
      :closable="false"
      show-icon
      title="账户已连接，但部分只读数据尚未就绪。请根据下方状态检查同步，不代表需要重新授权。"
      style="margin-bottom: 14px"
    />
    <div class="summary-row">
      <span>账户 {{ summary.total }}</span><span>有效 {{ summary.active }}</span><span>数据就绪 {{ summary.ready }}</span><span :class="{ warn: summary.attention }">需关注 {{ summary.attention }}</span>
    </div>
    <el-table :data="accounts" border :row-class-name="accountRowClass">
      <el-table-column type="expand">
        <template #default="{ row }">
          <div class="dimension-panel">
            <div v-for="(label, key) in dimensionLabels" :key="key" class="dimension-card">
              <div><b>{{ label }}</b><span>{{ row.dimensions?.[key]?.count || 0 }} 条</span></div>
              <p :class="['dimension-state', row.dimensions?.[key]?.status]">
                {{ dimensionStateLabels[row.dimensions?.[key]?.status] || row.dimensions?.[key]?.status }}
                <small>{{ fmtTime(row.dimensions?.[key]?.finished_at) }}</small>
              </p>
              <p v-if="row.dimensions?.[key]?.error" class="dimension-error">{{ row.dimensions[key].error }}</p>
              <el-button
                v-if="row.status === 'active'"
                link type="primary"
                :loading="repairingKey === `${row.id}:${key}`"
                :disabled="Boolean(repairingKey) && repairingKey !== `${row.id}:${key}`"
                @click="repair(row, key)"
              >重试此维度</el-button>
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="account_name" label="账号名称" />
      <el-table-column prop="external_account_id" label="账户 ID" />
      <el-table-column label="连接状态" width="110"><template #default="{ row }">{{ row.status === 'active' ? '授权有效' : '未生效' }}</template></el-table-column>
      <el-table-column label="数据状态" min-width="150"><template #default="{ row }"><b :class="['data-state', row.data_state]">{{ stateLabels[row.data_state] || row.data_state }}</b><small v-if="row.last_sync_error">{{ row.last_sync_error }}</small></template></el-table-column>
      <el-table-column label="已拉取资产" min-width="240"><template #default="{ row }"><span class="counts">计划 {{ row.counts?.campaigns || 0 }} · 单元 {{ row.counts?.adgroups || 0 }} · 关键词 {{ row.counts?.keywords || 0 }} · 搜索词 {{ row.counts?.search_terms || 0 }}</span></template></el-table-column>
      <el-table-column label="最近同步" min-width="150"><template #default="{ row }">{{ fmtTime(row.last_synced_at || row.last_asset_synced_at) }}</template></el-table-column>
      <el-table-column label="只读同步" width="120"><template #default="{ row }"><el-button v-if="row.status === 'active'" link type="primary" :loading="repairingKey === `${row.id}:all`" :disabled="Boolean(repairingKey) && repairingKey !== `${row.id}:all`" @click="repair(row)">同步全部</el-button><span v-else>—</span></template></el-table-column>
      <template #empty><div class="account-empty">{{ loading ? '正在读取推广账户…' : '尚未授权推广账号' }}</div></template>
    </el-table>
  </div>
</template>

<style scoped>
.asset-page{padding:24px}header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:20px}h2{margin:0 0 7px}p{margin:0;color:#6b7280}.summary-row{display:flex;gap:18px;margin:0 0 12px;font-size:12px;color:#667085}.summary-row .warn{color:#b15f00;font-weight:700}.data-state{display:block;color:#287a55}.data-state.partial,.data-state.failed,.data-state.not_synced,.data-state.empty{color:#b15f00}.data-state.inactive{color:#8b95a5}.data-state+small{display:block;margin-top:3px;color:#b42318;font-weight:400}.counts{font-size:12px;color:#485467}.account-empty{padding:28px;color:#8b95a5}
.dimension-panel{display:grid;grid-template-columns:repeat(4,minmax(160px,1fr));gap:12px;padding:14px 44px}.dimension-card{padding:12px;border:1px solid #e5e7eb;border-radius:8px;background:#fff}.dimension-card>div{display:flex;justify-content:space-between;color:#344054}.dimension-card>div span,.dimension-state small{font-size:12px;color:#667085}.dimension-state{margin:9px 0 5px;font-size:12px;color:#287a55}.dimension-state.failed,.dimension-state.not_synced,.dimension-state.empty{color:#b15f00}.dimension-state small{margin-left:6px}.dimension-error{margin:0 0 5px;color:#b42318;font-size:12px;overflow-wrap:anywhere}@media(max-width:1100px){.dimension-panel{grid-template-columns:repeat(2,minmax(160px,1fr))}}
:deep(.focused-account-row)>td{background:#fff8e6!important}
</style>
