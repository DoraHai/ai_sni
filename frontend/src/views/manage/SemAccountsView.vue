<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { fetchSemAccounts, repairSemAccountAssets } from '../../api/moduleAssets'
import { currentTenantId } from '../../store/session'

const router = useRouter()
const loading = ref(false)
const accounts = ref([])
const repairingId = ref(null)
const summary = ref({ total: 0, active: 0, ready: 0, attention: 0 })
const stateLabels = {
  ready: '数据就绪', partial: '数据不完整', failed: '同步失败', syncing: '同步中',
  pending: '等待同步', not_synced: '尚未同步', empty: '已同步但无数据', inactive: '授权未生效',
}
const attentionAccounts = computed(() => accounts.value.filter((item) => !['ready', 'syncing', 'pending'].includes(item.data_state)))

function fmtTime(value) {
  return value ? value.slice(0, 16).replace('T', ' ') : '—'
}

async function load() {
  if (!currentTenantId.value) return
  loading.value = true
  try {
    const result = await fetchSemAccounts(currentTenantId.value)
    accounts.value = result.accounts || []
    summary.value = result.summary || { total: accounts.value.length, active: 0, ready: 0, attention: 0 }
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

async function repair(row) {
  repairingId.value = row.id
  try {
    const result = await repairSemAccountAssets(currentTenantId.value, row.id)
    const synced = result.result || {}
    ElMessage.success(`补偿同步完成：计划 ${synced.campaigns_synced || 0}、单元 ${synced.adgroups_synced || 0}、关键词 ${synced.keywords_synced || 0}、搜索词 ${synced.search_terms_synced || 0}`)
    await load()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    repairingId.value = null
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
    <el-table :data="accounts" border>
      <el-table-column prop="account_name" label="账号名称" />
      <el-table-column prop="external_account_id" label="账户 ID" />
      <el-table-column label="连接状态" width="110"><template #default="{ row }">{{ row.status === 'active' ? '授权有效' : '未生效' }}</template></el-table-column>
      <el-table-column label="数据状态" min-width="150"><template #default="{ row }"><b :class="['data-state', row.data_state]">{{ stateLabels[row.data_state] || row.data_state }}</b><small v-if="row.last_sync_error">{{ row.last_sync_error }}</small></template></el-table-column>
      <el-table-column label="已拉取资产" min-width="240"><template #default="{ row }"><span class="counts">计划 {{ row.counts?.campaigns || 0 }} · 单元 {{ row.counts?.adgroups || 0 }} · 关键词 {{ row.counts?.keywords || 0 }} · 搜索词 {{ row.counts?.search_terms || 0 }}</span></template></el-table-column>
      <el-table-column label="最近同步" min-width="150"><template #default="{ row }">{{ fmtTime(row.last_synced_at || row.last_asset_synced_at) }}</template></el-table-column>
      <el-table-column label="只读补偿" width="120"><template #default="{ row }"><el-button v-if="row.status === 'active' && row.data_state !== 'ready'" link type="primary" :loading="repairingId === row.id" @click="repair(row)">补同步</el-button><span v-else>—</span></template></el-table-column>
    </el-table>
    <el-empty v-if="!loading && !accounts.length" description="尚未授权推广账号" />
  </div>
</template>

<style scoped>
.asset-page{padding:24px}header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:20px}h2{margin:0 0 7px}p{margin:0;color:#6b7280}.summary-row{display:flex;gap:18px;margin:0 0 12px;font-size:12px;color:#667085}.summary-row .warn{color:#b15f00;font-weight:700}.data-state{display:block;color:#287a55}.data-state.partial,.data-state.failed,.data-state.not_synced,.data-state.empty{color:#b15f00}.data-state.inactive{color:#8b95a5}.data-state+small{display:block;margin-top:3px;color:#b42318;font-weight:400}.counts{font-size:12px;color:#485467}
</style>
