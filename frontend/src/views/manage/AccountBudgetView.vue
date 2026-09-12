<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { fetchAccountBudget, setAccountBudget } from '../../api/manage'
import { fetchWritebackMode, WRITEBACK_CONFIRMATION } from '../../api/writeback'
import { session } from '../../store/session'
import { createLatestRequestGuard } from '../../utils/latestRequest'
import { chooseSemAccount } from '../../utils/accountScope'
import { isSemDemoIdentity, SEM_DEMO_ACCOUNTS } from '../../utils/semDemo'
import { accountActionPreflight } from '../../utils/writebackPreflight'

const TENANT_ID = computed(() => session.tenantId) // 当前客户，顶栏切换器驱动
const demoMode = computed(() => isSemDemoIdentity(session.user, TENANT_ID.value))
const currentTenant = computed(() => session.tenants.find((row) => row.id === TENANT_ID.value))
const readableAccounts = computed(() => (
  demoMode.value ? SEM_DEMO_ACCOUNTS : (currentTenant.value?.sem_accounts || [])
).filter((row) => row.status !== 'archived'))
const activeAccounts = computed(() => readableAccounts.value.filter((row) => row.status === 'active'))
const selectedAccountIsActive = computed(() => activeAccounts.value.some((row) => row.id === selectedAccountId.value))
const selectedAccountId = ref(null)

const loading = ref(false)
const error = ref('')
const data = ref(null)
const saving = ref(false)
const input = ref(null) // 待写回的预算输入
const loadGuard = createLatestRequestGuard(() => ({
  tenantId: TENANT_ID.value,
  accountId: selectedAccountId.value,
  authRevision: session.authRevision,
}))
const saveGuard = createLatestRequestGuard(() => ({
  tenantId: TENANT_ID.value,
  accountId: selectedAccountId.value,
  authRevision: session.authRevision,
}))

async function load() {
  const attempt = loadGuard.begin()
  const { tenantId, accountId } = attempt.context
  if (!session.canView('manage.account') || !tenantId || !accountId) {
    data.value = null
    error.value = ''
    loading.value = false
    return
  }
  loading.value = true
  error.value = ''
  try {
    const result = await fetchAccountBudget({ tenantId, baiduAccountId: accountId })
    if (!attempt.isCurrent()) return
    data.value = result
    if (data.value?.status === 'ok') input.value = data.value.budget
  } catch (e) {
    if (attempt.isCurrent()) error.value = e.message
  } finally {
    if (attempt.isCurrent()) loading.value = false
  }
}

watch([TENANT_ID, readableAccounts, () => session.tenantListRevision], ([, accounts]) => {
  loadGuard.invalidate()
  saveGuard.invalidate()
  data.value = null
  error.value = ''
  loading.value = false
  saving.value = false
  input.value = null
  const previousAccountId = selectedAccountId.value
  const nextAccountId = chooseSemAccount(accounts, previousAccountId)
  selectedAccountId.value = nextAccountId
  if (nextAccountId === previousAccountId) load()
}, { immediate: true })
watch(selectedAccountId, () => {
  loadGuard.invalidate()
  saveGuard.invalidate()
  data.value = null
  error.value = ''
  loading.value = false
  saving.value = false
  input.value = null
  load()
})
watch(() => session.authRevision, () => {
  loadGuard.invalidate()
  saveGuard.invalidate()
  data.value = null
  error.value = ''
  loading.value = false
  saving.value = false
  input.value = null
  if (session.canView('manage.account')) load()
})
onBeforeUnmount(() => {
  loadGuard.invalidate()
  saveGuard.invalidate()
})

const fmtMoney = (v) => (v == null ? '—' : '¥' + Number(v).toFixed(2))
const min = computed(() => data.value?.min_budget ?? 50)
const max = computed(() => data.value?.max_budget ?? 10000000)
const ok = computed(() => data.value?.status === 'ok')

// 改动幅度提示（账户预算不像出价有 20% 硬上限，但大幅调高给个醒目提示）
const changeHint = computed(() => {
  if (!ok.value || input.value == null || data.value.budget == null || data.value.budget <= 0) return null
  const pct = Math.round((input.value - data.value.budget) / data.value.budget * 100)
  if (Math.abs(pct) < 1) return null
  return { pct, big: Math.abs(pct) >= 100 }
})

async function save() {
  if (!session.canEdit('manage.account')) return
  const attempt = saveGuard.begin()
  const { tenantId, accountId } = attempt.context
  const budgetSnapshot = data.value
  if (!tenantId || !accountId || !budgetSnapshot || !selectedAccountIsActive.value) return
  if (Number(budgetSnapshot.baidu_account_id) !== Number(accountId)) {
    ElMessage.error('当前预算数据与所选推广账户不一致，请重新读取后再提交')
    return
  }
  const v = Number(input.value)
  const minBudget = Number(budgetSnapshot.min_budget ?? 50)
  const maxBudget = Number(budgetSnapshot.max_budget ?? 10000000)
  if (!Number.isFinite(v) || v < minBudget || v > maxBudget) {
    ElMessage.warning(`日预算需在 ¥${minBudget} ~ ¥${maxBudget} 之间`)
    return
  }
  let preflight
  try {
    const mode = await fetchWritebackMode(tenantId)
    if (!attempt.isCurrent() || !selectedAccountIsActive.value) return
    preflight = accountActionPreflight(mode, {
      tenantId,
      accountId,
      scope: 'account_budget',
    })
    if (!preflight.ok) return ElMessage.error(preflight.message)
  } catch (e) {
    if (attempt.isCurrent()) {
      ElMessage.error(e.response?.data?.detail || '无法完成账户预算预检，已禁止提交，请刷新后重试')
    }
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认把账户日预算从 ${fmtMoney(budgetSnapshot.budget)} 改为 ¥${v.toFixed(2)}？\n${preflight.message}`,
      '确认修改账户日预算',
      { confirmButtonText: preflight.confirmButtonText, cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return // 用户取消
  }
  if (!attempt.isCurrent() || !selectedAccountIsActive.value) return
  saving.value = true
  try {
    const res = await setAccountBudget({
      tenantId,
      baiduAccountId: accountId,
      budget: v,
      confirmation: WRITEBACK_CONFIRMATION,
    })
    if (!attempt.isCurrent()) return
    if (res.status === 'dry_run') {
      ElMessage.success(`已加入待回写：日预算 ${fmtMoney(res.old_budget)} → ${fmtMoney(res.new_budget)}（百度账户未修改）`)
    } else if (res.status === 'success') {
      ElMessage.success(`已写回：日预算 ${fmtMoney(res.old_budget)} → ${fmtMoney(res.new_budget)}`)
    } else if (['pending', 'reconcile'].includes(res.status)) {
      ElMessage.warning(res.error_msg || '百度执行结果未知，已转入人工对账')
    } else {
      ElMessage.error('写回失败：' + (res.error_msg || '未知错误'))
    }
    await load()
  } catch (e) {
    if (attempt.isCurrent()) ElMessage.error(e.message)
  } finally {
    if (attempt.isCurrent()) saving.value = false
  }
}
</script>

<template>
  <div v-loading="loading">
    <div class="page-header">
      <div>
        <div class="page-title">账户与预算</div>
        <div class="page-desc">
          账户日预算是整个账户一天的花费上限——智能投放/OCPC 再怎么调，每天也不会超过它，是账户的“安全总闸”。
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
      title="账户预算回写受客户、推广账户和动作门禁保护；已开放动作会真实修改百度账户。"
    />

    <div v-if="readableAccounts.length > 1 || !selectedAccountIsActive" class="account-selector">
      <span>推广账户</span>
      <el-select v-model="selectedAccountId" clearable placeholder="全部账户（只读）" style="width: 260px">
        <el-option
          v-for="account in readableAccounts"
          :key="account.id"
          :label="`${account.username} · ${account.ucid}${account.status === 'active' ? '' : ' · 已停用（历史）'}`"
          :value="account.id"
        />
      </el-select>
    </div>

    <div v-if="data && data.status === 'error'" class="empty-panel">
      <b>账户预算暂不可用</b>
      <span>{{ data.message }}</span>
      <el-button size="small" @click="load">重新读取</el-button>
    </div>

    <div v-else-if="!loading && !data" class="empty-panel">
      <b>没有读取到账户预算</b>
      <span>{{ error || '请确认当前客户已绑定有效的百度推广账户。' }}</span>
      <el-button size="small" @click="load">重新读取</el-button>
    </div>

    <template v-else-if="ok">
      <!-- 账户概览 -->
      <div class="stat-grid">
        <div class="stat-card primary">
          <div class="stat-label">当前账户日预算</div>
          <div class="stat-value">{{ data.has_daily_budget ? fmtMoney(data.budget) : '未设置（不限）' }}</div>
          <div class="stat-sub">每天最多花这么多</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">账户余额</div>
          <div class="stat-value">{{ fmtMoney(data.balance) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">累计消费</div>
          <div class="stat-value">{{ fmtMoney(data.cost) }}</div>
        </div>
      </div>

      <!-- 修改日预算 -->
      <div class="edit-panel">
        <div class="edit-title">设置账户日预算</div>
        <div class="edit-row">
          <span class="prefix">¥</span>
          <el-input-number
            v-model="input"
            :min="min"
            :max="max"
            :step="50"
            :precision="2"
            controls-position="right"
            style="width: 200px"
          />
          <el-button v-if="!demoMode && session.canEdit('manage.account')" type="primary" :loading="saving" :disabled="!selectedAccountIsActive" @click="save">加入待回写</el-button>
          <span v-if="changeHint" class="change-hint" :class="{ big: changeHint.big }">
            {{ changeHint.pct > 0 ? '+' : '' }}{{ changeHint.pct }}%
            <template v-if="changeHint.big">⚠ 调整幅度较大，请确认</template>
          </span>
        </div>
        <div class="edit-note">范围 ¥{{ min }} ~ ¥{{ max.toLocaleString() }}；建议设在你能接受的每日花费上限内。</div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.page-header { margin-bottom: 14px; }
.page-title { font-size: 20px; font-weight: 600; color: var(--sem-text); }
.page-desc { font-size: 12px; color: var(--sem-text-sub); margin-top: 4px; }
.account-selector { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; font-size: 13px; color: var(--sem-text-sub); }

.stat-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 14px; }
@media (max-width: 900px) { .stat-grid { grid-template-columns: 1fr; } }
.stat-card { background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; padding: 14px 16px; }
.stat-card.primary { border-left: 4px solid var(--sem-primary); }
.stat-label { font-size: 11px; color: var(--sem-text-sub); }
.stat-value { font-size: 22px; font-weight: 700; margin-top: 8px; font-variant-numeric: tabular-nums; color: var(--sem-text); }
.stat-sub { font-size: 11px; color: #9ca3af; margin-top: 6px; }

.edit-panel { background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; padding: 18px; }
.edit-title { font-size: 14px; font-weight: 600; color: var(--sem-text); margin-bottom: 14px; }
.edit-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.prefix { font-size: 16px; color: var(--sem-text-sub); }
.change-hint { font-size: 12px; font-weight: 600; color: var(--sem-text-sub); }
.change-hint.big { color: var(--sem-danger); }
.edit-note { font-size: 11px; color: #9ca3af; margin-top: 10px; }

.empty-panel { background: #fff; border: 1px solid var(--sem-border); border-radius: 8px; padding: 36px; text-align: center; font-size: 13px; color: var(--sem-text-sub); display: flex; flex-direction: column; align-items: center; gap: 10px; }
.empty-panel b { color: var(--sem-text); font-size: 15px; }
</style>
