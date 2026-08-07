<script setup>
/**
 * 发布渠道管理
 * ① 渠道目录：类型 / 发布模式（auto_publish 可 Webhook 自动推）
 * ② 渠道账号：按页签；auto 渠道强制配置 Webhook 自动化参数
 */
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createGeoChannelAccount,
  createGeoPublishingChannel,
  deleteGeoChannelAccount,
  deleteGeoPublishingChannel,
  enableMultiMediaAutoPack,
  fetchAutoPushStatus,
  listGeoChannelAccounts,
  listGeoPublishingChannels,
  patchGeoChannelAccount,
  patchGeoPublishingChannel,
  refreshSocialOAuth,
  startSocialOAuth,
  verifySocialAccount,
} from '../../api/geoContent'
import { useGeoTenant } from '../../composables/useGeoTenant'

const { tenantId } = useGeoTenant()
const loading = ref(false)
const error = ref('')
const channels = ref([])
const accounts = ref([])
const activeTab = ref('all')
const autoMatrix = ref(null)
const enablingPack = ref(false)

const createChOpen = ref(false)
const createAccOpen = ref(false)
const editAccOpen = ref(false)
const editChOpen = ref(false)

const CHANNEL_TYPES = [
  { value: 'website', label: 'website · 官网（Webhook）', auto: true, social: false },
  { value: 'docs', label: 'docs · 文档（Webhook）', auto: true, social: false },
  { value: 'wechat', label: 'wechat · 公众号（wechat_mp / OAuth / 网关）', auto: true, social: true },
  { value: 'zhihu', label: 'zhihu · 知乎（OAuth2 / 网关）', auto: true, social: true },
  { value: 'baijiahao', label: 'baijiahao · 百家号（OAuth2 / 网关）', auto: true, social: true },
  { value: 'toutiao', label: 'toutiao · 头条（OAuth2 / 网关）', auto: true, social: true },
  { value: 'industry_media', label: 'industry_media · 行业媒体（人工回填）', auto: false, social: false },
]

const SOCIAL_TYPES = new Set(['wechat', 'zhihu', 'baijiahao', 'toutiao'])

const PUBLISH_MODES = [
  {
    value: 'auto_publish',
    label: 'auto_publish · 可自动推送（Webhook）',
    tip: '任务审校通过后，可对已导出渠道稿一键 Webhook 推送',
  },
  {
    value: 'draft_then_manual',
    label: 'draft_then_manual · 出稿后人工发',
    tip: '系统生成适配稿，运营在平台发完后回填 URL',
  },
  {
    value: 'manual_only',
    label: 'manual_only · 仅人工',
    tip: '不走自动推送，仅作登记与回填',
  },
]

const chForm = ref({
  channel_type: 'website',
  name: '',
  publish_mode: 'auto_publish',
  base_url: '',
  enabled: true,
})

const editChForm = ref({
  id: null,
  name: '',
  publish_mode: 'auto_publish',
  base_url: '',
  enabled: true,
})

const accForm = ref({
  channel_id: null,
  display_name: '',
  auth_type: 'webhook',
  webhook_url: '',
  method: 'POST',
  secret: '',
  headers_json: '',
  // social
  provider: 'wechat_mp', // wechat_mp | gateway | oauth2
  platform: 'wechat',
  api_url: '',
  access_token: '',
  app_id: '',
  app_secret: '',
  client_id: '',
  client_secret: '',
  authorize_url: '',
  token_url: '',
  redirect_uri: '',
  scope: '',
})

const editForm = ref({
  id: null,
  display_name: '',
  auth_type: 'webhook',
  webhook_url: '',
  method: 'POST',
  secret: '',
  headers_json: '',
  platform: 'wechat',
  api_url: '',
  access_token: '',
  clear_credentials: false,
  status: 'active',
})

function channelById(id) {
  return channels.value.find((x) => x.id === Number(id)) || null
}

function isAutoPublish(ch) {
  if (!ch) return false
  return String(ch.publish_mode || '') === 'auto_publish'
}

function typeSupportsWebhook(channelType) {
  const t = String(channelType || '').toLowerCase()
  return t === 'website' || t === 'docs'
}

function typeSupportsSocial(channelType) {
  return SOCIAL_TYPES.has(String(channelType || '').toLowerCase())
}

function defaultAuthForChannel(channelId) {
  const ch = channelById(channelId)
  if (typeSupportsSocial(ch?.channel_type)) return 'social_api'
  if (typeSupportsWebhook(ch?.channel_type)) return 'webhook'
  return 'manual'
}

function modeLabel(mode) {
  const m = PUBLISH_MODES.find((x) => x.value === mode)
  return m ? m.label.split(' · ')[1] || mode : mode || '—'
}

function modeTagType(mode) {
  if (mode === 'auto_publish') return 'success'
  if (mode === 'draft_then_manual') return 'warning'
  return 'info'
}

const channelTabs = computed(() => {
  const list = (channels.value || []).map((c) => {
    const accs = (accounts.value || []).filter((a) => a.channel_id === c.id)
    const webhookReady = accs.some(
      (a) =>
        (a.auth_type === 'webhook' || a.auth_type === 'social_api') &&
        a.has_credentials &&
        a.status === 'active',
    )
    return {
      key: String(c.id),
      id: c.id,
      label: c.name || c.channel_type,
      type: c.channel_type,
      enabled: c.enabled,
      publish_mode: c.publish_mode,
      auto: isAutoPublish(c),
      count: accs.filter((a) => a.status !== 'disabled').length,
      webhookReady,
    }
  })
  return [
    {
      key: 'all',
      id: null,
      label: '全部',
      type: '',
      enabled: true,
      auto: false,
      count: accounts.value.length,
      webhookReady: false,
    },
    ...list,
  ]
})

const activeChannel = computed(() =>
  activeTab.value === 'all' ? null : channelById(activeTab.value),
)

const filteredAccounts = computed(() => {
  let rows = accounts.value || []
  if (activeTab.value !== 'all') {
    const cid = Number(activeTab.value)
    rows = rows.filter((a) => a.channel_id === cid)
  }
  return rows
})

const autoChannels = computed(() =>
  (channels.value || []).filter((c) => isAutoPublish(c) && c.enabled),
)

async function load() {
  if (!tenantId.value) {
    error.value = '请先选择客户或配置本地 API Key'
    channels.value = []
    accounts.value = []
    return
  }
  loading.value = true
  error.value = ''
  try {
    const [ch, acc] = await Promise.all([
      listGeoPublishingChannels(tenantId.value, false),
      listGeoChannelAccounts(tenantId.value),
    ])
    channels.value = ch.items || []
    accounts.value = acc.items || []
    try {
      autoMatrix.value = await fetchAutoPushStatus(tenantId.value)
    } catch {
      autoMatrix.value = null
    }
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function enableMediaPack() {
  enablingPack.value = true
  try {
    const res = await enableMultiMediaAutoPack(tenantId.value)
    autoMatrix.value = res.matrix || null
    ElMessage.success(
      `已开启多媒 auto_publish（更新 ${res.channels_updated ?? 0} 条）。请为未就绪渠道配置凭证。`,
    )
    await load()
  } catch (e) {
    ElMessage.error(e.message || '开启失败')
  } finally {
    enablingPack.value = false
  }
}

function defaultModeForType(ctype) {
  return typeSupportsWebhook(ctype) ? 'auto_publish' : 'draft_then_manual'
}

function onCreateChTypeChange(t) {
  chForm.value.publish_mode = defaultModeForType(t)
}

async function createChannel() {
  try {
    await createGeoPublishingChannel({
      tenant_id: tenantId.value,
      channel_type: chForm.value.channel_type,
      name: chForm.value.name.trim() || chForm.value.channel_type,
      publish_mode: chForm.value.publish_mode || defaultModeForType(chForm.value.channel_type),
      base_url: chForm.value.base_url.trim() || null,
      enabled: chForm.value.enabled,
    })
    ElMessage.success('已创建渠道')
    createChOpen.value = false
    await load()
  } catch (e) {
    ElMessage.error(e.message || '创建失败')
  }
}

function openEditChannel(row) {
  editChForm.value = {
    id: row.id,
    name: row.name || '',
    publish_mode: row.publish_mode || 'manual_only',
    base_url: row.base_url || '',
    enabled: !!row.enabled,
  }
  editChOpen.value = true
}

async function saveEditChannel() {
  try {
    await patchGeoPublishingChannel(tenantId.value, editChForm.value.id, {
      name: editChForm.value.name.trim() || undefined,
      publish_mode: editChForm.value.publish_mode,
      base_url: editChForm.value.base_url.trim() || null,
      enabled: editChForm.value.enabled,
    })
    ElMessage.success('渠道配置已保存')
    editChOpen.value = false
    await load()
  } catch (e) {
    ElMessage.error(e.message || '保存失败')
  }
}

async function toggleChannel(row) {
  try {
    await patchGeoPublishingChannel(tenantId.value, row.id, { enabled: !row.enabled })
    ElMessage.success(row.enabled ? '已禁用渠道' : '已启用渠道')
    await load()
  } catch (e) {
    ElMessage.error(e.message || '更新失败')
  }
}

async function removeChannel(row) {
  try {
    await ElMessageBox.confirm(
      `物理删除渠道「${row.name}」及其账号？不可恢复。`,
      '删除渠道',
      { type: 'error', confirmButtonText: '删除' },
    )
    await deleteGeoPublishingChannel(tenantId.value, row.id, true)
    ElMessage.success('渠道已删除')
    await load()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error(e.message || '删除失败')
  }
}

function parseHeaders(jsonStr) {
  const s = String(jsonStr || '').trim()
  if (!s) return {}
  try {
    const obj = JSON.parse(s)
    if (obj && typeof obj === 'object' && !Array.isArray(obj)) return obj
  } catch {
    throw new Error('Headers 须为 JSON 对象，如 {"Authorization":"Bearer xxx"}')
  }
  throw new Error('Headers 须为 JSON 对象')
}

function buildWebhookCredentials(form) {
  const url = form.webhook_url.trim()
  if (!url.startsWith('https://')) {
    throw new Error('Webhook URL 必须是公网 https://（禁止 127.0.0.1 / 内网）')
  }
  const creds = {
    webhook_url: url,
    method: form.method || 'POST',
    headers: parseHeaders(form.headers_json),
  }
  if (form.secret?.trim()) creds.secret = form.secret.trim()
  return creds
}

function buildSocialCredentials(form, channelType) {
  const platform = (form.platform || channelType || 'wechat').toLowerCase()
  const provider = (form.provider || (platform === 'wechat' ? 'wechat_mp' : 'gateway')).toLowerCase()

  if (provider === 'wechat_mp') {
    const app_id = (form.app_id || '').trim()
    const app_secret = (form.app_secret || '').trim()
    if (!app_id || !app_secret) throw new Error('微信公众号需要 app_id 与 app_secret')
    return {
      provider: 'wechat_mp',
      platform: 'wechat',
      app_id,
      app_secret,
      mode_default: 'draft',
    }
  }

  if (provider === 'oauth2') {
    const client_id = (form.client_id || '').trim()
    const client_secret = (form.client_secret || '').trim()
    const authorize_url = (form.authorize_url || '').trim()
    const token_url = (form.token_url || '').trim()
    const api_url = (form.api_url || '').trim()
    const redirect_uri = (form.redirect_uri || '').trim()
    if (!client_id || !client_secret) throw new Error('OAuth2 需要 client_id / client_secret')
    if (!authorize_url || !token_url) throw new Error('OAuth2 需要 authorize_url / token_url')
    if (!api_url) throw new Error('OAuth2 推送需要 api_url（发布接口）')
    if (!redirect_uri) throw new Error('OAuth2 需要 redirect_uri（回调地址）')
    return {
      provider: 'oauth2',
      platform,
      client_id,
      client_secret,
      authorize_url,
      token_url,
      api_url,
      redirect_uri,
      scope: (form.scope || '').trim() || undefined,
      method: form.method || 'POST',
      headers: parseHeaders(form.headers_json),
    }
  }

  // gateway
  const api_url = (form.api_url || '').trim()
  if (!api_url.startsWith('https://')) {
    throw new Error('网关 api_url 必须是 https://（官方 API 或自建转发）')
  }
  const token = (form.access_token || '').trim()
  if (!token) throw new Error('gateway 模式 access_token 必填')
  return {
    provider: 'gateway',
    platform,
    api_url,
    access_token: token,
    method: form.method || 'POST',
    headers: parseHeaders(form.headers_json),
  }
}

function openCreateAccount(prefillChannelId) {
  const cid =
    prefillChannelId ||
    (activeTab.value !== 'all' ? Number(activeTab.value) : null) ||
    autoChannels.value[0]?.id ||
    channels.value[0]?.id ||
    null
  const ch = channelById(cid)
  const auth = defaultAuthForChannel(cid)
  accForm.value = {
    channel_id: cid,
    display_name: '',
    auth_type: auth,
    webhook_url: '',
    method: 'POST',
    secret: '',
    headers_json: '',
    platform: typeSupportsSocial(ch?.channel_type) ? ch.channel_type : 'wechat',
    api_url: '',
    access_token: '',
  }
  createAccOpen.value = true
}

function onAccChannelChange(cid) {
  const ch = channelById(cid)
  accForm.value.auth_type = defaultAuthForChannel(cid)
  if (typeSupportsSocial(ch?.channel_type)) {
    accForm.value.platform = ch.channel_type
    accForm.value.provider = ch.channel_type === 'wechat' ? 'wechat_mp' : 'oauth2'
  }
}

async function goOAuth(row) {
  try {
    const r = await startSocialOAuth(tenantId.value, row.id)
    if (r?.authorize_url) {
      window.open(r.authorize_url, '_blank')
      ElMessage.success('已打开授权页，完成后回来点「校验」')
    } else {
      ElMessage.warning('未返回 authorize_url')
    }
  } catch (e) {
    ElMessage.error(e.message || '启动 OAuth 失败')
  }
}

async function doVerifySocial(row) {
  try {
    const r = await verifySocialAccount(tenantId.value, row.id)
    ElMessage.success(
      r.mock ? '凭证校验通过（mock）' : r.oauth_authorized === false ? '未授权' : '凭证校验通过',
    )
    await load()
  } catch (e) {
    ElMessage.error(e.message || '校验失败')
  }
}

async function doRefreshOAuth(row) {
  try {
    await refreshSocialOAuth(tenantId.value, row.id)
    ElMessage.success('已刷新 access_token')
    await load()
  } catch (e) {
    ElMessage.error(e.message || '刷新失败')
  }
}

async function createAccount() {
  if (!accForm.value.channel_id || !accForm.value.display_name.trim()) {
    ElMessage.warning('请选择渠道并填写显示名')
    return
  }
  const ch = channelById(accForm.value.channel_id)
  if (
    isAutoPublish(ch) &&
    typeSupportsWebhook(ch?.channel_type) &&
    accForm.value.auth_type !== 'webhook'
  ) {
    ElMessage.warning('官网/文档 auto_publish 请使用 Webhook')
    accForm.value.auth_type = 'webhook'
    return
  }
  if (
    isAutoPublish(ch) &&
    typeSupportsSocial(ch?.channel_type) &&
    !['social_api', 'oauth2'].includes(accForm.value.auth_type)
  ) {
    ElMessage.warning('社交渠道 auto_publish 请使用 social_api 或 oauth2')
    accForm.value.auth_type = 'social_api'
    return
  }
  try {
    const body = {
      tenant_id: tenantId.value,
      channel_id: accForm.value.channel_id,
      display_name: accForm.value.display_name.trim(),
      auth_type:
        accForm.value.provider === 'oauth2' ? 'oauth2' : accForm.value.auth_type,
      credentials: null,
    }
    if (accForm.value.auth_type === 'webhook') {
      body.credentials = buildWebhookCredentials(accForm.value)
    } else if (['social_api', 'oauth2'].includes(accForm.value.auth_type) || typeSupportsSocial(ch?.channel_type)) {
      body.credentials = buildSocialCredentials(accForm.value, ch?.channel_type)
      if (accForm.value.provider === 'oauth2') body.auth_type = 'oauth2'
      else body.auth_type = 'social_api'
    }
    const created = await createGeoChannelAccount(body)
    ElMessage.success(
      body.auth_type === 'webhook'
        ? '已创建 Webhook 账号'
        : body.auth_type === 'oauth2'
          ? '已创建 OAuth2 账号（请点「去授权」完成授权）'
          : accForm.value.provider === 'wechat_mp'
            ? '已创建微信公众号账号（可点「校验凭证」）'
            : '已创建社交直发账号',
    )
    createAccOpen.value = false
    await load()
    if (body.auth_type === 'oauth2' && created?.id) {
      // optional: user clicks 去授权
    }
  } catch (e) {
    ElMessage.error(e.message || '创建失败')
  }
}

function openEditAccount(row) {
  editForm.value = {
    id: row.id,
    display_name: row.display_name || '',
    auth_type: row.auth_type || 'manual',
    webhook_url: '',
    method: 'POST',
    secret: '',
    headers_json: '',
    clear_credentials: false,
    status: row.status || 'active',
  }
  editAccOpen.value = true
}

async function saveEditAccount() {
  if (!editForm.value.display_name.trim()) {
    ElMessage.warning('显示名不能为空')
    return
  }
  try {
    const body = {
      display_name: editForm.value.display_name.trim(),
      auth_type: editForm.value.auth_type,
      status: editForm.value.status,
    }
    if (editForm.value.clear_credentials) {
      body.clear_credentials = true
    } else if (
      editForm.value.auth_type === 'webhook' &&
      editForm.value.webhook_url.trim()
    ) {
      body.credentials = buildWebhookCredentials(editForm.value)
    }
    await patchGeoChannelAccount(tenantId.value, editForm.value.id, body)
    ElMessage.success('账号已更新')
    editAccOpen.value = false
    await load()
  } catch (e) {
    ElMessage.error(e.message || '更新失败')
  }
}

async function disableAccount(row) {
  try {
    await patchGeoChannelAccount(tenantId.value, row.id, { status: 'disabled' })
    ElMessage.success('账号已禁用')
    await load()
  } catch (e) {
    ElMessage.error(e.message || '禁用失败')
  }
}

async function enableAccount(row) {
  try {
    await patchGeoChannelAccount(tenantId.value, row.id, { status: 'active' })
    ElMessage.success('账号已启用')
    await load()
  } catch (e) {
    ElMessage.error(e.message || '启用失败')
  }
}

async function removeAccount(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除账号「${row.display_name}」(账号 ID ${row.id})？`,
      '删除渠道账号',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteGeoChannelAccount(tenantId.value, row.id, true)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(e.message || '删除失败')
  }
}

function channelName(id) {
  const c = channelById(id)
  return c ? `${c.name || c.channel_type}` : `渠道#${id}`
}

function statusLabel(s) {
  const map = {
    active: '有效',
    unconfigured: '未配置',
    expired: '过期',
    disabled: '已禁用',
  }
  return map[s] || s || '—'
}

/** 当前页签：自动化配置就绪状态 */
const autoSetupStatus = computed(() => {
  const ch = activeChannel.value
  if (!ch || !isAutoPublish(ch)) return null
  const accs = (accounts.value || []).filter(
    (a) => a.channel_id === ch.id && a.status === 'active' && a.auth_type === 'webhook' && a.has_credentials,
  )
  return {
    channel: ch,
    ready: accs.length > 0 && ch.enabled,
    accountCount: accs.length,
    missing: [
      !ch.enabled && '渠道未启用',
      ch.publish_mode !== 'auto_publish' && '发布模式不是 auto_publish',
      accs.length === 0 && '缺少有效 Webhook 账号',
    ].filter(Boolean),
  }
})

watch(tenantId, load)
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="geo-page">
    <div class="page-header">
      <div>
        <div class="page-title">发布渠道</div>
        <div class="page-desc">
          <strong>可自动推送</strong>：发布模式 = <code>auto_publish</code> 的官网/文档 + Webhook 账号（HTTPS）。
          微信/知乎等仅支持出稿后<strong>人工发 + 回填 URL</strong>（无官方 OAuth 自动化）。
        </div>
      </div>
      <div class="header-actions">
        <el-button @click="createChOpen = true">新建渠道</el-button>
        <el-button type="primary" @click="openCreateAccount()">新建账号</el-button>
        <el-button @click="load">刷新</el-button>
        <router-link class="el-button" to="/geo/workbench">工作台</router-link>
      </div>
    </div>

    <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

    <!-- 多媒自动推送矩阵 -->
    <section v-if="autoMatrix" class="block auto-overview">
      <div class="block-head">
        <h3 class="sec">多媒自动推送矩阵</h3>
        <span class="sec-hint">
          就绪 {{ autoMatrix.ready_count }}/{{ autoMatrix.total_auto_types }} · 只差配置凭证即可推
        </span>
        <el-button
          size="small"
          type="primary"
          plain
          :loading="enablingPack"
          style="margin-left: auto"
          @click="enableMediaPack"
        >
          一键开启多媒 auto 包
        </el-button>
      </div>
      <el-table :data="autoMatrix.items || []" size="small" class="mb" empty-text="无自动推送渠道">
        <el-table-column prop="name" label="渠道" min-width="120" />
        <el-table-column prop="channel_type" label="类型" width="100" />
        <el-table-column prop="publish_mode" label="模式" width="120" />
        <el-table-column label="凭证" width="100">
          <template #default="{ row }">
            {{ row.ready_accounts }}/{{ row.account_count }}
          </template>
        </el-table-column>
        <el-table-column label="配置就绪" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.config_ready ? 'success' : 'warning'">
              {{ row.config_ready ? '就绪' : '待配置' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="缺什么" min-width="200">
          <template #default="{ row }">
            <span v-if="row.config_ready" class="muted">填 token 即可推送</span>
            <span v-else>{{ (row.tips || []).join('；') }}</span>
          </template>
        </el-table-column>
        <el-table-column label="凭证字段" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.credential_schema?.auth_type }}:
            {{ (row.credential_schema?.fields || []).join(', ') }}
          </template>
        </el-table-column>
      </el-table>
      <p class="hint">{{ autoMatrix.hint }}</p>
    </section>

    <!-- 自动化渠道总览 -->
    <section class="block auto-overview">
      <div class="block-head">
        <h3 class="sec">官网 Webhook 卡片</h3>
        <span class="sec-hint">
          website/docs → Webhook；wechat/zhihu/百家号/头条 → social_api 直发（auto_publish）
        </span>
      </div>
      <div class="auto-cards">
        <div
          v-for="c in channels.filter((x) => typeSupportsWebhook(x.channel_type))"
          :key="c.id"
          class="auto-card"
          :class="{ ready: isAutoPublish(c) && c.enabled && accounts.some((a) => a.channel_id === c.id && a.auth_type === 'webhook' && a.has_credentials && a.status === 'active') }"
        >
          <div class="auto-card-title">
            {{ c.name }}
            <el-tag size="small" :type="modeTagType(c.publish_mode)">{{ modeLabel(c.publish_mode) }}</el-tag>
          </div>
          <div class="auto-card-meta">
            渠道 ID {{ c.id }} · {{ c.channel_type }}
            <template v-if="c.base_url"> · 站点 {{ c.base_url }}</template>
          </div>
          <div class="auto-card-status">
            <template
              v-if="
                isAutoPublish(c) &&
                c.enabled &&
                accounts.some(
                  (a) =>
                    a.channel_id === c.id &&
                    a.auth_type === 'webhook' &&
                    a.has_credentials &&
                    a.status === 'active',
                )
              "
            >
              <el-tag type="success" size="small">Webhook 已就绪</el-tag>
              可在任务编辑器选此账号「Webhook 推送」
            </template>
            <template v-else>
              <el-tag type="warning" size="small">待配置</el-tag>
              <el-button link type="primary" @click="openEditChannel(c)">设为 auto_publish</el-button>
              <el-button link type="primary" @click="openCreateAccount(c.id)">配置 Webhook</el-button>
            </template>
          </div>
        </div>
        <div v-if="!channels.some((x) => typeSupportsWebhook(x.channel_type))" class="hint">
          暂无官网/文档渠道，请先新建。
        </div>
      </div>
    </section>

    <!-- ① 渠道目录 -->
    <section class="block">
      <div class="block-head">
        <h3 class="sec">① 渠道目录</h3>
        <span class="sec-hint">主键：<code>渠道 ID</code> · 点「配置」可改发布模式 / 站点 URL</span>
      </div>
      <el-table :data="channels" stripe empty-text="暂无渠道" class="mb" size="small">
        <el-table-column prop="id" label="渠道 ID" width="88" />
        <el-table-column prop="channel_type" label="类型" width="120" show-overflow-tooltip />
        <el-table-column prop="name" label="名称" min-width="140" show-overflow-tooltip />
        <el-table-column label="发布模式" min-width="160">
          <template #default="{ row }">
            <el-tag size="small" :type="modeTagType(row.publish_mode)">
              {{ modeLabel(row.publish_mode) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="站点 base_url" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ row.base_url || '—' }}</template>
        </el-table-column>
        <el-table-column label="启用" width="72" align="center">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
              {{ row.enabled ? '是' : '否' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="账号数" width="72" align="center">
          <template #default="{ row }">
            {{ accounts.filter((a) => a.channel_id === row.id).length }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEditChannel(row)">配置</el-button>
            <el-button link type="primary" @click="toggleChannel(row)">
              {{ row.enabled ? '禁用' : '启用' }}
            </el-button>
            <el-button link type="danger" @click="removeChannel(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <!-- ② 渠道账号 -->
    <section class="block">
      <div class="block-head">
        <h3 class="sec">② 渠道账号</h3>
        <span class="sec-hint">主键：<code>账号 ID</code> · 按渠道页签管理；auto 渠道请配 Webhook</span>
      </div>

      <el-tabs v-model="activeTab" type="card" class="acc-tabs">
        <el-tab-pane
          v-for="t in channelTabs"
          :key="t.key"
          :name="t.key"
        >
          <template #label>
            <span>
              {{ t.key === 'all' ? '全部' : t.label }}
              <span class="tab-count">({{ t.count }})</span>
              <el-tag
                v-if="t.auto && t.key !== 'all'"
                size="small"
                :type="t.webhookReady ? 'success' : 'warning'"
                class="tab-tag"
              >
                {{ t.webhookReady ? '自动就绪' : '待配 Webhook' }}
              </el-tag>
            </span>
          </template>
        </el-tab-pane>
      </el-tabs>

      <!-- 当前页签自动化指引 -->
      <el-alert
        v-if="autoSetupStatus"
        class="mb"
        :type="autoSetupStatus.ready ? 'success' : 'warning'"
        :closable="false"
        show-icon
      >
        <template #title>
          <span v-if="autoSetupStatus.ready">
            「{{ autoSetupStatus.channel.name }}」自动化已就绪（{{ autoSetupStatus.accountCount }} 个 Webhook 账号）
          </span>
          <span v-else>
            「{{ autoSetupStatus.channel.name }}」自动化未就绪：{{ autoSetupStatus.missing.join('；') }}
          </span>
        </template>
        <div v-if="!autoSetupStatus.ready" class="alert-actions">
          <el-button size="small" type="primary" @click="openEditChannel(autoSetupStatus.channel)">
            配置发布模式
          </el-button>
          <el-button size="small" type="primary" @click="openCreateAccount(autoSetupStatus.channel.id)">
            配置 Webhook 账号
          </el-button>
        </div>
        <div v-else class="hint">
          用法：优化文章 → 生成渠道稿 → 导出 → 审校通过 → 选本账号「Webhook 推送」
        </div>
      </el-alert>

      <el-alert
        v-else-if="activeChannel && !isAutoPublish(activeChannel)"
        class="mb"
        type="info"
        :closable="false"
        show-icon
        :title="`「${activeChannel.name}」为人工渠道：可建 manual 账号作登记；发完后在任务里回填 URL。官方 OAuth 自动发属二期。`"
      />

      <div class="tab-actions">
        <el-button
          type="primary"
          size="small"
          @click="openCreateAccount(activeTab === 'all' ? null : Number(activeTab))"
        >
          {{
            activeChannel && isAutoPublish(activeChannel)
              ? '配置 Webhook 自动化账号'
              : '在当前渠道新建账号'
          }}
        </el-button>
      </div>

      <el-table :data="filteredAccounts" stripe empty-text="该渠道下暂无账号" size="small">
        <el-table-column prop="id" label="账号 ID" width="88" />
        <el-table-column label="所属渠道" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">
            {{ channelName(row.channel_id) }}
            <span class="muted">（渠道 ID {{ row.channel_id }}）</span>
          </template>
        </el-table-column>
        <el-table-column prop="display_name" label="显示名" min-width="150" show-overflow-tooltip />
        <el-table-column prop="auth_type" label="鉴权" width="100" />
        <el-table-column label="提供商" width="100">
          <template #default="{ row }">{{ row.provider || '—' }}</template>
        </el-table-column>
        <el-table-column label="Token" min-width="120">
          <template #default="{ row }">
            <el-tag v-if="row.token_expired" size="small" type="danger">已过期</el-tag>
            <el-tag v-else-if="row.token_expiring_soon" size="small" type="warning">将过期</el-tag>
            <el-tag v-else-if="row.oauth_authorized" size="small" type="success">有效</el-tag>
            <span v-else class="muted">—</span>
            <div v-if="row.token_expires_at" class="muted">{{ row.token_expires_at }}</div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag
              size="small"
              :type="
                row.status === 'active'
                  ? 'success'
                  : row.status === 'disabled'
                    ? 'info'
                    : 'warning'
              "
            >
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="凭证" width="72" align="center">
          <template #default="{ row }">
            {{ row.has_credentials ? '已配' : '无' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="320" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEditAccount(row)">编辑</el-button>
            <el-button
              v-if="row.auth_type === 'oauth2' || row.provider === 'oauth2'"
              link
              type="primary"
              @click="goOAuth(row)"
            >去授权</el-button>
            <el-button
              v-if="row.auth_type === 'oauth2' || row.provider === 'oauth2'"
              link
              @click="doRefreshOAuth(row)"
            >刷新Token</el-button>
            <el-button
              v-if="row.auth_type === 'social_api' || row.auth_type === 'oauth2'"
              link
              type="success"
              @click="doVerifySocial(row)"
            >校验</el-button>
            <el-button
              v-if="row.status === 'disabled'"
              link
              type="success"
              @click="enableAccount(row)"
            >
              启用
            </el-button>
            <el-button v-else link type="warning" @click="disableAccount(row)">禁用</el-button>
            <el-button link type="danger" @click="removeAccount(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <!-- 新建渠道 -->
    <el-dialog v-model="createChOpen" title="新建发布渠道" width="480px">
      <el-form label-width="100px">
        <el-form-item label="类型">
          <el-select
            v-model="chForm.channel_type"
            style="width: 100%"
            @change="onCreateChTypeChange"
          >
            <el-option
              v-for="t in CHANNEL_TYPES"
              :key="t.value"
              :label="t.label"
              :value="t.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="chForm.name" placeholder="可选" />
        </el-form-item>
        <el-form-item label="发布模式">
          <el-select v-model="chForm.publish_mode" style="width: 100%">
            <el-option
              v-for="m in PUBLISH_MODES"
              :key="m.value"
              :label="m.label"
              :value="m.value"
            />
          </el-select>
          <div class="form-tip">
            {{ PUBLISH_MODES.find((m) => m.value === chForm.publish_mode)?.tip }}
          </div>
        </el-form-item>
        <el-form-item v-if="typeSupportsWebhook(chForm.channel_type)" label="站点 URL">
          <el-input v-model="chForm.base_url" placeholder="https://www.example.com（可选）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createChOpen = false">取消</el-button>
        <el-button type="primary" @click="createChannel">创建</el-button>
      </template>
    </el-dialog>

    <!-- 配置渠道（自动化关键） -->
    <el-dialog v-model="editChOpen" title="配置渠道 · 发布模式" width="500px">
      <el-form label-width="110px">
        <el-form-item label="渠道 ID">
          <span>{{ editChForm.id }}</span>
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="editChForm.name" />
        </el-form-item>
        <el-form-item label="发布模式" required>
          <el-select v-model="editChForm.publish_mode" style="width: 100%">
            <el-option
              v-for="m in PUBLISH_MODES"
              :key="m.value"
              :label="m.label"
              :value="m.value"
            />
          </el-select>
          <div class="form-tip">
            要自动推送请选 <strong>auto_publish</strong>，再为该渠道创建 Webhook 账号。
          </div>
        </el-form-item>
        <el-form-item label="站点 base_url">
          <el-input v-model="editChForm.base_url" placeholder="https://… 可选，便于对照" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="editChForm.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editChOpen = false">取消</el-button>
        <el-button type="primary" @click="saveEditChannel">保存配置</el-button>
      </template>
    </el-dialog>

    <!-- 新建账号（自动化表单） -->
    <el-dialog
      v-model="createAccOpen"
      :title="
        accForm.auth_type === 'webhook'
          ? '配置 Webhook 账号'
          : accForm.auth_type === 'social_api'
            ? '配置社交直发账号'
            : '新建渠道账号（人工）'
      "
      width="540px"
    >
      <el-form label-width="120px">
        <el-form-item label="所属渠道" required>
          <el-select
            v-model="accForm.channel_id"
            style="width: 100%"
            @change="onAccChannelChange"
          >
            <el-option
              v-for="c in channels"
              :key="c.id"
              :label="`${c.name} · ${modeLabel(c.publish_mode)} · 渠道 ID ${c.id}`"
              :value="c.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="显示名" required>
          <el-input v-model="accForm.display_name" placeholder="如：官网 CMS 生产 Webhook" />
        </el-form-item>
        <el-form-item label="鉴权类型">
          <el-select v-model="accForm.auth_type" style="width: 100%">
            <el-option label="webhook · 官网/文档" value="webhook" />
            <el-option label="social_api · 社交直发" value="social_api" />
            <el-option label="manual · 人工回填" value="manual" />
          </el-select>
        </el-form-item>

        <template v-if="accForm.auth_type === 'webhook'">
          <el-divider content-position="left">自动化 Webhook 参数</el-divider>
          <el-form-item label="Webhook URL" required>
            <el-input
              v-model="accForm.webhook_url"
              placeholder="https://cms.example.com/hooks/geo-publish"
            />
            <div class="form-tip">必须公网 HTTPS；推送时 POST JSON 渠道稿</div>
          </el-form-item>
          <el-form-item label="HTTP 方法">
            <el-select v-model="accForm.method" style="width: 100%">
              <el-option label="POST" value="POST" />
              <el-option label="PUT" value="PUT" />
              <el-option label="PATCH" value="PATCH" />
            </el-select>
          </el-form-item>
          <el-form-item label="签名 secret">
            <el-input
              v-model="accForm.secret"
              type="password"
              show-password
              placeholder="可选；有则带 X-GEO-Signature"
            />
          </el-form-item>
          <el-form-item label="Headers JSON">
            <el-input
              v-model="accForm.headers_json"
              type="textarea"
              :rows="2"
              placeholder='可选，如 {"Authorization":"Bearer xxx"}'
            />
          </el-form-item>
        </template>
        <template v-else-if="accForm.auth_type === 'social_api' || accForm.auth_type === 'oauth2'">
          <el-divider content-position="left">社交真发布</el-divider>
          <el-form-item label="提供商" required>
            <el-select v-model="accForm.provider" style="width: 100%">
              <el-option label="wechat_mp · 微信公众号原生（app_id/secret）" value="wechat_mp" />
              <el-option label="oauth2 · 授权码 + 刷新 token" value="oauth2" />
              <el-option label="gateway · 自建转发（api_url + token）" value="gateway" />
            </el-select>
          </el-form-item>
          <el-form-item label="平台" required>
            <el-select v-model="accForm.platform" style="width: 100%">
              <el-option label="wechat 公众号" value="wechat" />
              <el-option label="zhihu 知乎" value="zhihu" />
              <el-option label="baijiahao 百家号" value="baijiahao" />
              <el-option label="toutiao 头条" value="toutiao" />
            </el-select>
          </el-form-item>

          <template v-if="accForm.provider === 'wechat_mp'">
            <el-alert
              class="mb"
              type="success"
              :closable="false"
              show-icon
              title="微信公众号：用 app_id + app_secret 自动取 token，调用 draft/add（真开放平台接口）。本地可填 mock_ 前缀做演练。"
            />
            <el-form-item label="app_id" required>
              <el-input v-model="accForm.app_id" placeholder="wx… 或 mock_wx_demo" />
            </el-form-item>
            <el-form-item label="app_secret" required>
              <el-input v-model="accForm.app_secret" type="password" show-password />
            </el-form-item>
          </template>

          <template v-else-if="accForm.provider === 'oauth2'">
            <el-alert
              class="mb"
              type="info"
              :closable="false"
              show-icon
              title="创建后点账号列表「去授权」；回调地址须配置到平台控制台，并指向本 API 的 /api/v1/geo/oauth/social/callback"
            />
            <el-form-item label="client_id" required>
              <el-input v-model="accForm.client_id" />
            </el-form-item>
            <el-form-item label="client_secret" required>
              <el-input v-model="accForm.client_secret" type="password" show-password />
            </el-form-item>
            <el-form-item label="authorize_url" required>
              <el-input v-model="accForm.authorize_url" placeholder="https://…/oauth/authorize" />
            </el-form-item>
            <el-form-item label="token_url" required>
              <el-input v-model="accForm.token_url" placeholder="https://…/oauth/token" />
            </el-form-item>
            <el-form-item label="redirect_uri" required>
              <el-input
                v-model="accForm.redirect_uri"
                placeholder="https://your-api/api/v1/geo/oauth/social/callback"
              />
            </el-form-item>
            <el-form-item label="api_url" required>
              <el-input v-model="accForm.api_url" placeholder="授权后发布接口 HTTPS" />
            </el-form-item>
            <el-form-item label="scope">
              <el-input v-model="accForm.scope" placeholder="可选" />
            </el-form-item>
          </template>

          <template v-else>
            <el-form-item label="api_url" required>
              <el-input v-model="accForm.api_url" placeholder="https://…/publish" />
            </el-form-item>
            <el-form-item label="access_token" required>
              <el-input v-model="accForm.access_token" type="password" show-password />
            </el-form-item>
            <el-form-item label="HTTP 方法">
              <el-select v-model="accForm.method" style="width: 100%">
                <el-option label="POST" value="POST" />
                <el-option label="PUT" value="PUT" />
              </el-select>
            </el-form-item>
            <el-form-item label="Headers JSON">
              <el-input v-model="accForm.headers_json" type="textarea" :rows="2" />
            </el-form-item>
          </template>
        </template>
        <el-alert
          v-else
          type="info"
          :closable="false"
          show-icon
          title="人工账号：仅登记用途；在任务编辑器发完后「回填 URL」"
        />
      </el-form>
      <template #footer>
        <el-button @click="createAccOpen = false">取消</el-button>
        <el-button type="primary" @click="createAccount">创建</el-button>
      </template>
    </el-dialog>

    <!-- 编辑账号 -->
    <el-dialog v-model="editAccOpen" title="编辑渠道账号" width="540px">
      <el-form label-width="120px">
        <el-form-item label="账号 ID">
          <span>{{ editForm.id }}</span>
        </el-form-item>
        <el-form-item label="显示名" required>
          <el-input v-model="editForm.display_name" />
        </el-form-item>
        <el-form-item label="鉴权类型">
          <el-select v-model="editForm.auth_type" style="width: 100%">
            <el-option label="webhook" value="webhook" />
            <el-option label="manual" value="manual" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="editForm.status" style="width: 100%">
            <el-option label="有效 active" value="active" />
            <el-option label="未配置 unconfigured" value="unconfigured" />
            <el-option label="已禁用 disabled" value="disabled" />
          </el-select>
        </el-form-item>
        <template v-if="editForm.auth_type === 'webhook'">
          <el-divider content-position="left">更新 Webhook（留空不改）</el-divider>
          <el-form-item label="新 Webhook URL">
            <el-input v-model="editForm.webhook_url" placeholder="https://…" />
          </el-form-item>
          <el-form-item label="方法">
            <el-select v-model="editForm.method" style="width: 100%">
              <el-option label="POST" value="POST" />
              <el-option label="PUT" value="PUT" />
              <el-option label="PATCH" value="PATCH" />
            </el-select>
          </el-form-item>
          <el-form-item label="secret">
            <el-input v-model="editForm.secret" type="password" show-password />
          </el-form-item>
          <el-form-item label="Headers JSON">
            <el-input v-model="editForm.headers_json" type="textarea" :rows="2" />
          </el-form-item>
          <el-form-item label="清除凭证">
            <el-checkbox v-model="editForm.clear_credentials">清空已存 Webhook</el-checkbox>
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="editAccOpen = false">取消</el-button>
        <el-button type="primary" @click="saveEditAccount">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.geo-page { padding: 4px 2px 28px; }
.page-header {
  display: flex; justify-content: space-between; gap: 12px; margin-bottom: 14px; flex-wrap: wrap;
}
.page-title { font-size: 20px; font-weight: 700; color: #1e2330; }
.page-desc { font-size: 13px; color: #6b7280; margin-top: 4px; max-width: 720px; line-height: 1.55; }
.page-desc code { background: #f5f0ff; padding: 1px 6px; border-radius: 4px; color: #6d28d9; }
.header-actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.mb { margin-bottom: 14px; }
.block {
  background: #fff;
  border: 1px solid #e8e4f5;
  border-radius: 12px;
  padding: 14px 16px 18px;
  margin-bottom: 16px;
}
.block-head {
  display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; margin-bottom: 10px;
}
.sec { font-size: 15px; font-weight: 700; margin: 0; color: #374151; }
.sec-hint { font-size: 12px; color: #9ca3af; }
.sec-hint code {
  background: #f5f0ff; padding: 1px 6px; border-radius: 4px; color: #6d28d9;
}
.auto-overview { border-color: #c4b5fd; background: linear-gradient(180deg, #faf8ff 0%, #fff 40%); }
.auto-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 10px;
}
.auto-card {
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 12px 14px;
  background: #fff;
}
.auto-card.ready { border-color: #86efac; background: #f0fdf4; }
.auto-card-title {
  font-weight: 700; color: #1f2937; display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
}
.auto-card-meta { font-size: 12px; color: #6b7280; margin: 6px 0 8px; }
.auto-card-status { font-size: 12px; color: #374151; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.acc-tabs { margin-bottom: 8px; }
.tab-count { color: #9ca3af; font-size: 12px; }
.tab-tag { margin-left: 6px; vertical-align: middle; }
.tab-actions { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; flex-wrap: wrap; }
.hint { font-size: 12px; color: #6b7280; }
.muted { font-size: 12px; color: #9ca3af; margin-left: 4px; }
.form-tip { font-size: 12px; color: #9ca3af; margin-top: 4px; line-height: 1.4; }
.alert-actions { margin-top: 8px; display: flex; gap: 8px; flex-wrap: wrap; }
</style>
