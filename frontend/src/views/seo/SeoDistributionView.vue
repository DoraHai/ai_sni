<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  completeSeoManualPublication,
  createSeoDistributionConnection,
  createSeoManualPublication,
  downloadSeoPublishedLinksTemplate,
  fetchSeoContentAssets,
  fetchSeoContentPublications,
  fetchSeoDistributionCatalog,
  fetchSeoDistributionConnections,
  fetchSeoPublicationAttempts,
  importSeoPublishedLinks,
  preflightSeoDistribution,
  publishSeoDistribution,
  retrySeoContentPublication,
  syncSeoContentPublication,
  testSeoDistributionConnection,
  updateSeoDistributionConnection,
} from '../../api/seo'
import { fetchSeoSites } from '../../api/moduleAssets'
import { currentTenantId, session } from '../../store/session'

const loading = ref(false)
const error = ref('')
const activeTab = ref('channels')
const query = ref('')
const channelFilter = ref('all')
const catalog = ref([])
const connections = ref([])
const contents = ref([])
const publications = ref([])
const sites = ref([])
const siteId = ref(null)
const canEdit = computed(() => !session.isLoggedIn || session.canEdit('seo.content'))

const importInput = ref(null)
const importDialog = ref(false)
const importing = ref(false)
const importFile = ref(null)
const importResult = ref(null)

const connectionDialog = ref(false)
const connectionSaving = ref(false)
const connectionEditingId = ref(null)
const connectionCredentialsChanged = ref(false)
const connectionTestingId = ref(null)
const connectionTogglingId = ref(null)
const connectionForm = reactive({ platform_code: '', name: '', base_url: '', credentials: {}, clear_credentials: false, enabled: true, test_after_save: true })
const selectedPlatform = computed(() => catalog.value.find(item => item.code === connectionForm.platform_code))
const editingConnection = computed(() => connections.value.find(item => item.id === connectionEditingId.value))

const manualDialog = ref(false)
const manualSaving = ref(false)
const manualForm = reactive({ content_id: null, platform_name: '', page_url: '' })

const batchDialog = ref(false)
const batchStep = ref(0)
const batchChecking = ref(false)
const batchRunning = ref(false)
const batchProgress = ref(0)
const batchCurrent = ref('')
const batchResults = ref([])
const batchPreview = ref(null)
const batchForm = reactive({ content_ids: [], connection_ids: [], action: 'draft' })

const completeDialog = ref(false)
const completeSaving = ref(false)
const completeForm = reactive({ publication_id: null, page_url: '', confirmed: false })
const handoffItem = ref(null)
const handoffOpened = ref(false)
const handoffCopied = reactive({ title: false, content: false })
const syncingId = ref(null)
const retryingId = ref(null)
const taskStatus = ref('all')
const attemptsDialog = ref(false)
const attemptsLoading = ref(false)
const attemptPublication = ref(null)
const attempts = ref([])

const handoffTitle = computed(() => handoffItem.value?.adapted_title || handoffItem.value?.content_title || '')
const handoffHtml = computed(() => handoffItem.value?.adapted_content || '')
const handoffPlain = computed(() => {
  const source = handoffHtml.value
  if (!source) return ''
  if (!/<[a-z][\s\S]*>/i.test(source)) return source
  const document = new DOMParser().parseFromString(source, 'text/html')
  document.body.querySelectorAll('br').forEach(node => node.replaceWith('\n'))
  document.body.querySelectorAll('p,h1,h2,h3,h4,h5,h6,li,blockquote').forEach(node => node.append('\n'))
  return (document.body.textContent || '').replace(/\n{3,}/g, '\n\n').trim()
})

const statusMeta = {
  pending: ['待处理', 'warning'],
  preparing: ['准备中', 'warning'],
  publishing: ['发布中', 'warning'],
  draft_created: ['草稿已创建', 'primary'],
  manual_required: ['待人工确认', 'warning'],
  published: ['已发布', 'success'],
  failed: ['失败', 'danger'],
  cancelled: ['已取消', 'info'],
}
const modeName = value => ({ api: 'API 直连', assisted: '辅助发布', share: '分享发布', oauth: 'OAuth', draft: '创建草稿', publish: '正式发布', manual: '人工登记' })[value] || '人工登记'
const statusName = value => statusMeta[value]?.[0] || value
const statusType = value => statusMeta[value]?.[1] || 'info'
const date = value => value ? new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '尚未执行'

const published = computed(() => publications.value.filter(item => item.status === 'published'))
const activeTasks = computed(() => publications.value.filter(item => item.status !== 'published'))
const filteredActiveTasks = computed(() => taskStatus.value === 'all' ? activeTasks.value : activeTasks.value.filter(item => item.status === taskStatus.value))
const publishedContentCount = computed(() => new Set(published.value.map(item => item.content_id)).size)
const coverage = computed(() => contents.value.length ? Math.round(publishedContentCount.value / contents.value.length * 100) : 0)
const connectedCount = computed(() => connections.value.filter(item => item.enabled && ['connected', 'ready'].includes(item.status)).length)
const selectableConnections = computed(() => connections.value.filter(item => item.enabled && (item.mode === 'assisted' || item.status === 'connected')))
const pendingContents = computed(() => contents.value.filter(item => !published.value.some(record => record.content_id === item.id)))
const batchFailedCount = computed(() => batchResults.value.filter(item => !item.ok).length)

const channelCards = computed(() => catalog.value.map(platform => {
  const platformConnections = connections.value.filter(item => item.platform_code === platform.code)
  const connectionIds = new Set(platformConnections.map(item => item.id))
  const records = publications.value.filter(item => item.platform_code === platform.code || connectionIds.has(item.connection_id))
  return { ...platform, connections: platformConnections, records, published: records.filter(item => item.status === 'published').length }
}))
const visibleChannels = computed(() => channelCards.value.filter(item => {
  const keyword = query.value.trim().toLowerCase()
  const matchesText = !keyword || item.name.toLowerCase().includes(keyword) || item.connections.some(connection => connection.name.toLowerCase().includes(keyword))
  const matchesFilter = channelFilter.value === 'all'
    || (channelFilter.value === 'connected' && item.connections.length)
    || (channelFilter.value === 'available' && item.available && !item.connections.length)
    || (channelFilter.value === 'planned' && !item.available)
  return matchesText && matchesFilter
}))

async function load() {
  if (!currentTenantId.value) {
    error.value = '请先选择客户'
    return
  }
  if (!siteId.value) {
    error.value = '请先选择或创建 SEO 网站'
    contents.value = []
    publications.value = []
    return
  }
  loading.value = true
  try {
    const [catalogResult, connectionResult, contentResult, publicationResult] = await Promise.all([
      fetchSeoDistributionCatalog(),
      fetchSeoDistributionConnections({ tenantId: currentTenantId.value }),
      fetchSeoContentAssets({ tenantId: currentTenantId.value, siteId: siteId.value }),
      fetchSeoContentPublications({ tenantId: currentTenantId.value, siteId: siteId.value }),
    ])
    catalog.value = catalogResult.items || []
    connections.value = connectionResult.items || []
    contents.value = contentResult.items || []
    const contentIds = new Set(contents.value.map(item => item.id))
    publications.value = (publicationResult.items || []).filter(item => contentIds.has(item.content_id))
    error.value = ''
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function loadSites() {
  if (!currentTenantId.value) {
    sites.value = []
    siteId.value = null
    return load()
  }
  try {
    sites.value = (await fetchSeoSites(currentTenantId.value)).sites || []
    const selected = sites.value.some(item => item.id === siteId.value)
      ? siteId.value
      : (sites.value.find(item => item.status === 'active')?.id || sites.value[0]?.id || null)
    if (selected !== siteId.value) siteId.value = selected
    else await load()
  } catch (e) {
    error.value = e.message
  }
}

function openConnection(platform) {
  if (!platform.available) return ElMessage.info(platform.help || '该平台仍在规划中')
  Object.assign(connectionForm, {
    platform_code: platform.code,
    name: platform.name,
    base_url: '',
    credentials: Object.fromEntries((platform.credential_fields || []).map(item => [item.key, ''])),
    clear_credentials: false,
    enabled: true,
    test_after_save: platform.mode === 'api',
  })
  connectionEditingId.value = null
  connectionCredentialsChanged.value = false
  connectionDialog.value = true
}

function editConnection(connection) {
  const platform = catalog.value.find(item => item.code === connection.platform_code)
  if (!platform) return ElMessage.error('平台定义不存在，请刷新后重试')
  Object.assign(connectionForm, {
    platform_code: connection.platform_code,
    name: connection.name,
    base_url: connection.base_url || '',
    credentials: Object.fromEntries((platform.credential_fields || []).map(item => [item.key, ''])),
    clear_credentials: false,
    enabled: connection.enabled,
    test_after_save: false,
  })
  connectionEditingId.value = connection.id
  connectionCredentialsChanged.value = false
  connectionDialog.value = true
}

function markCredentialsChanged() {
  connectionCredentialsChanged.value = true
  connectionForm.clear_credentials = false
}

function markCredentialsCleared(value) {
  if (value) connectionCredentialsChanged.value = false
}

async function saveConnection() {
  if (!connectionForm.name.trim()) return ElMessage.warning('请填写连接名称')
  if (selectedPlatform.value?.mode === 'api' && selectedPlatform.value?.base_url_required !== false && !connectionForm.base_url.trim()) return ElMessage.warning('请填写平台站点地址')
  const requiredCredentials = selectedPlatform.value?.credential_fields || []
  if ((!connectionEditingId.value || connectionCredentialsChanged.value) && requiredCredentials.some(field => !String(connectionForm.credentials[field.key] || '').trim())) return ElMessage.warning('请完整填写平台授权信息')
  if (connectionForm.clear_credentials && connectionForm.test_after_save) return ElMessage.warning('清除授权信息后无法立即测试连接')
  connectionSaving.value = true
  try {
    let saved
    if (connectionEditingId.value) {
      const payload = {
        name: connectionForm.name.trim(),
        base_url: connectionForm.base_url.trim() || null,
        enabled: connectionForm.enabled,
        clear_credentials: connectionForm.clear_credentials,
      }
      if (connectionCredentialsChanged.value && !connectionForm.clear_credentials) payload.credentials = connectionForm.credentials
      saved = await updateSeoDistributionConnection({ connectionId: connectionEditingId.value, tenantId: currentTenantId.value, payload })
    } else {
      saved = await createSeoDistributionConnection({
        tenant_id: currentTenantId.value,
        platform_code: connectionForm.platform_code,
        name: connectionForm.name.trim(),
        base_url: connectionForm.base_url.trim() || null,
        credentials: connectionForm.credentials,
        enabled: connectionForm.enabled,
      })
    }
    connectionDialog.value = false
    if (connectionForm.test_after_save && selectedPlatform.value?.mode === 'api') {
      await testConnection(saved, { quietSuccess: false })
      return
    }
    ElMessage.success(selectedPlatform.value?.mode === 'assisted' ? '辅助发布渠道已保存' : '平台连接已保存')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    connectionSaving.value = false
  }
}

async function testConnection(connection, options = {}) {
  connectionTestingId.value = connection.id
  try {
    const result = await testSeoDistributionConnection({ connectionId: connection.id, tenantId: currentTenantId.value })
    if (!options.quietSuccess) ElMessage.success(result.message || '连接测试通过')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    connectionTestingId.value = null
    await load()
  }
}

async function toggleConnection(connection, enabled) {
  connectionTogglingId.value = connection.id
  try {
    await updateSeoDistributionConnection({ connectionId: connection.id, tenantId: currentTenantId.value, payload: { enabled } })
    ElMessage.success(enabled ? '平台连接已启用' : '平台连接已停用')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    connectionTogglingId.value = null
  }
}

function openManual(item = null) {
  Object.assign(manualForm, { content_id: item?.id || null, platform_name: '', page_url: '' })
  manualDialog.value = true
}

async function saveManual() {
  if (!manualForm.content_id) return ElMessage.warning('请选择内容资产')
  if (!manualForm.platform_name.trim()) return ElMessage.warning('请填写发布平台')
  if (!manualForm.page_url.trim()) return ElMessage.warning('请填写发布链接')
  manualSaving.value = true
  try {
    await createSeoManualPublication({
      tenant_id: currentTenantId.value,
      site_id: siteId.value,
      content_id: manualForm.content_id,
      platform_name: manualForm.platform_name.trim(),
      page_url: manualForm.page_url.trim(),
    })
    manualDialog.value = false
    ElMessage.success('发布记录已登记')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    manualSaving.value = false
  }
}

function openBatch(item = null) {
  Object.assign(batchForm, { content_ids: item ? [item.id] : [], connection_ids: [], action: 'draft' })
  batchPreview.value = null
  batchResults.value = []
  batchProgress.value = 0
  batchStep.value = 0
  batchDialog.value = true
}

async function runPreflight() {
  if (!batchForm.content_ids.length) return ElMessage.warning('至少选择一篇文章')
  if (!batchForm.connection_ids.length) return ElMessage.warning('至少选择一个平台连接')
  batchChecking.value = true
  try {
    batchPreview.value = await preflightSeoDistribution({
      tenant_id: currentTenantId.value,
      site_id: siteId.value,
      content_ids: batchForm.content_ids,
      connection_ids: batchForm.connection_ids,
      action: batchForm.action,
    })
    batchStep.value = 1
    if (batchPreview.value.blocked) ElMessage.warning(`${batchPreview.value.blocked} 个任务被预检拦截`)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    batchChecking.value = false
  }
}

async function executeBatch() {
  const rows = (batchPreview.value?.rows || []).filter(item => item.status === 'ready')
  if (!rows.length) return ElMessage.warning('没有可以执行的任务')
  if (batchForm.action === 'publish') {
    try {
      await ElMessageBox.confirm(`即将正式发布 ${rows.length} 个任务，内容可能立即对外公开。确认继续？`, '确认正式发布', { type: 'warning', confirmButtonText: '确认发布', cancelButtonText: '返回检查' })
    } catch { return }
  }
  batchRunning.value = true
  batchResults.value = rows.map(item => ({ ...item, run_status: 'queued', ok: null, result: null, error: '' }))
  batchStep.value = 2
  for (let index = 0; index < rows.length; index += 1) {
    const item = rows[index]
    const task = batchResults.value[index]
    task.run_status = 'running'
    batchCurrent.value = `${item.content_title} · ${item.connection_name}${item.image_count ? ` · 正在转存 ${item.image_count} 张图片` : ''}`
    try {
      const result = await publishSeoDistribution({
        tenant_id: currentTenantId.value,
        site_id: siteId.value,
        content_id: item.content_id,
        connection_id: item.connection_id,
        action: batchForm.action,
        confirm: batchForm.action === 'publish',
      })
      Object.assign(task, { ok: true, result, run_status: 'succeeded' })
    } catch (e) {
      Object.assign(task, { ok: false, error: e.message, run_status: 'failed' })
    }
    batchProgress.value = Math.round((index + 1) / rows.length * 100)
  }
  batchRunning.value = false
  batchCurrent.value = ''
  batchStep.value = 3
  const success = batchResults.value.filter(item => item.ok).length
  if (success === rows.length) ElMessage.success(`已完成 ${success}/${rows.length} 个任务`)
  else ElMessage.warning(`已完成 ${success}/${rows.length} 个任务；失败项已保留在任务中心`)
  await load()
}

async function copyHandoffTitle() {
  try {
    await navigator.clipboard.writeText(handoffTitle.value)
    handoffCopied.title = true
    ElMessage.success('标题已复制')
  } catch (e) {
    ElMessage.error('标题复制失败，请选中文本手动复制')
  }
}

async function copyHandoffContent() {
  try {
    if (window.ClipboardItem && navigator.clipboard.write && /<[a-z][\s\S]*>/i.test(handoffHtml.value)) {
      await navigator.clipboard.write([new window.ClipboardItem({
        'text/html': new Blob([handoffHtml.value], { type: 'text/html' }),
        'text/plain': new Blob([handoffPlain.value], { type: 'text/plain' }),
      })])
    } else {
      await navigator.clipboard.writeText(handoffPlain.value)
    }
    handoffCopied.content = true
    ElMessage.success('正文已复制；支持的平台会保留基础格式')
  } catch (e) {
    ElMessage.error('正文复制失败，请选中文本手动复制')
  }
}

function openHandoffEditor() {
  if (!handoffItem.value?.handoff_url) return ElMessage.warning('当前渠道未配置官方编辑器地址')
  const link = document.createElement('a')
  link.href = handoffItem.value.handoff_url
  link.target = '_blank'
  link.rel = 'noopener noreferrer'
  link.click()
  handoffOpened.value = true
}

function handoffPublication(item) {
  handoffItem.value = item
  handoffOpened.value = false
  Object.assign(handoffCopied, { title: false, content: false })
  Object.assign(completeForm, { publication_id: item.id, page_url: '', confirmed: false })
  completeDialog.value = true
}

async function syncPublication(item) {
  syncingId.value = item.id
  try {
    const result = await syncSeoContentPublication({ publicationId: item.id, tenantId: currentTenantId.value, siteId: siteId.value })
    if (result.status === 'published') ElMessage.success('平台状态已同步，文章发布成功')
    else if (result.status === 'failed') ElMessage.error(result.last_error || '平台返回发布失败')
    else ElMessage.info('平台仍在处理中，请稍后再次同步')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    syncingId.value = null
  }
}

async function showAttempts(item) {
  attemptPublication.value = item
  attempts.value = []
  attemptsDialog.value = true
  attemptsLoading.value = true
  try {
    const result = await fetchSeoPublicationAttempts({ publicationId: item.id, tenantId: currentTenantId.value, siteId: siteId.value })
    attempts.value = result.items || []
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    attemptsLoading.value = false
  }
}

async function retryPublication(item) {
  try {
    await ElMessageBox.confirm(
      '请先到平台后台确认该文章没有实际发布。重试可能再次提交相同内容，确认已经核对并继续？',
      '确认重试失败任务',
      { type: 'warning', confirmButtonText: '已核对，确认重试', cancelButtonText: '取消' },
    )
  } catch { return }
  retryingId.value = item.id
  try {
    const result = await retrySeoContentPublication({
      publicationId: item.id,
      payload: { tenant_id: currentTenantId.value, site_id: siteId.value, confirm: true },
    })
    ElMessage.success(result.status === 'published' ? '重试成功，文章已发布' : `重试已提交：${statusName(result.status)}`)
    await load()
  } catch (e) {
    ElMessage.error(e.message)
    await load()
  } finally {
    retryingId.value = null
  }
}

function openTaskCenter() {
  batchDialog.value = false
  activeTab.value = 'tasks'
  taskStatus.value = batchFailedCount.value ? 'failed' : 'all'
}

async function completeManual() {
  if (!completeForm.page_url.trim()) return ElMessage.warning('请粘贴平台发布后的完整链接')
  if (!completeForm.confirmed) return ElMessage.warning('请确认链接已经可以正常访问')
  completeSaving.value = true
  try {
    await completeSeoManualPublication({
      publicationId: completeForm.publication_id,
      payload: { tenant_id: currentTenantId.value, site_id: siteId.value, page_url: completeForm.page_url.trim() },
    })
    completeDialog.value = false
    handoffItem.value = null
    ElMessage.success('人工发布闭环已完成')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    completeSaving.value = false
  }
}

function selectImport() {
  if (!currentTenantId.value) return ElMessage.warning('请先选择客户')
  importInput.value?.click()
}

async function previewImport(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  if (!file.name.toLowerCase().endsWith('.xlsx')) return ElMessage.warning('请选择 .xlsx 格式的 Excel 文件')
  importFile.value = file
  importing.value = true
  try {
    importResult.value = await importSeoPublishedLinks({ tenantId: currentTenantId.value, file, dryRun: true })
    importDialog.value = true
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    importing.value = false
  }
}

async function commitImport() {
  if (!importFile.value || !importResult.value || importResult.value.failed) return
  importing.value = true
  try {
    const result = await importSeoPublishedLinks({ tenantId: currentTenantId.value, file: importFile.value, dryRun: false })
    if (result.committed) {
      ElMessage.success(`已批量登记 ${result.imported} 条多平台发布记录`)
      importDialog.value = false
      importFile.value = null
      await load()
    }
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    importing.value = false
  }
}

async function downloadTemplate() {
  try {
    const blob = await downloadSeoPublishedLinksTemplate()
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = 'SEO发布链接批量登记模板.xlsx'
    anchor.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    ElMessage.error(e.message)
  }
}

watch(siteId, load)
watch(currentTenantId, loadSites)
onMounted(loadSites)
</script>

<template>
  <div class="distribution-page" v-loading="loading">
    <section class="distribution-hero">
      <div>
        <span>CONTENT DISTRIBUTION</span>
        <h1>内容分发中心</h1>
        <p>连接发布平台、批量预检并追踪每篇文章在每个渠道的真实状态。</p>
      </div>
      <div class="hero-actions">
        <el-select v-model="siteId" class="distribution-site-picker" placeholder="选择 SEO 网站"><el-option v-for="site in sites" :key="site.id" :label="site.name||site.canonical_domain" :value="site.id" /></el-select>
        <input v-if="canEdit" ref="importInput" class="file-input" type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" @change="previewImport">
        <el-button v-if="canEdit" :loading="importing" @click="selectImport">Excel 批量登记</el-button>
        <el-button v-if="canEdit" @click="openManual()">登记发布链接</el-button>
        <el-button v-if="canEdit" type="primary" @click="openBatch()">批量发布</el-button>
      </div>
    </section>

    <el-alert v-if="error" :title="error" type="warning" :closable="false" show-icon />

    <section class="summary-grid">
      <article><span>平台连接</span><strong>{{ connectedCount }}</strong><small>可立即执行的渠道</small></article>
      <article><span>发布记录</span><strong>{{ published.length }}</strong><small>每个平台独立保存</small></article>
      <article><span>待处理任务</span><strong>{{ activeTasks.length }}</strong><small>失败与人工确认均可追踪</small></article>
      <article><span>内容覆盖率</span><strong>{{ coverage }}%</strong><small>{{ publishedContentCount }}/{{ contents.length }} 篇已有发布记录</small></article>
    </section>

    <nav class="view-tabs">
      <button :class="{ active: activeTab === 'channels' }" @click="activeTab = 'channels'">平台连接</button>
      <button :class="{ active: activeTab === 'tasks' }" @click="activeTab = 'tasks'">发布任务 <b v-if="activeTasks.length">{{ activeTasks.length }}</b></button>
      <button :class="{ active: activeTab === 'records' }" @click="activeTab = 'records'">发布记录</button>
    </nav>

    <template v-if="activeTab === 'channels'">
      <section class="channel-toolbar">
        <el-segmented v-model="channelFilter" :options="[{ label: '全部', value: 'all' }, { label: '已连接', value: 'connected' }, { label: '可接入', value: 'available' }, { label: '规划中', value: 'planned' }]" />
        <el-input v-model="query" clearable placeholder="搜索平台或连接名称" />
        <el-button @click="load">刷新状态</el-button>
      </section>
      <section class="channel-grid">
        <article v-for="item in visibleChannels" :key="item.code" class="channel-card" :class="{ muted: !item.available }">
          <header>
            <span class="channel-logo">{{ item.name.slice(0, 1) }}</span>
            <div><strong>{{ item.name }}</strong><small>{{ modeName(item.mode) }}</small></div>
            <el-tag :type="item.connections.length ? 'success' : item.available ? 'primary' : 'info'" effect="light">
              {{ item.connections.length ? `${item.connections.length} 个连接` : item.available ? '可接入' : '规划中' }}
            </el-tag>
          </header>
          <p>{{ item.help }}</p>
          <div class="capabilities"><span v-for="capability in item.capabilities" :key="capability">{{ ({ connection_test: '连接测试', draft: '创建草稿', publish: '正式发布', adapt: '内容适配', copy: '一键复制', open_editor: '打开编辑器', manual_confirm: '人工确认', status_link: '链接回流', async_status: '状态同步', media_upload: '图片上传' })[capability] || capability }}</span></div>
          <div v-if="item.connections.length" class="connection-list">
            <div v-for="connection in item.connections" :key="connection.id">
              <span><b>{{ connection.name }}</b><small>{{ connection.base_url || '无需站点地址' }} · {{ connection.last_tested_at ? `最近测试 ${date(connection.last_tested_at)}` : connection.mode === 'api' ? '尚未测试' : '无需测试' }}</small><small v-if="connection.last_error" class="connection-error">{{ connection.last_error }}</small></span>
              <el-tag size="small" :type="connection.status === 'failed' ? 'danger' : ['connected', 'ready'].includes(connection.status) ? 'success' : 'warning'">{{ ({ connected: '已连接', ready: '已就绪', configured: '待测试', failed: '连接失败' })[connection.status] || connection.status }}</el-tag>
              <el-button v-if="canEdit" link type="primary" @click="editConnection(connection)">编辑</el-button>
              <el-button v-if="canEdit && connection.mode === 'api'" link type="primary" :loading="connectionTestingId === connection.id" @click="testConnection(connection)">测试</el-button>
              <el-switch v-if="canEdit" :model-value="connection.enabled" :loading="connectionTogglingId === connection.id" @change="value => toggleConnection(connection, value)" />
            </div>
          </div>
          <footer>
            <span>已发布 {{ item.published }} 篇</span>
            <el-button v-if="canEdit && item.available" type="primary" plain @click="openConnection(item)">添加连接</el-button>
            <el-button v-else-if="!item.available" disabled>等待接口开放</el-button>
          </footer>
        </article>
      </section>
    </template>

    <template v-else-if="activeTab === 'tasks'">
      <section class="table-panel">
        <header><div><h2>发布任务</h2><p>API 发布、草稿创建和人工交接采用同一状态流，每次尝试都有记录。</p></div><div class="task-toolbar"><el-select v-model="taskStatus" size="small"><el-option label="全部待处理" value="all" /><el-option label="失败" value="failed" /><el-option label="发布中" value="publishing" /><el-option label="待人工确认" value="manual_required" /><el-option label="草稿已创建" value="draft_created" /></el-select><el-button @click="load">刷新</el-button><el-button v-if="canEdit" type="primary" @click="openBatch()">新建批量任务</el-button></div></header>
        <el-table :data="filteredActiveTasks" empty-text="暂无待处理任务">
          <el-table-column prop="content_title" label="文章" min-width="220" show-overflow-tooltip />
          <el-table-column prop="connection_name" label="平台连接" min-width="150"><template #default="scope">{{ scope.row.connection_name || scope.row.platform_name }}</template></el-table-column>
          <el-table-column prop="publish_mode" label="方式" width="110"><template #default="scope">{{ modeName(scope.row.publish_mode) }}</template></el-table-column>
          <el-table-column prop="status" label="状态" min-width="170"><template #default="scope"><el-tag :type="statusType(scope.row.status)">{{ statusName(scope.row.status) }}</el-tag><small v-if="scope.row.last_error" class="task-error">{{ scope.row.last_error }}</small></template></el-table-column>
          <el-table-column prop="updated_at" label="更新时间" width="140"><template #default="scope">{{ date(scope.row.updated_at) }}</template></el-table-column>
          <el-table-column label="操作" width="280" fixed="right">
            <template #default="scope">
              <el-button v-if="scope.row.status === 'manual_required'" link type="primary" @click="handoffPublication(scope.row)">打开发布交接台</el-button>
              <el-button v-if="scope.row.status === 'publishing' && scope.row.platform_code === 'wechat_official'" link type="primary" :loading="syncingId === scope.row.id" @click="syncPublication(scope.row)">同步状态</el-button>
              <el-button v-if="canEdit && scope.row.status === 'failed' && ['draft','publish'].includes(scope.row.publish_mode)" link type="danger" :loading="retryingId === scope.row.id" @click="retryPublication(scope.row)">确认后重试</el-button>
              <el-button link type="primary" @click="showAttempts(scope.row)">尝试记录</el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>
      <section v-if="pendingContents.length" class="pending-suggestions">
        <header><h2>尚未覆盖的内容</h2><span>{{ pendingContents.length }} 篇</span></header>
        <div v-for="item in pendingContents.slice(0, 6)" :key="item.id"><span><b>{{ item.title }}</b><small>{{ item.content_type }} · {{ item.author || '未分配负责人' }}</small></span><el-button link type="primary" @click="openBatch(item)">去分发</el-button></div>
      </section>
    </template>

    <template v-else>
      <section class="table-panel">
        <header><div><h2>已发布记录</h2><p>同一文章可保留多个平台链接，不再互相覆盖。</p></div><el-button @click="selectImport">批量登记</el-button></header>
        <el-table :data="published" empty-text="暂无已发布记录">
          <el-table-column prop="content_title" label="文章" min-width="220" show-overflow-tooltip />
          <el-table-column prop="platform_name" label="平台" width="130" />
          <el-table-column prop="connection_name" label="连接" width="150"><template #default="scope">{{ scope.row.connection_name || '人工登记' }}</template></el-table-column>
          <el-table-column prop="page_url" label="发布链接" min-width="260" show-overflow-tooltip><template #default="scope"><a :href="scope.row.page_url" target="_blank" rel="noopener">{{ scope.row.page_url }}</a></template></el-table-column>
          <el-table-column prop="published_at" label="发布时间" width="150"><template #default="scope">{{ date(scope.row.published_at) }}</template></el-table-column>
          <el-table-column label="操作" width="100"><template #default="scope"><el-button link type="primary" @click="showAttempts(scope.row)">尝试记录</el-button></template></el-table-column>
        </el-table>
      </section>
    </template>

    <el-dialog v-model="connectionDialog" :title="connectionEditingId ? '编辑平台连接' : '添加平台连接'" width="620px" destroy-on-close>
      <div v-if="selectedPlatform" class="dialog-intro"><b>{{ selectedPlatform.name }}</b><span>{{ selectedPlatform.help }}</span></div>
      <el-form label-position="top">
        <el-form-item label="连接名称" required><el-input v-model="connectionForm.name" placeholder="例如：品牌官网、官方知乎账号" /></el-form-item>
        <el-form-item v-if="selectedPlatform?.mode === 'api' && selectedPlatform?.base_url_required !== false" :label="selectedPlatform.base_url_label || '平台地址'" required><el-input v-model="connectionForm.base_url" placeholder="https://example.com" /></el-form-item>
        <el-form-item v-for="field in selectedPlatform?.credential_fields || []" :key="field.key" :label="field.label" :required="!connectionEditingId || !editingConnection?.has_credentials">
          <el-input v-model="connectionForm.credentials[field.key]" :type="field.type" :show-password="field.type === 'password'" :autocomplete="field.type === 'password' ? 'new-password' : 'off'" :placeholder="connectionEditingId && editingConnection?.has_credentials ? '留空保持现有授权信息' : ''" @input="markCredentialsChanged" />
        </el-form-item>
        <el-alert v-if="connectionEditingId && editingConnection?.has_credentials" title="授权信息已加密保存且不会回显；所有字段留空即可保持原值。" type="info" :closable="false" show-icon />
        <el-form-item v-if="connectionEditingId && editingConnection?.has_credentials" label="授权信息"><el-checkbox v-model="connectionForm.clear_credentials" @change="markCredentialsCleared">清除现有授权信息</el-checkbox></el-form-item>
        <el-form-item label="连接状态"><el-switch v-model="connectionForm.enabled" active-text="启用" inactive-text="停用" /></el-form-item>
        <el-form-item v-if="selectedPlatform?.mode === 'api'" label="保存后操作"><el-checkbox v-model="connectionForm.test_after_save">保存后立即测试连接</el-checkbox></el-form-item>
        <el-alert v-if="selectedPlatform?.mode === 'assisted'" title="无需填写平台账号密码。发布时系统会复制适配稿并打开官方编辑器。" type="info" :closable="false" show-icon />
      </el-form>
      <template #footer><el-button @click="connectionDialog = false">取消</el-button><el-button type="primary" :loading="connectionSaving" @click="saveConnection">{{ connectionForm.test_after_save && selectedPlatform?.mode === 'api' ? '保存并测试' : '保存连接' }}</el-button></template>
    </el-dialog>

    <el-dialog v-model="batchDialog" title="批量分发" width="980px" :close-on-click-modal="!batchRunning">
      <el-steps :active="batchStep" finish-status="success" simple><el-step title="选择" /><el-step title="预检" /><el-step title="执行" /><el-step title="完成" /></el-steps>
      <div v-if="batchStep === 0" class="batch-select">
        <el-form label-position="top">
          <el-form-item label="选择文章" required><el-select v-model="batchForm.content_ids" multiple :multiple-limit="20" filterable collapse-tags collapse-tags-tooltip placeholder="最多选择20篇"><el-option v-for="item in contents" :key="item.id" :label="item.title" :value="item.id" /></el-select></el-form-item>
          <el-form-item label="选择平台连接" required><el-select v-model="batchForm.connection_ids" multiple filterable placeholder="选择已就绪的平台"><el-option v-for="item in selectableConnections" :key="item.id" :label="`${item.name} · ${item.platform_name}`" :value="item.id" /></el-select><small v-if="!selectableConnections.length" class="form-tip">请先在“平台连接”中添加并测试 API 平台，或启用辅助发布渠道。</small></el-form-item>
          <el-form-item label="发布方式"><el-radio-group v-model="batchForm.action"><el-radio-button value="draft">优先创建草稿</el-radio-button><el-radio-button value="publish">直接正式发布</el-radio-button></el-radio-group><small class="form-tip">推荐先创建草稿；辅助发布平台始终需要用户在官方编辑器确认。</small></el-form-item>
        </el-form>
      </div>
      <div v-else-if="batchStep === 1 && batchPreview" class="batch-preview">
        <el-alert :title="`共 ${batchPreview.total} 个任务：${batchPreview.ready} 个可执行，${batchPreview.blocked} 个被拦截。`" :type="batchPreview.blocked ? 'warning' : 'success'" :closable="false" show-icon />
        <el-table :data="batchPreview.rows" max-height="420" size="small">
          <el-table-column prop="content_title" label="文章" min-width="190" show-overflow-tooltip /><el-table-column prop="connection_name" label="平台" width="145" /><el-table-column prop="mode" label="方式" width="100"><template #default="scope">{{ modeName(scope.row.mode) }}</template></el-table-column><el-table-column prop="content_chars" label="字数" width="70" /><el-table-column prop="image_count" label="图片" width="65"><template #default="scope">{{ scope.row.image_count ? `${scope.row.image_count} 张` : '—' }}</template></el-table-column><el-table-column label="预检结果" min-width="260"><template #default="scope"><div class="preflight-result"><el-tag :type="scope.row.status === 'ready' ? 'success' : 'danger'">{{ scope.row.status === 'ready' ? '可执行' : '已拦截' }}</el-tag><span v-for="message in scope.row.errors" :key="`e-${message}`" class="preflight-error">{{ message }}</span><span v-for="message in scope.row.warnings" :key="`w-${message}`" class="preflight-warning">{{ message }}</span></div></template></el-table-column>
        </el-table>
      </div>
      <div v-else class="batch-execution">
        <el-progress :percentage="batchProgress" :status="batchRunning ? undefined : batchResults.some(item => !item.ok) ? 'warning' : 'success'" />
        <p v-if="batchRunning && batchCurrent" class="upload-state">正在处理：{{ batchCurrent }}</p>
        <div class="result-list"><div v-for="item in batchResults" :key="`${item.content_id}-${item.connection_id}`"><i class="result-dot" :class="item.run_status === 'succeeded' ? 'ok' : item.run_status === 'failed' ? 'fail' : 'pending'">{{ item.run_status === 'succeeded' ? '✓' : item.run_status === 'failed' ? '!' : item.run_status === 'running' ? '…' : '·' }}</i><span><b>{{ item.content_title }}</b><small>{{ item.connection_name }} · {{ item.run_status === 'queued' ? '排队中' : item.run_status === 'running' ? '发布中' : item.ok ? statusName(item.result.status) : item.error }}</small></span><el-button v-if="item.ok && item.result.status === 'manual_required'" link type="primary" @click="handoffPublication(item.result)">继续人工发布</el-button></div></div>
      </div>
      <template #footer>
        <el-button v-if="batchStep === 0" @click="batchDialog = false">取消</el-button>
        <el-button v-if="batchStep === 1" @click="batchStep = 0">返回修改</el-button>
        <el-button v-if="batchStep === 3" @click="batchDialog = false">关闭</el-button>
        <el-button v-if="batchStep === 3" type="primary" @click="openTaskCenter">查看任务中心</el-button>
        <el-button v-if="batchStep === 0" type="primary" :loading="batchChecking" @click="runPreflight">下一步：发布预检</el-button>
        <el-button v-if="batchStep === 1" type="primary" :disabled="!batchPreview?.ready" :loading="batchRunning" @click="executeBatch">执行 {{ batchPreview?.ready }} 个任务</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="attemptsDialog" title="发布尝试记录" width="760px">
      <div v-if="attemptPublication" class="dialog-intro"><b>{{ attemptPublication.content_title }}</b><span>{{ attemptPublication.connection_name || attemptPublication.platform_name }} · {{ statusName(attemptPublication.status) }}</span></div>
      <el-table v-loading="attemptsLoading" :data="attempts" max-height="430" empty-text="暂无尝试记录">
        <el-table-column prop="started_at" label="开始时间" width="160"><template #default="scope">{{ date(scope.row.started_at) }}</template></el-table-column>
        <el-table-column prop="action" label="操作" width="120"><template #default="scope">{{ ({ draft: '创建草稿', publish: '正式发布', retry_draft: '重试草稿', retry_publish: '重试发布', sync: '同步状态', manual_complete: '人工发布完成' })[scope.row.action] || scope.row.action }}</template></el-table-column>
        <el-table-column prop="status" label="结果" width="100"><template #default="scope"><el-tag :type="scope.row.status === 'succeeded' ? 'success' : scope.row.status === 'failed' ? 'danger' : 'warning'">{{ ({ started: '执行中', succeeded: '成功', failed: '失败' })[scope.row.status] || scope.row.status }}</el-tag></template></el-table-column>
        <el-table-column label="说明" min-width="240"><template #default="scope"><span :class="{ 'invalid': scope.row.error }">{{ scope.row.error || (scope.row.response_summary?.http_status ? `平台 HTTP ${scope.row.response_summary.http_status}` : '已记录平台响应') }}</span></template></el-table-column>
        <el-table-column prop="completed_at" label="完成时间" width="160"><template #default="scope">{{ date(scope.row.completed_at) }}</template></el-table-column>
      </el-table>
      <template #footer><el-button @click="attemptsDialog = false">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="manualDialog" title="登记已发布链接" width="620px">
      <el-form label-position="top"><el-form-item label="内容资产" required><el-select v-model="manualForm.content_id" filterable><el-option v-for="item in contents" :key="item.id" :label="item.title" :value="item.id" /></el-select></el-form-item><el-form-item label="发布平台" required><el-input v-model="manualForm.platform_name" placeholder="例如：知乎、百家号、行业媒体" /></el-form-item><el-form-item label="发布链接" required><el-input v-model="manualForm.page_url" placeholder="https://example.com/article" /></el-form-item></el-form>
      <template #footer><el-button @click="manualDialog = false">取消</el-button><el-button type="primary" :loading="manualSaving" @click="saveManual">保存发布记录</el-button></template>
    </el-dialog>

    <el-dialog v-model="completeDialog" title="辅助发布交接台" width="820px" destroy-on-close>
      <div v-if="handoffItem" class="handoff-workbench">
        <div class="handoff-heading"><span><b>{{ handoffItem.connection_name || handoffItem.platform_name }}</b><small>{{ handoffItem.content_title }} · 内容版本 {{ handoffItem.source_version }}</small></span><el-tag type="warning">等待平台确认</el-tag></div>
        <el-steps :active="completeForm.confirmed ? 3 : handoffOpened ? 2 : (handoffCopied.title || handoffCopied.content) ? 1 : 0" finish-status="success" simple><el-step title="复制内容" /><el-step title="平台发布" /><el-step title="回填链接" /></el-steps>
        <section class="handoff-copy-card">
          <header><b>1. 复制适配内容</b><span>标题和正文分开复制，更适合平台编辑器</span></header>
          <div class="handoff-field"><label>标题</label><el-input :model-value="handoffTitle" readonly /><el-button :type="handoffCopied.title ? 'success' : 'primary'" plain @click="copyHandoffTitle">{{ handoffCopied.title ? '标题已复制' : '复制标题' }}</el-button></div>
          <div class="handoff-body"><label>正文预览 · {{ handoffPlain.length }} 字</label><el-input :model-value="handoffPlain" type="textarea" :rows="8" readonly resize="vertical" /><el-button :type="handoffCopied.content ? 'success' : 'primary'" plain @click="copyHandoffContent">{{ handoffCopied.content ? '正文已复制' : '复制正文（保留格式）' }}</el-button></div>
        </section>
        <section class="handoff-publish-card">
          <header><b>2. 在官方平台发布</b><span>系统不会保存平台密码或 Cookie</span></header>
          <el-alert title="请核对平台账号、封面和排版，再由你在平台页面最终确认发布。" type="warning" :closable="false" show-icon />
          <el-button type="primary" @click="openHandoffEditor">{{ handoffOpened ? '重新打开官方编辑器' : '打开官方编辑器' }}</el-button>
        </section>
        <section class="handoff-complete-card">
          <header><b>3. 回填最终链接</b><span>登记后将计入分发覆盖率并保留操作记录</span></header>
          <el-input v-model="completeForm.page_url" placeholder="粘贴公开文章链接：https://..." clearable />
          <el-checkbox v-model="completeForm.confirmed">我已确认文章发布成功，且该链接可以正常访问</el-checkbox>
        </section>
      </div>
      <template #footer><el-button @click="completeDialog = false">保存任务，稍后完成</el-button><el-button type="primary" :disabled="!completeForm.page_url.trim() || !completeForm.confirmed" :loading="completeSaving" @click="completeManual">验证链接并完成</el-button></template>
    </el-dialog>

    <el-dialog v-model="importDialog" title="Excel 批量登记预检" width="900px">
      <div v-if="importResult" class="import-preview">
        <el-alert v-if="importResult.failed" :title="`发现 ${importResult.failed} 条错误，整批不会写入；请修正 Excel 后重新上传。`" type="error" :closable="false" show-icon />
        <el-alert v-else :title="`预检通过：${importResult.valid} 条记录可以安全导入，同一文章可登记多个平台链接。`" type="success" :closable="false" show-icon />
        <div class="import-summary"><span>文件：{{ importFile?.name }}</span><b>总计 {{ importResult.total }}</b><b class="valid">有效 {{ importResult.valid }}</b><b :class="{ invalid: importResult.failed }">错误 {{ importResult.failed }}</b></div>
        <el-table :data="importResult.rows" max-height="400" size="small" border><el-table-column prop="row_number" label="行" width="58" /><el-table-column prop="content_id" label="资产ID" width="88" /><el-table-column prop="title" label="内容标题" min-width="170" show-overflow-tooltip /><el-table-column prop="platform" label="平台" width="105" /><el-table-column prop="page_url" label="发布链接" min-width="210" show-overflow-tooltip /><el-table-column prop="action" label="写入方式" width="110" /><el-table-column label="检查结果" min-width="170"><template #default="scope"><span v-if="scope.row.status === 'valid'" class="valid">通过</span><span v-else class="invalid">{{ scope.row.errors.join('；') }}</span></template></el-table-column></el-table>
        <p class="import-help">支持前1000行；同一内容资产可以出现多行，但同一发布链接不能重复。<button @click="downloadTemplate">下载 Excel 模板</button></p>
      </div>
      <template #footer><el-button @click="importDialog = false">取消</el-button><el-button :disabled="!importResult || importResult.failed > 0" type="primary" :loading="importing" @click="commitImport">确认批量登记</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.distribution-site-picker{width:220px}
.distribution-page{min-height:100%;padding:22px 26px 40px;background:#f5f7fb;color:#202938}.distribution-hero{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:24px 28px;border:1px solid #e0e5ec;border-radius:12px;background:linear-gradient(135deg,#fff 60%,#eef4ff)}.distribution-hero span{color:#2563eb;font-size:10px;font-weight:800;letter-spacing:1.5px}.distribution-hero h1{margin:6px 0 5px;font-size:26px}.distribution-hero p{margin:0;color:#697386;font-size:12px}.hero-actions{display:flex;gap:8px}.file-input{display:none}.summary-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:16px 0}.summary-grid article{padding:17px 18px;border:1px solid #e1e5eb;border-radius:10px;background:#fff}.summary-grid span,.summary-grid small,.summary-grid strong{display:block}.summary-grid span{color:#6d7685;font-size:11px}.summary-grid strong{margin:5px 0 2px;font-size:25px}.summary-grid small{color:#949baa;font-size:10px}.view-tabs{display:flex;gap:4px;margin-bottom:14px;padding:4px;border:1px solid #e1e5eb;border-radius:9px;background:#fff}.view-tabs button{padding:8px 15px;border:0;border-radius:6px;background:transparent;color:#657083;font-size:12px;font-weight:650;cursor:pointer}.view-tabs button.active{background:#eaf1ff;color:#1d4ed8}.view-tabs b{display:inline-grid;min-width:18px;height:18px;margin-left:4px;place-items:center;border-radius:10px;background:#f59e0b;color:#fff;font-size:10px}.channel-toolbar{display:flex;align-items:center;gap:10px;margin-bottom:14px}.channel-toolbar .el-input{width:280px;margin-left:auto}.channel-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.channel-card{display:flex;min-height:255px;padding:17px;flex-direction:column;border:1px solid #dfe4eb;border-radius:10px;background:#fff}.channel-card.muted{background:#fafbfc}.channel-card header{display:flex;align-items:center;gap:10px}.channel-card header>div{min-width:0;flex:1}.channel-card header strong,.channel-card header small{display:block}.channel-card header strong{font-size:14px}.channel-card header small{margin-top:2px;color:#8b94a3;font-size:10px}.channel-logo{display:grid;width:36px;height:36px;place-items:center;border-radius:9px;background:#2563eb;color:#fff;font-weight:800}.channel-card>p{min-height:38px;margin:14px 0 10px;color:#687386;font-size:11px;line-height:1.7}.capabilities{display:flex;flex-wrap:wrap;gap:5px}.capabilities span{padding:3px 6px;border-radius:5px;background:#eef2f7;color:#667083;font-size:9.5px}.connection-list{display:grid;gap:6px;margin-top:12px}.connection-list>div{display:flex;align-items:center;gap:7px;padding:8px;border-radius:7px;background:#f7f9fc}.connection-list>div>span{min-width:0;flex:1}.connection-list b,.connection-list small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.connection-list b{font-size:10.5px}.connection-list small{color:#9299a5;font-size:9px}.channel-card footer{display:flex;align-items:center;justify-content:space-between;margin-top:auto;padding-top:14px;color:#7b8492;font-size:10px}.table-panel,.pending-suggestions{overflow:hidden;border:1px solid #dfe4eb;border-radius:10px;background:#fff}.table-panel>header,.pending-suggestions>header{display:flex;align-items:center;justify-content:space-between;padding:16px 18px;border-bottom:1px solid #e8ebef}.table-panel h2,.pending-suggestions h2{margin:0;font-size:14px}.table-panel p{margin:3px 0 0;color:#89919f;font-size:10px}.table-panel a{color:#2563eb;text-decoration:none}.muted-text{color:#9098a5;font-size:10px}.pending-suggestions{margin-top:14px}.pending-suggestions>div{display:flex;align-items:center;gap:12px;padding:11px 18px;border-bottom:1px solid #eef0f3}.pending-suggestions>div:last-child{border:0}.pending-suggestions>div>span{min-width:0;flex:1}.pending-suggestions b,.pending-suggestions small{display:block}.pending-suggestions b{font-size:11px}.pending-suggestions small{margin-top:3px;color:#9299a5;font-size:9.5px}.dialog-intro{display:flex;margin-bottom:14px;padding:12px 14px;flex-direction:column;gap:4px;border-radius:8px;background:#f2f6ff}.dialog-intro b{font-size:13px}.dialog-intro span{color:#647085;font-size:10.5px}.batch-select,.batch-preview,.batch-execution{margin-top:18px}.batch-select .el-select{width:100%}.form-tip{display:block;margin-top:6px;color:#8a93a1;font-size:10px}.check-message{margin-left:7px;color:#7a8392;font-size:10px}.batch-execution{display:grid;gap:16px}.result-list{display:grid;max-height:400px;overflow:auto;border:1px solid #e5e8ed;border-radius:8px}.result-list>div{display:flex;align-items:center;gap:10px;padding:10px 12px;border-bottom:1px solid #edf0f3}.result-list>div:last-child{border:0}.result-list>div>span{min-width:0;flex:1}.result-list b,.result-list small{display:block}.result-list b{font-size:11px}.result-list small{margin-top:2px;color:#7f8897;font-size:9.5px}.result-list .ok{color:#16a36a}.result-list .fail{color:#d84b4b}.import-preview{display:grid;gap:14px}.import-summary{display:flex;gap:18px;color:#687386;font-size:12px}.import-summary span{margin-right:auto}.valid{color:#16825d}.invalid{color:#c2413a}.import-help{margin:0;color:#737c8b;font-size:11px}.import-help button{border:0;background:none;color:#2563eb;font-weight:700;cursor:pointer}.el-form{margin-top:12px}.el-select{width:100%}@media(max-width:1150px){.channel-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:800px){.distribution-page{padding:14px}.distribution-hero{align-items:flex-start;flex-direction:column}.hero-actions{width:100%;flex-wrap:wrap}.summary-grid,.channel-grid{grid-template-columns:1fr 1fr}.channel-toolbar{align-items:stretch;flex-direction:column}.channel-toolbar .el-input{width:100%;margin:0}.view-tabs{overflow-x:auto}.view-tabs button{white-space:nowrap}}@media(max-width:560px){.summary-grid,.channel-grid{grid-template-columns:1fr}.hero-actions .el-button{margin-left:0;flex:1}.summary-grid article{padding:14px}.distribution-hero{padding:20px}.batch-preview{overflow-x:auto}}
.result-dot{display:grid;width:20px;height:20px;place-items:center;border-radius:50%;font-size:11px;font-style:normal;font-weight:800}.result-dot.ok{background:#e7f7ef;color:#16825d}.result-dot.fail{background:#feecec;color:#c2413a}.result-dot.pending{background:#eef2f7;color:#64748b}
.upload-state{margin:0;padding:9px 12px;border-radius:7px;background:#eef4ff;color:#315a9d;font-size:11px}
.connection-error,.task-error{display:block;margin-top:3px;color:#c2413a!important;white-space:normal!important}.task-toolbar{display:flex;align-items:center;gap:8px}.task-toolbar .el-select{width:145px}.preflight-result{display:grid;align-items:start;gap:4px}.preflight-result .el-tag{width:max-content}.preflight-error{color:#c2413a;font-size:10px}.preflight-warning{color:#a16207;font-size:10px}
.handoff-workbench{display:grid;gap:14px}.handoff-heading{display:flex;align-items:center;justify-content:space-between}.handoff-heading span,.handoff-heading b,.handoff-heading small{display:block}.handoff-heading small{margin-top:4px;color:#7b8492;font-size:10.5px}.handoff-workbench section{display:grid;gap:10px;padding:14px;border:1px solid #e2e7ee;border-radius:9px;background:#fafbfd}.handoff-workbench section header{display:flex;align-items:center;justify-content:space-between}.handoff-workbench section header b{font-size:12px}.handoff-workbench section header span{color:#8992a0;font-size:10px}.handoff-field{display:grid;grid-template-columns:52px minmax(0,1fr) 110px;align-items:center;gap:8px}.handoff-field label,.handoff-body label{color:#687386;font-size:10.5px}.handoff-body{display:grid;grid-template-columns:minmax(0,1fr) 150px;align-items:end;gap:8px}.handoff-body label{grid-column:1/-1}.handoff-publish-card .el-button{width:max-content}.handoff-complete-card .el-checkbox{height:auto;white-space:normal}@media(max-width:700px){.handoff-field,.handoff-body{grid-template-columns:1fr}.handoff-field label,.handoff-body label{grid-column:1}.handoff-workbench section header{align-items:flex-start;flex-direction:column;gap:3px}}
</style>
