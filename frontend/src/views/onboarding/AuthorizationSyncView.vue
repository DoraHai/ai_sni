<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { fetchBaiduOAuthStatus, startBaiduOAuth } from '../../api/baiduOAuth'
import { fetchTenants } from '../../api/auth'
import { fetchSemAccounts } from '../../api/moduleAssets'
import { currentTenantId, session } from '../../store/session'

const route = useRoute()
const router = useRouter()
const accounts = ref([])
const configured = ref(false)
const callbackUrl = ref('')
const loading = ref(false)
const authorizing = ref(false)
const loadError = ref('')
let pollTimer = null
let loadGeneration = 0

const tenantName = computed(
  () => session.tenants.find((tenant) => tenant.id === session.tenantId)?.name || '当前客户',
)

const canBind = computed(
  () => (!session.isLoggedIn && !!import.meta.env.VITE_API_KEY) || session.canEdit('onboarding'),
)

const activeAccounts = computed(() => accounts.value.filter((item) => item.status === 'active'))
const readinessLabel = computed(() => {
  if (!configured.value) return '待配置'
  if (activeAccounts.value.length) return '已接入'
  return '可授权'
})

function formatDate(value) {
  if (!value) return '尚未同步'
  const date = new Date(value.endsWith?.('Z') ? value : `${value}Z`)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}

function accountRoleLabel(item) {
  if (item.auth_mode !== 'oauth') return '系统接入账户'
  if (item.account_role === 'subaccount') return '子账户'
  return item.authorization_type === 2 ? '超管账户' : '普通账户'
}

function statusLabel(status) {
  return {
    active: '授权有效',
    inactive: '已取消',
    reauthorization_required: '需重新授权',
  }[status] || status
}

function syncStatusLabel(item) {
  const dataStateLabels = {
    ready: '资产已同步', partial: '资产同步不完整', empty: '已同步但暂无资产',
    not_synced: '尚未同步资产', failed: '同步失败', syncing: '正在同步', pending: '等待首次同步',
  }
  if (item.data_state && dataStateLabels[item.data_state]) return dataStateLabels[item.data_state]
  return {
    pending: '等待首次同步',
    syncing: '正在同步',
    synced: '同步完成',
    failed: '同步失败',
  }[item.sync_status] || (item.last_synced_at ? '同步完成' : '等待首次同步')
}

function scheduleStatusPoll() {
  window.clearTimeout(pollTimer)
  const shouldPoll = accounts.value.some((item) =>
    ['pending', 'syncing'].includes(item.sync_status),
  )
  if (shouldPoll) pollTimer = window.setTimeout(loadStatus, 3000)
}

async function loadStatus() {
  if (!session.tenantId) return
  const generation = ++loadGeneration
  const tenantId = session.tenantId
  loading.value = true
  loadError.value = ''
  try {
    const [result, assets] = await Promise.all([
      fetchBaiduOAuthStatus(tenantId),
      fetchSemAccounts(tenantId),
    ])
    if (generation !== loadGeneration || tenantId !== session.tenantId) return
    const assetsById = new Map((assets.accounts || []).map((item) => [item.id, item]))
    accounts.value = (result.accounts || []).map((item) => ({
      ...item,
      ...(assetsById.get(item.id) || {}),
      username: item.username,
      ucid: item.ucid,
      authorization_name: item.authorization_name,
      authorization_type: item.authorization_type,
      account_role: item.account_role,
    }))
    configured.value = !!result.configured
    callbackUrl.value = result.callback_url || ''
  } catch (error) {
    if (generation === loadGeneration) loadError.value = '账户与同步状态加载失败，请稍后重试'
  } finally {
    if (generation === loadGeneration) {
      loading.value = false
      scheduleStatusPoll()
    }
  }
}

async function startBaiduAuthorization() {
  if (!canBind.value || !session.tenantId || authorizing.value) return
  authorizing.value = true
  try {
    const result = await startBaiduOAuth({
      tenantId: session.tenantId,
      returnPath: '/onboarding',
    })
    window.location.assign(result.authorize_url)
  } catch (error) {
    ElMessage.error(error.message)
    authorizing.value = false
  }
}

async function handleAuthorizationResult() {
  if (!route.query.baidu_auth) return
  if (route.query.baidu_auth === 'success') {
    const count = Number(route.query.accounts || 0)
    const targetTenantId = Number(route.query.tenant_id || 0)
    if (targetTenantId) {
      // 回调已确认该客户归属，先切换上下文；客户列表请求失败也不应退回旧客户。
      session.setTenant(targetTenantId)
    }
    try {
      const result = await fetchTenants('sem')
      session.setTenants(result.tenants || [])
    } catch { /* 后续 loadStatus 会显示具体错误 */ }
    ElMessage.success(
      count
        ? `百度授权成功，已切换到新客户（共接入 ${count} 个账号）`
        : '百度授权成功，已切换到新客户',
    )
  } else {
    const messages = {
      invalid_app: '授权应用不匹配，请联系管理员检查配置',
      invalid_signature: '百度回调验签失败，请联系管理员',
      invalid_state: '授权请求已过期，请重新点击绑定',
      oauth_upstream: '百度授权服务暂时不可用，请稍后重试',
      oauth_rejected: '百度未接受本次授权，请重新尝试',
      internal_error: '授权处理失败，请联系管理员查看日志',
    }
    ElMessage.error(messages[route.query.code] || '百度授权未完成，请重新尝试')
  }
  await router.replace({ path: '/onboarding' })
}

watch(currentTenantId, loadStatus)
onMounted(async () => {
  await handleAuthorizationResult()
  await loadStatus()
})
onBeforeUnmount(() => window.clearTimeout(pollTimer))
</script>

<template>
  <section class="auth-page">
    <header class="page-heading">
      <div>
        <div class="eyebrow">首次接入</div>
        <h1>授权与同步</h1>
        <p>授权新的百度营销账户，系统会自动创建独立客户并开始同步投放数据。</p>
      </div>
      <div class="sync-policy">
        <span class="policy-dot" />
        数据每 15 分钟自动同步
      </div>
    </header>

    <div class="connect-card">
      <div class="connect-main">
        <div class="baidu-mark" aria-hidden="true">
          <span class="paw-dot dot-one" />
          <span class="paw-dot dot-two" />
          <span class="paw-dot dot-three" />
          <span class="paw-dot dot-four" />
          <b>百</b>
        </div>

        <div class="connect-copy">
          <div class="platform-line">
            <h2>百度推广</h2>
            <span
              class="ready-tag"
              :class="{ ready: configured, connected: activeAccounts.length }"
            >
              {{ readinessLabel }}
            </span>
          </div>
          <p>
            由客户登录百度营销账户并确认授权，无需向平台提供账户密码。
            授权后可同步计划、单元、关键词、消费与转化数据。
          </p>

          <div class="connect-actions">
            <el-tooltip
              v-if="!canBind"
              content="当前角色仅有查看权限，请联系管理员完成账户绑定"
              placement="top"
            >
              <span>
                <button class="bind-button" disabled>绑定百度推广</button>
              </span>
            </el-tooltip>
            <button
              v-else
              class="bind-button"
              :disabled="!configured || authorizing"
              @click="startBaiduAuthorization"
            >
              {{ authorizing ? '正在前往百度…' : '授权新客户账号' }}
              <span aria-hidden="true">→</span>
            </button>
            <span class="safe-note">OAuth 2.0 安全授权</span>
          </div>
        </div>
      </div>

      <div class="flow-panel">
        <div class="flow-title">授权只需三步</div>
        <ol class="flow-list">
          <li>
            <span class="step-no">1</span>
            <div>
              <b>登录百度营销</b>
              <small>进入百度官方授权页</small>
            </div>
          </li>
          <li>
            <span class="step-no">2</span>
            <div>
              <b>选择推广账户</b>
              <small>可选择普通或超管账户</small>
            </div>
          </li>
          <li>
            <span class="step-no">3</span>
            <div>
              <b>确认授权并同步</b>
              <small>返回平台后自动开始拉取</small>
            </div>
          </li>
        </ol>
      </div>
    </div>

    <div class="content-grid">
      <section class="account-panel">
        <div class="section-head">
          <div>
            <h3>已绑定账户</h3>
            <p>{{ tenantName }}对应的百度推广账户</p>
          </div>
          <span class="account-count">{{ activeAccounts.length }} 个有效账户</span>
        </div>

        <div v-if="loading" class="empty-account">
          <div class="empty-icon loading-mark" aria-hidden="true">↻</div>
          <div>
            <b>正在读取授权账户</b>
            <p>正在核对账户关系、令牌状态和最近同步时间。</p>
          </div>
        </div>

        <div v-else-if="loadError" class="empty-account">
          <div class="empty-icon error-mark" aria-hidden="true">!</div>
          <div>
            <b>授权状态读取失败</b>
            <p>{{ loadError }}</p>
          </div>
        </div>

        <div v-else-if="!accounts.length" class="empty-account">
          <div class="empty-icon" aria-hidden="true">⌁</div>
          <div>
            <b>尚未绑定百度推广账户</b>
            <p>完成首次授权后，账户名称、授权状态和最近同步时间会显示在这里。</p>
          </div>
        </div>

        <div v-else class="account-list">
          <article v-for="item in accounts" :key="item.id" class="account-row">
            <div class="account-avatar">百</div>
            <div class="account-identity">
              <div class="account-name">
                {{ item.username }}
                <span>{{ accountRoleLabel(item) }}</span>
              </div>
              <div class="account-meta">UCID {{ item.ucid }} · 授权主体 {{ item.authorization_name || '—' }}</div>
              <div v-if="item.counts" class="account-assets">
                计划 {{ item.counts.campaigns }} · 单元 {{ item.counts.adgroups }} · 关键词 {{ item.counts.keywords }} · 搜索词 {{ item.counts.search_terms }}
              </div>
            </div>
            <div class="account-sync">
              <small>{{ syncStatusLabel(item) }}</small>
              <b :class="`sync-${item.sync_status || 'pending'}`">{{ formatDate(item.last_synced_at) }}</b>
              <em v-if="item.sync_status === 'failed'" :title="item.last_sync_error || ''">系统将自动重试</em>
            </div>
            <span class="status-pill" :class="item.status">{{ statusLabel(item.status) }}</span>
          </article>
        </div>
      </section>

      <aside class="security-panel">
        <div class="shield" aria-hidden="true">✓</div>
        <div>
          <h3>授权信息由平台安全托管</h3>
          <ul>
            <li>无需保存客户的百度账户密码</li>
            <li>访问令牌加密保存并自动续期</li>
            <li>令牌失效或客户解除授权后停止同步</li>
          </ul>
        </div>
      </aside>
    </div>

    <div class="preflight-note" :class="{ warning: !configured }">
      <span class="note-mark">i</span>
      <div>
        <b>{{ configured ? '正式回调已就绪' : '还差一项服务器配置' }}</b>
        <span v-if="configured">百度授权完成后将返回 {{ callbackUrl }}，自动创建客户并开始首次同步。</span>
        <span v-else>需要在服务器配置百度应用 SecretKey 和授权链接中的 scope，完成后即可开放绑定。</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.auth-page {
  --auth-blue: #185fa5;
  --auth-blue-dark: #124c85;
  --auth-blue-soft: #edf5fc;
  --auth-ink: #1f2937;
  --auth-muted: #667085;
  --auth-line: #e4e9f0;
  min-height: calc(100vh - 122px);
  color: var(--auth-ink);
}

.page-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 20px;
}

.eyebrow {
  margin-bottom: 6px;
  color: var(--auth-blue);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.14em;
}

.page-heading h1 {
  margin: 0;
  font-size: 24px;
  font-weight: 650;
  letter-spacing: -0.02em;
}

.page-heading p {
  margin: 8px 0 0;
  color: var(--auth-muted);
  font-size: 13px;
}

.sync-policy {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border: 1px solid #cde5d9;
  border-radius: 999px;
  background: #f4fbf7;
  color: #26734d;
  font-size: 12px;
  font-weight: 600;
}

.policy-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #20a464;
  box-shadow: 0 0 0 4px rgb(32 164 100 / 12%);
}

.connect-card {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(280px, 0.72fr);
  overflow: hidden;
  border: 1px solid var(--auth-line);
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 10px 30px rgb(28 61 92 / 6%);
}

.connect-main {
  display: flex;
  align-items: flex-start;
  gap: 22px;
  padding: 32px;
}

.baidu-mark {
  position: relative;
  width: 68px;
  height: 68px;
  flex: 0 0 auto;
  border-radius: 18px;
  background: linear-gradient(145deg, #226db3, #114b83);
  box-shadow: 0 10px 22px rgb(24 95 165 / 24%);
}

.baidu-mark b {
  position: absolute;
  right: 12px;
  bottom: 8px;
  color: #fff;
  font-size: 27px;
  font-weight: 800;
  line-height: 1;
}

.paw-dot {
  position: absolute;
  border-radius: 50%;
  background: #fff;
  opacity: 0.92;
}

.dot-one { top: 13px; left: 13px; width: 9px; height: 12px; transform: rotate(-24deg); }
.dot-two { top: 8px; left: 28px; width: 10px; height: 13px; }
.dot-three { top: 12px; left: 44px; width: 9px; height: 12px; transform: rotate(24deg); }
.dot-four { top: 26px; left: 27px; width: 18px; height: 15px; }

.connect-copy { min-width: 0; }

.platform-line {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.platform-line h2 {
  margin: 0;
  font-size: 21px;
  font-weight: 650;
}

.ready-tag {
  padding: 3px 8px;
  border-radius: 999px;
  background: #fff5e7;
  color: #9a5b12;
  font-size: 11px;
  font-weight: 650;
}

.ready-tag.ready {
  background: #eaf7ef;
  color: #23734d;
}

.ready-tag.connected {
  background: #e8f2fb;
  color: #185fa5;
}

.connect-copy > p {
  max-width: 680px;
  margin: 11px 0 20px;
  color: var(--auth-muted);
  font-size: 13px;
  line-height: 1.75;
}

.connect-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.bind-button {
  display: inline-flex;
  align-items: center;
  gap: 18px;
  min-height: 40px;
  padding: 0 18px;
  border: 1px solid var(--auth-blue);
  border-radius: 7px;
  background: var(--auth-blue);
  color: #fff;
  font: inherit;
  font-size: 13px;
  font-weight: 650;
  cursor: pointer;
  box-shadow: 0 5px 14px rgb(24 95 165 / 18%);
  transition: background 160ms ease, transform 160ms ease, box-shadow 160ms ease;
}

.bind-button:hover:not(:disabled) {
  background: var(--auth-blue-dark);
  transform: translateY(-1px);
  box-shadow: 0 8px 18px rgb(24 95 165 / 23%);
}

.bind-button:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.safe-note {
  color: #7a8492;
  font-size: 12px;
}

.flow-panel {
  padding: 26px 28px;
  border-left: 1px solid var(--auth-line);
  background:
    linear-gradient(135deg, rgb(24 95 165 / 7%), transparent 52%),
    #f8fafc;
}

.flow-title {
  margin-bottom: 18px;
  color: #344054;
  font-size: 12px;
  font-weight: 700;
}

.flow-list {
  display: grid;
  gap: 17px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.flow-list li {
  display: flex;
  align-items: center;
  gap: 12px;
}

.step-no {
  display: grid;
  width: 27px;
  height: 27px;
  flex: 0 0 auto;
  place-items: center;
  border: 1px solid #c5d9ec;
  border-radius: 50%;
  background: #fff;
  color: var(--auth-blue);
  font-size: 12px;
  font-weight: 750;
}

.flow-list b,
.flow-list small {
  display: block;
}

.flow-list b {
  color: #344054;
  font-size: 12px;
  font-weight: 650;
}

.flow-list small {
  margin-top: 3px;
  color: #8a94a3;
  font-size: 11px;
}

.content-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(300px, 0.55fr);
  gap: 16px;
  margin-top: 16px;
}

.account-panel,
.security-panel {
  border: 1px solid var(--auth-line);
  border-radius: 12px;
  background: #fff;
}

.account-panel { padding: 22px 24px; }

.section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 18px;
  border-bottom: 1px solid #edf0f4;
}

.section-head h3,
.security-panel h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 650;
}

.section-head p {
  margin: 6px 0 0;
  color: var(--auth-muted);
  font-size: 12px;
}

.account-count {
  flex: 0 0 auto;
  color: #7a8492;
  font-size: 12px;
}

.empty-account {
  display: flex;
  align-items: center;
  gap: 16px;
  min-height: 112px;
  padding: 16px 6px 4px;
}

.empty-icon {
  display: grid;
  width: 42px;
  height: 42px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 12px;
  background: var(--auth-blue-soft);
  color: var(--auth-blue);
  font-size: 24px;
}

.empty-account b {
  font-size: 13px;
  font-weight: 650;
}

.empty-account p {
  margin: 6px 0 0;
  color: var(--auth-muted);
  font-size: 12px;
  line-height: 1.6;
}

.loading-mark {
  animation: auth-spin 1s linear infinite;
}

.error-mark {
  background: #fff0f0;
  color: #b33a3a;
  font-size: 16px;
  font-weight: 800;
}

@keyframes auth-spin {
  to { transform: rotate(360deg); }
}

.account-list {
  display: grid;
}

.account-row {
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr) minmax(92px, auto) auto;
  align-items: center;
  gap: 13px;
  padding: 16px 4px;
  border-bottom: 1px solid #edf0f4;
}

.account-row:last-child {
  border-bottom: 0;
  padding-bottom: 2px;
}

.account-avatar {
  display: grid;
  width: 36px;
  height: 36px;
  place-items: center;
  border-radius: 10px;
  background: #edf5fc;
  color: #185fa5;
  font-size: 15px;
  font-weight: 750;
}

.account-identity {
  min-width: 0;
}

.account-name {
  overflow: hidden;
  color: #253041;
  font-size: 13px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.account-name span {
  display: inline-block;
  margin-left: 7px;
  padding: 2px 6px;
  border-radius: 999px;
  background: #f0f2f5;
  color: #747f8d;
  font-size: 10px;
  font-weight: 600;
  vertical-align: 1px;
}

.account-meta {
  overflow: hidden;
  margin-top: 5px;
  color: #8a94a3;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.account-assets { margin-top: 4px; color: #65758b; font-size: 10px; }

.account-sync small,
.account-sync b {
  display: block;
  text-align: right;
}

.account-sync small {
  color: #98a1ad;
  font-size: 10px;
}

.account-sync b {
  margin-top: 4px;
  color: #536071;
  font-size: 11px;
  font-weight: 600;
}

.account-sync b.sync-syncing,
.account-sync b.sync-pending {
  color: #185fa5;
}

.account-sync b.sync-failed {
  color: #b54747;
}

.account-sync em {
  display: block;
  margin-top: 3px;
  color: #b54747;
  font-size: 9px;
  font-style: normal;
  text-align: right;
}

.status-pill {
  padding: 4px 8px;
  border-radius: 999px;
  background: #f0f2f5;
  color: #667085;
  font-size: 10px;
  font-weight: 650;
  white-space: nowrap;
}

.status-pill.active {
  background: #eaf7ef;
  color: #23734d;
}

.status-pill.reauthorization_required {
  background: #fff2e4;
  color: #9a5b12;
}

.security-panel {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 22px;
  background: #fbfcfe;
}

.shield {
  display: grid;
  width: 34px;
  height: 38px;
  flex: 0 0 auto;
  place-items: center;
  border: 1px solid #bcdcc9;
  border-radius: 17px 17px 12px 12px;
  background: #eff9f3;
  color: #208254;
  font-size: 14px;
  font-weight: 800;
}

.security-panel ul {
  display: grid;
  gap: 10px;
  margin: 16px 0 0;
  padding: 0;
  color: var(--auth-muted);
  font-size: 12px;
  list-style: none;
}

.security-panel li::before {
  content: '·';
  margin-right: 7px;
  color: #289764;
  font-weight: 900;
}

.preflight-note {
  display: flex;
  align-items: center;
  gap: 11px;
  margin-top: 16px;
  padding: 12px 15px;
  border: 1px solid #d9e5f1;
  border-radius: 9px;
  background: #f6f9fc;
  color: #526070;
  font-size: 12px;
}

.preflight-note.warning {
  border-color: #f0d7aa;
  background: #fffaf1;
  color: #7e5a22;
}

.note-mark {
  display: grid;
  width: 20px;
  height: 20px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 50%;
  background: #dceaf7;
  color: var(--auth-blue);
  font-weight: 750;
}

.preflight-note b { margin-right: 10px; color: #344054; }

@media (max-width: 1100px) {
  .connect-card,
  .content-grid {
    grid-template-columns: 1fr;
  }

  .flow-panel {
    border-top: 1px solid var(--auth-line);
    border-left: 0;
  }

  .flow-list {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .page-heading {
    align-items: flex-start;
    flex-direction: column;
  }

  .connect-main {
    padding: 24px 20px;
  }

  .flow-list {
    grid-template-columns: 1fr;
  }

  .content-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .account-row {
    grid-template-columns: 38px minmax(0, 1fr) auto;
  }

  .account-sync {
    display: none;
  }
}
</style>
