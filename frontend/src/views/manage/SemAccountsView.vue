<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { fetchSemAccounts } from '../../api/moduleAssets'
import { currentTenantId } from '../../store/session'

const router = useRouter()
const loading = ref(false)
const accounts = ref([])

async function load() {
  if (!currentTenantId.value) return
  loading.value = true
  try {
    accounts.value = (await fetchSemAccounts(currentTenantId.value)).accounts || []
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
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
    <el-table :data="accounts" border>
      <el-table-column prop="account_name" label="账号名称" />
      <el-table-column prop="external_account_id" label="账户 ID" />
      <el-table-column prop="status" label="状态" width="100" />
      <el-table-column prop="sync_status" label="同步状态" width="120" />
      <el-table-column prop="last_synced_at" label="最近同步" min-width="170" />
    </el-table>
    <el-empty v-if="!loading && !accounts.length" description="尚未授权推广账号" />
  </div>
</template>

<style scoped>
.asset-page{padding:24px}header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:20px}h2{margin:0 0 7px}p{margin:0;color:#6b7280}
</style>
