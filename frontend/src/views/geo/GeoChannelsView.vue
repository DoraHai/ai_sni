<script setup>
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createGeoChannelAccount,
  createGeoPublishingChannel,
  deleteGeoChannelAccount,
  deleteGeoPublishingChannel,
  listGeoChannelAccounts,
  listGeoPublishingChannels,
  patchGeoChannelAccount,
  patchGeoPublishingChannel,
  refreshSocialOAuth,
  startSocialOAuth,
  verifySocialAccount,
} from '../../api/geoContent'
import GeoAccountCredentials from '../../components/GeoAccountCredentials.vue'
import { buildAccountCredentials, credentialCheckMessage } from '../../utils/geoAccountCredentials'
import { isPersistedGeoRow, persistedGeoRows } from '../../utils/geoVirtualDefaults'
import GeoWorkbenchPage from '../../components/GeoWorkbenchPage.vue'
import { useGeoTenant } from '../../composables/useGeoTenant'

const { tenantId } = useGeoTenant()
const loading = ref(false)
const error = ref('')
const channels = ref([])
const accounts = ref([])
const channelDialogOpen = ref(false)
const accountDialogOpen = ref(false)
const channelForm = ref(emptyChannelForm())
const accountForm = ref(emptyAccountForm())
const typeFilter = ref('全部平台')
const verifying = ref(false)
const oauthBusy = ref('')
const savingAccount = ref(false)
let contextEpoch = 0
const SOCIAL_AUTH = new Set(['oauth2', 'social_api'])
function isOAuthAccount(account) { return SOCIAL_AUTH.has(account?.auth_type) }

const CHANNEL_TYPES = [
  ['website', '官网 CMS'], ['docs', '文档'], ['wechat', '微信公众号'], ['zhihu', '知乎'],
  ['baijiahao', '百家号'], ['toutiao', '头条'], ['industry_media', '行业媒体'],
  ['community_qa', '社区问答'], ['encyclopedia', '百科'], ['visual_content', '视觉内容'],
]
const CHANNEL_CN = Object.fromEntries(CHANNEL_TYPES)

function emptyChannelForm() {
  return { id: null, name: '', channel_type: 'website', publish_mode: 'draft_then_manual', base_url: '', enabled: true, source_role: '', citation_potential: '中', strategy: '', engines: '' }
}
function emptyAccountForm() {
  return { id: null, channel_id: null, display_name: '', auth_type: 'manual', status: 'active', provider: 'gateway', credential_values: {}, replace_credentials: false, original_auth_type: 'manual' }
}
function channelLabel(key) { return CHANNEL_CN[key] || key || '—' }
function rulesOf(channel) { return channel?.content_rules && typeof channel.content_rules === 'object' ? channel.content_rules : {} }
function ruleValue(channel, key, fallback = '—') { const value = rulesOf(channel)[key]; return Array.isArray(value) ? value.join(' / ') || fallback : value || fallback }
function accountCount(channelId) { return accounts.value.filter((account) => account.channel_id === channelId).length }
function publishModeLabel(mode) {
  return ({ auto_publish: '自动发布', draft_then_manual: '审核后发布', manual_only: '仅手动发布' })[mode] || '未设置'
}
function channelStatus(channel) {
  if (!isPersistedGeoRow(channel)) return { label: '默认建议', type: 'info' }
  if (!channel.enabled) return { label: '未启用', type: 'info' }
  const linked = accounts.value.filter((account) => account.channel_id === channel.id)
  if (!linked.length) return { label: '待添加账号', type: 'warning' }
  if (linked.some((account) => account.status === 'active' && account.has_credentials)) return { label: '凭据已配置', type: 'success' }
  return { label: '待配置凭证', type: 'warning' }
}

const persistedChannels = computed(() => persistedGeoRows(channels.value))
const connectedCount = computed(() => persistedChannels.value.filter((channel) => channel.enabled).length)
const readyAccountCount = computed(() => accounts.value.filter((account) => account.status === 'active' && account.has_credentials).length)
const strategyCount = computed(() => channels.value.filter((channel) => rulesOf(channel).source_role).length)
const TYPE_TABS = ['全部平台', '自有渠道', '内容平台', '新闻媒体', '外链渠道', '待接入']
const CATEGORY_BY_TYPE = {
  website: 'owned', docs: 'owned', wechat: 'content', zhihu: 'content',
  baijiahao: 'content', toutiao: 'content', visual_content: 'content',
  industry_media: 'news', community_qa: 'backlink', encyclopedia: 'backlink',
}
const FILTER_CATEGORY = {
  自有渠道: 'owned', 内容平台: 'content', 新闻媒体: 'news', 外链渠道: 'backlink',
}
function channelCategory(channel) {
  return rulesOf(channel).category || CATEGORY_BY_TYPE[channel.channel_type] || 'content'
}
const filteredChannels = computed(() => {
  if (typeFilter.value === '待接入') return channels.value.filter((channel) => !channel.enabled)
  const category = FILTER_CATEGORY[typeFilter.value]
  if (!category) return channels.value
  return channels.value.filter((channel) => channelCategory(channel) === category)
})

async function loadConfiguration() {
  if (!tenantId.value) { channels.value = []; accounts.value = []; return }
  const tenant = tenantId.value
  const epoch = contextEpoch
  const [channelResult, accountResult] = await Promise.all([listGeoPublishingChannels(tenant, false), listGeoChannelAccounts(tenant)])
  if (epoch !== contextEpoch) return
  channels.value = channelResult.items || []
  accounts.value = accountResult.items || []
}
async function refresh() {
  if (!tenantId.value) { error.value = '请先选择客户或配置本地 API Key'; return }
  loading.value = true; error.value = ''
  try { await loadConfiguration() } catch (e) { error.value = e.message || '加载失败' } finally { loading.value = false }
}

async function refreshConnectionStatus() {
  if (!tenantId.value) { error.value = '请先选择客户或配置本地 API Key'; return }
  verifying.value = true
  error.value = ''
  const checkTenant = tenantId.value
  const checkEpoch = contextEpoch
  const oauthAccounts = accounts.value.filter(a => a.auth_type !== 'manual')
  const notes = []
  for (const account of oauthAccounts) {
    try {
      if (checkEpoch !== contextEpoch) return
      const result = await verifySocialAccount(checkTenant, account.id)
      if (checkEpoch !== contextEpoch) return
      notes.push(`${account.display_name}：${credentialCheckMessage(result)}`)
    } catch (e) {
      notes.push(`${account.display_name}：${e.message || '校验失败'}`)
    }
  }
  if (checkEpoch !== contextEpoch) return
  try {
    await loadConfiguration()
    if (checkEpoch !== contextEpoch) return
    ElMessage.success(notes.length ? notes.join('；') : '已刷新平台与账号状态')
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    verifying.value = false
  }
}

async function goOAuth(account) {
  oauthBusy.value = `oauth-${account.id}`
  try {
    const result = await startSocialOAuth(tenantId.value, account.id)
    if (result?.authorize_url) {
      window.open(result.authorize_url, '_blank')
      ElMessage.success('已打开授权页，完成后点「校验」')
    } else {
      ElMessage.warning('未返回授权地址，请检查平台 OAuth 配置')
    }
  } catch (e) {
    ElMessage.error(e.message || '启动 OAuth 失败')
  } finally {
    oauthBusy.value = ''
  }
}

async function doVerifySocial(account) {
  const epoch = contextEpoch
  const tenant = tenantId.value
  oauthBusy.value = `verify-${account.id}`
  try {
    const result = await verifySocialAccount(tenant, account.id)
    if (epoch !== contextEpoch) return
    ElMessage.success(credentialCheckMessage(result))
    await loadConfiguration()
  } catch (e) {
    if (epoch === contextEpoch) ElMessage.error(e.message || '校验失败')
  } finally {
    if (epoch === contextEpoch) oauthBusy.value = ''
  }
}

async function doRefreshOAuth(account) {
  oauthBusy.value = `refresh-${account.id}`
  try {
    await refreshSocialOAuth(tenantId.value, account.id)
    ElMessage.success('已刷新授权令牌')
    await loadConfiguration()
  } catch (e) {
    ElMessage.error(e.message || '刷新失败')
  } finally {
    oauthBusy.value = ''
  }
}

function openCreateChannel() { channelForm.value = emptyChannelForm(); channelDialogOpen.value = true }
function openEditChannel(channel) {
  const rules = rulesOf(channel)
  channelForm.value = { id: isPersistedGeoRow(channel) ? channel.id : null, name: channel.name || '', channel_type: channel.channel_type, publish_mode: channel.publish_mode || 'manual_only', base_url: channel.base_url || '', enabled: !!channel.enabled, source_role: rules.source_role || '', citation_potential: rules.citation_potential || '中', strategy: rules.strategy || '', engines: Array.isArray(rules.engines) ? rules.engines.join(', ') : rules.engines || '' }
  channelDialogOpen.value = true
}
function channelPayload() {
  const form = channelForm.value
  const engines = form.engines.split(/[,，]/).map((item) => item.trim()).filter(Boolean)
  const sourceRole = form.source_role.trim()
  const strategy = form.strategy.trim()
  const geo_profile = sourceRole && strategy ? {
    category: CATEGORY_BY_TYPE[form.channel_type] || 'content',
    source_role: sourceRole,
    citation_potential: ({ 高: 'high', 中: 'medium', 低: 'low' })[form.citation_potential] || 'medium',
    geo_strategy: strategy,
    adapted_engines: engines,
  } : undefined
  return {
    name: form.name.trim() || channelLabel(form.channel_type),
    channel_type: form.channel_type,
    publish_mode: form.publish_mode,
    base_url: form.base_url.trim() || null,
    enabled: !!form.enabled,
    content_rules: {
      source_role: sourceRole || undefined,
      citation_potential: form.citation_potential || undefined,
      strategy: strategy || undefined,
      engines,
    },
    geo_profile,
  }
}
async function saveChannel() {
  try {
    const payload = channelPayload()
    if (channelForm.value.id) await patchGeoPublishingChannel(tenantId.value, channelForm.value.id, payload)
    else await createGeoPublishingChannel({ tenant_id: tenantId.value, ...payload })
    ElMessage.success(channelForm.value.id ? '平台策略已保存' : '已添加分发平台')
    channelDialogOpen.value = false
    await refresh()
  } catch (e) { ElMessage.error(e.message || '保存平台失败') }
}
async function removeChannel(channel) {
  if (!isPersistedGeoRow(channel)) {
    ElMessage.warning('这是尚未保存的默认平台，无需删除')
    return
  }
  try {
    await ElMessageBox.confirm(`删除平台「${channel.name}」及其账号？`, '删除分发平台', { type: 'warning' })
    await deleteGeoPublishingChannel(tenantId.value, channel.id, true)
    ElMessage.success('平台已删除'); await refresh()
  } catch (e) { if (e !== 'cancel' && e !== 'close') ElMessage.error(e.message || '删除平台失败') }
}

function openCreateAccount(channelId = null) {
  const selected = persistedChannels.value.find((channel) => channel.id === channelId)
    || persistedChannels.value[0]
  if (!selected) {
    ElMessage.warning('请先保存一个分发平台，再添加账号')
    return
  }
  accountForm.value = { ...emptyAccountForm(), channel_id: selected.id }
  accountDialogOpen.value = true
}
function openEditAccount(account) {
  accountForm.value = { ...emptyAccountForm(), id: account.id, channel_id: account.channel_id, display_name: account.display_name || '', auth_type: account.auth_type || 'manual', original_auth_type: account.auth_type || 'manual', status: account.status || 'active', provider: account.provider || 'gateway' }
  accountDialogOpen.value = true
}
async function saveAccount() {
  if (savingAccount.value) return
  const tenant = tenantId.value
  const epoch = contextEpoch
  try {
    const form = accountForm.value
    if (!tenant || !form.channel_id || !form.display_name.trim()) throw new Error('请选择客户、平台并填写账号名称')
    const platform = channels.value.find(c => c.id === form.channel_id)?.channel_type
    if (!platform) throw new Error('平台不属于当前客户，请刷新后重试')
    const credentials = buildAccountCredentials(form, platform)
    savingAccount.value = true
    if (form.id) await patchGeoChannelAccount(tenant, form.id, { display_name: form.display_name.trim(), auth_type: form.auth_type, status: credentials ? 'active' : form.status, ...(credentials ? { credentials } : {}) })
    else await createGeoChannelAccount({ tenant_id: tenant, channel_id: form.channel_id, display_name: form.display_name.trim(), auth_type: form.auth_type, ...(credentials ? { credentials } : {}) })
    if (epoch !== contextEpoch) return
    ElMessage.success('账号已保存，请继续检查凭据或完成授权')
    accountDialogOpen.value = false
    accountForm.value = emptyAccountForm()
    await refresh()
  } catch (e) { if (epoch === contextEpoch) ElMessage.error(e.message || '保存账号失败') }
  finally { savingAccount.value = false }
}
async function removeAccount(account) {
  try {
    await ElMessageBox.confirm(`删除账号「${account.display_name}」？`, '删除渠道账号', { type: 'warning' })
    await deleteGeoChannelAccount(tenantId.value, account.id, true)
    ElMessage.success('账号已删除'); await refresh()
  } catch (e) { if (e !== 'cancel' && e !== 'close') ElMessage.error(e.message || '删除账号失败') }
}

watch(accountDialogOpen, open => { if (!open) accountForm.value = emptyAccountForm() })
watch(tenantId, () => { contextEpoch++; verifying.value = false; oauthBusy.value = ''; accountDialogOpen.value = false; channelDialogOpen.value = false; accountForm.value = emptyAccountForm(); channels.value = []; accounts.value = []; refresh() })
onBeforeUnmount(() => { contextEpoch++; accountForm.value = emptyAccountForm() })
onMounted(refresh)
</script>

<template>
  <GeoWorkbenchPage title="分发平台" sub="维护发布账号，并按 AI 引用价值配置渠道策略" :loading="loading">
    <template #actions><button class="gd-btn" type="button" :disabled="verifying" @click="refreshConnectionStatus">{{ verifying ? '校验中…' : '刷新连接状态' }}</button><button class="gd-btn primary" type="button" @click="openCreateChannel">+ 添加分发平台</button></template>
    <div class="geo-dash channels-page">
      <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />
      <section class="context-card mb"><div><span class="kicker">Shared Accounts · GEO Strategy</span><h2>账号与 SEO 共用，发布策略按 GEO 独立配置</h2><p>同一平台账号无需重复授权；GEO 侧重点是信源权重、内容原创性、事实可核验性和被 AI 摘取的可能性。</p></div><div class="signal-grid"><span><b>{{ connectedCount }}</b> 已接入平台</span><span><b>{{ readyAccountCount }}</b> 已就绪账号</span><span><b>{{ strategyCount }}</b> 已配置策略</span></div></section>
      <section class="summary-grid mb"><div><span>已接入平台</span><b>{{ connectedCount }} / {{ channels.length }}</b><small>账号授权与 SEO 共用</small></div><div><span>GEO 推荐渠道</span><b>{{ strategyCount }}</b><small>已填写信源策略的平台</small></div><div><span>可自动推送</span><b>{{ channels.filter((c) => c.publish_mode === 'auto_publish' && c.enabled).length }}</b><small>需配有效账号</small></div><div><span>待接入</span><b>{{ channels.filter((c) => !c.enabled).length }}</b><small>禁用的平台不参与推送</small></div></section>
      <div class="filter-row mb">
        <button v-for="tab in TYPE_TABS" :key="tab" class="geo-filter" :class="{ active: typeFilter === tab }" type="button" @click="typeFilter = tab">{{ tab }}</button>
      </div>
      <section class="gd-card mb"><div class="gd-hd"><h3>平台账号与授权</h3><div class="header-actions"><button class="gd-btn" type="button" @click="openCreateAccount()">添加渠道账号</button></div></div><div class="gd-bd" style="padding:0"><el-table :data="filteredChannels" empty-text="暂无分发平台，请先添加平台" class="full-table"><el-table-column label="平台" min-width="150"><template #default="{ row }"><b>{{ row.name || channelLabel(row.channel_type) }}</b><el-tag v-if="row.virtual_default" size="small" effect="plain" type="info" class="ml">默认建议</el-tag><div class="muted">{{ row.base_url || channelLabel(row.channel_type) }}</div></template></el-table-column><el-table-column label="平台类型" width="120"><template #default="{ row }">{{ channelLabel(row.channel_type) }}</template></el-table-column><el-table-column label="发布方式" width="120"><template #default="{ row }"><el-tag size="small" effect="plain" type="info">{{ publishModeLabel(row.publish_mode) }}</el-tag></template></el-table-column><el-table-column label="账号" width="90"><template #default="{ row }">{{ accountCount(row.id) }} 个</template></el-table-column><el-table-column label="当前状态" width="120"><template #default="{ row }"><el-tag size="small" :type="channelStatus(row).type">{{ channelStatus(row).label }}</el-tag></template></el-table-column><el-table-column label="操作" width="250" fixed="right"><template #default="{ row }"><div class="channel-actions"><el-button v-if="!row.virtual_default" link @click="openCreateAccount(row.id)">添加账号</el-button><el-button link type="primary" @click="openEditChannel(row)">{{ row.virtual_default ? '保存平台' : '配置' }}</el-button><el-button v-if="!row.virtual_default" link type="danger" @click="removeChannel(row)">删除</el-button></div></template></el-table-column></el-table></div></section>
      <section class="gd-card mb"><div class="gd-hd"><h3>渠道账号</h3><span class="muted">账号授权与 SEO 共用</span></div><div class="gd-bd" style="padding:0"><el-table :data="accounts" empty-text="暂无渠道账号" class="full-table"><el-table-column label="账号" prop="display_name" min-width="180" /><el-table-column label="所属平台" min-width="130"><template #default="{ row }">{{ channels.find((c) => c.id === row.channel_id)?.name || `#${row.channel_id}` }}</template></el-table-column><el-table-column label="授权方式" prop="auth_type" width="120" /><el-table-column label="状态" width="100"><template #default="{ row }"><el-tag size="small" :type="row.status === 'active' ? 'success' : 'info'">{{ row.status || '—' }}</el-tag></template></el-table-column><el-table-column label="操作" width="260" fixed="right"><template #default="{ row }"><el-button v-if="isOAuthAccount(row)" link type="primary" :loading="oauthBusy === `oauth-${row.id}`" @click="goOAuth(row)">授权</el-button><el-button v-if="row.auth_type !== 'manual'" link :loading="oauthBusy === `verify-${row.id}`" @click="doVerifySocial(row)">检查凭据</el-button><el-button v-if="isOAuthAccount(row)" link :loading="oauthBusy === `refresh-${row.id}`" @click="doRefreshOAuth(row)">刷新令牌</el-button><el-button link type="primary" @click="openEditAccount(row)">编辑</el-button><el-button link type="danger" @click="removeAccount(row)">删除</el-button></template></el-table-column></el-table></div></section>
      <section class="gd-card mb"><div class="gd-hd"><h3>GEO 发布与信源策略</h3><span class="muted">优先选择具备稳定抓取、明确作者和可核验事实的平台</span></div><div class="gd-bd" style="padding:0"><el-table :data="filteredChannels" empty-text="配置平台后可维护 GEO 策略" class="full-table"><el-table-column label="平台" min-width="140"><template #default="{ row }">{{ row.name || channelLabel(row.channel_type) }}</template></el-table-column><el-table-column label="信源角色" min-width="130"><template #default="{ row }">{{ ruleValue(row, 'source_role') }}</template></el-table-column><el-table-column label="AI 引用潜力" width="120"><template #default="{ row }">{{ ruleValue(row, 'citation_potential') }}</template></el-table-column><el-table-column label="内容策略" min-width="230"><template #default="{ row }">{{ ruleValue(row, 'strategy') }}</template></el-table-column><el-table-column label="适配引擎" min-width="140"><template #default="{ row }">{{ ruleValue(row, 'engines') }}</template></el-table-column><el-table-column label="当前状态" width="105"><template #default="{ row }"><el-tag size="small" :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '策略可用' : '未启用' }}</el-tag></template></el-table-column></el-table></div></section>
    </div>
    <el-dialog v-model="channelDialogOpen" :title="channelForm.id ? '配置分发平台' : '添加分发平台'" width="560px"><el-form label-width="110px"><el-form-item label="平台名称"><el-input v-model="channelForm.name" placeholder="例如：行业技术媒体" /></el-form-item><el-form-item label="平台类型"><el-select v-model="channelForm.channel_type" style="width:100%"><el-option v-for="[value, label] in CHANNEL_TYPES" :key="value" :value="value" :label="label" /></el-select></el-form-item><el-form-item label="发布方式"><el-select v-model="channelForm.publish_mode" style="width:100%"><el-option label="自动发布" value="auto_publish" /><el-option label="出稿后人工发" value="draft_then_manual" /><el-option label="仅人工" value="manual_only" /></el-select></el-form-item><el-form-item label="接口 / 主页"><el-input v-model="channelForm.base_url" placeholder="https:// 或 API Endpoint" /></el-form-item><el-divider>GEO 发布与信源策略</el-divider><el-form-item label="信源角色"><el-input v-model="channelForm.source_role" placeholder="如：品牌事实底座" /></el-form-item><el-form-item label="AI 引用潜力"><el-select v-model="channelForm.citation_potential" style="width:100%"><el-option label="高" value="高" /><el-option label="中" value="中" /><el-option label="低" value="低" /></el-select></el-form-item><el-form-item label="内容策略"><el-input v-model="channelForm.strategy" type="textarea" placeholder="如：原创首发、明确作者、可核验事实" /></el-form-item><el-form-item label="适配引擎"><el-input v-model="channelForm.engines" placeholder="如：DeepSeek, Kimi" /></el-form-item><el-form-item label="启用"><el-switch v-model="channelForm.enabled" /></el-form-item></el-form><template #footer><el-button @click="channelDialogOpen = false">取消</el-button><el-button type="primary" @click="saveChannel">保存平台</el-button></template></el-dialog>
    <el-dialog :close-on-click-modal="!savingAccount" :close-on-press-escape="!savingAccount" :show-close="!savingAccount" v-model="accountDialogOpen" :title="accountForm.id ? '编辑渠道账号' : '添加渠道账号'" width="520px"><el-form label-width="115px" :disabled="savingAccount"><el-form-item label="所属平台"><el-select v-model="accountForm.channel_id" :disabled="!!accountForm.id || savingAccount" style="width:100%"><el-option v-for="channel in persistedChannels" :key="channel.id" :label="channel.name || channelLabel(channel.channel_type)" :value="channel.id" /></el-select></el-form-item><el-form-item label="账号名称"><el-input v-model="accountForm.display_name" placeholder="账号名称或 App ID" /></el-form-item><el-form-item label="授权方式"><el-select v-model="accountForm.auth_type" style="width:100%"><el-option label="人工回填" value="manual" /><el-option label="Webhook" value="webhook" /><el-option label="OAuth2" value="oauth2" /><el-option label="社交直发" value="social_api" /></el-select></el-form-item><GeoAccountCredentials :form="accountForm" /><el-form-item v-if="accountForm.id" label="状态"><el-select v-model="accountForm.status" style="width:100%"><el-option label="有效" value="active" /><el-option label="未配置" value="unconfigured" /><el-option label="已禁用" value="disabled" /></el-select></el-form-item></el-form><template #footer><el-button :disabled="savingAccount" @click="accountDialogOpen = false">取消</el-button><el-button type="primary"  :loading="savingAccount" @click="saveAccount">保存账号</el-button></template></el-dialog>
  </GeoWorkbenchPage>
</template>

<style scoped>
.mb { margin-bottom:14px; }.channels-page { padding-bottom:16px; }.context-card { display:flex; justify-content:space-between; gap:24px; padding:22px; border:1px solid #ddd6fe; border-radius:12px; background:linear-gradient(110deg,#faf8ff,#fff); }.context-card h2 { margin:5px 0; font-size:19px; }.context-card p,.muted { color:#64748b; font-size:12px; }.kicker { color:#7c3aed; font-size:12px; font-weight:800; }.signal-grid,.summary-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; align-content:center; }.signal-grid span { white-space:nowrap; color:#64748b; font-size:12px; }.signal-grid b { color:#4c1d95; font-size:18px; }.summary-grid { grid-template-columns:repeat(4,1fr); }.summary-grid>div { display:grid; gap:5px; padding:14px; border:1px solid #e5e7eb; border-radius:10px; background:#fff; }.summary-grid span,.summary-grid small { color:#64748b; font-size:12px; }.summary-grid b { font-size:20px; color:#1e293b; }.header-actions { margin-left:auto; }.full-table { width:100%; }.channel-actions { display:flex; align-items:center; gap:2px; white-space: nowrap; }.channel-actions .el-button + .el-button { margin-left:0; }.filter-row { display:flex; flex-wrap:wrap; gap:8px; }.geo-filter { border:1px solid #e7e9ef; background:#fff; border-radius:999px; padding:4px 10px; font-size:12px; cursor:pointer; }.geo-filter.active { background:#eef0ff; border-color:#c9ccf5; color:#4338ca; font-weight:700; } @media (max-width:800px) { .context-card { display:block; }.signal-grid,.summary-grid { grid-template-columns:repeat(2,1fr); margin-top:16px; } }
</style>
