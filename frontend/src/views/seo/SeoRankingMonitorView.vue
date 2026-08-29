<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  collectSeoRankSerp,
  createSeoRankSnapshotBatch,
  createSeoBrandAsset,
  fetchSeoBrandAssets,
  fetchSeoKeywords,
  fetchSeoOverview,
  fetchSeoRankCollectStatus,
  fetchSeoRankProviders,
  fetchSeoSerpResults,
  updateSeoBrandAsset,
  updateSeoSerpOwnership,
} from '../../api/seo'
import { fetchSeoSites } from '../../api/moduleAssets'
import { currentTenantId } from '../../store/session'
import { formatSeoRankTime } from './seoRankTime'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const collecting = ref(false)
const error = ref('')
const rankEngines = new Set(['baidu', 'google', 'bing', '360', 'sogou'])
const engine = ref(rankEngines.has(String(route.query.engine)) ? String(route.query.engine) : 'baidu')
const device = ref(route.query.device === 'mobile' ? 'mobile' : 'desktop')
const sites = ref([])
const siteId = ref(null)
const view = ref('ranking')
const ownership = ref('')
const collectDialog = ref(false)
const manualDialog = ref(false)
const manualImporting = ref(false)
const manualText = ref('')
const collectOutcome = ref(null)
const collectLimit = ref({ allowed: true, retry_after_seconds: 0, next_allowed_at: null, daily_requests_used: 0, daily_requests_limit: 0 })
const providers = ref({})
const clock = ref(Date.now())
const assetDialog = ref(false)
const result = ref({ items: [], total: 0 })
const overview = ref({ stats: {} })
const serp = ref({ items: [], total: 0, stats: {}, captured_at: null })
const assets = ref({ items: [], total: 0 })
const filters = reactive({ q: '', priority: '', alerts: false })
const collectForm = reactive({ keyword_ids: [], devices: ['desktop'], use_ai: true })
const assetForm = reactive({ asset_type: 'content_url', name: '', match_value: '', platform: '' })

const engines = [{ k: 'baidu', n: '百度' }, { k: 'google', n: 'Google' }, { k: 'bing', n: 'Bing' }, { k: '360', n: '360' }, { k: 'sogou', n: '搜狗' }]
const engineName = computed(() => engines.find((item) => item.k === engine.value)?.n || engine.value)
const providerConfigured = computed(() => Boolean(providers.value[engine.value]?.configured))
const ownershipTabs = [
  { k: '', n: '全部结果' },
  { k: 'official_site', n: '官网' },
  { k: 'brand_content', n: '品牌推文' },
  { k: 'ai_suspected', n: 'AI 疑似' },
  { k: 'unresolved', n: '待判断' },
]
const ownershipLabel = {
  official_site: '官网',
  brand_content: '品牌推文',
  ai_suspected: 'AI 疑似',
  unrelated: '非品牌',
  unresolved: '待判断',
}
const methodLabel = {
  exact_url: 'URL 精确匹配',
  published_url: '发布资产匹配',
  official_domain: '官网域名规则',
  site_domain: '站内页面域名',
  platform_account: '平台账号规则',
  ai: 'DeepSeek 判断',
  manual: '人工确认',
  none: '尚未判断',
}
const rows = computed(() => result.value.items.filter((item) =>
  (!filters.priority || item.priority === filters.priority)
  && (!filters.alerts || item.rank_delta < 0)))
const ranked = computed(() => result.value.items.filter((item) => item.latest_rank != null))
const avg = computed(() => ranked.value.length
  ? (ranked.value.reduce((sum, item) => sum + item.latest_rank, 0) / ranked.value.length).toFixed(1)
  : '—')
const requestCount = computed(() => collectForm.keyword_ids.length * collectForm.devices.length)
const estimatedCost = computed(() => (requestCount.value * 0.04).toFixed(2))
const cooldownSeconds = computed(() => collectLimit.value.next_allowed_at
  ? Math.max(0, Math.ceil((new Date(collectLimit.value.next_allowed_at).getTime() - clock.value) / 1000))
  : Number(collectLimit.value.retry_after_seconds || 0))
const dailyLimitReached = computed(() => Number(collectLimit.value.daily_requests_limit || 0) > 0 && Number(collectLimit.value.daily_requests_used || 0) >= Number(collectLimit.value.daily_requests_limit))
const collectAllowed = computed(() => cooldownSeconds.value <= 0 && !dailyLimitReached.value)
const collectButtonText = computed(() => {
  if (collecting.value) return '正在采集…'
  if (cooldownSeconds.value > 0) return `${Math.ceil(cooldownSeconds.value / 60)} 分钟后可更新`
  if (dailyLimitReached.value) return '今日额度已用完'
  return '↻ 更新排名'
})

const fmt = (value) => value == null ? '—' : Number(value).toLocaleString('zh-CN')
const delta = (item) => !item.rank_delta ? '—' : `${item.rank_delta > 0 ? '↑' : '↓'}${Math.abs(item.rank_delta)}`
const deviceLabel = (value) => `${engineName.value} ${value === 'mobile' ? '移动' : 'PC'}`
function openKeywordDetail(keywordId) {
  router.push({ path: `/seo/keywords/${keywordId}`, query: { engine: engine.value, device: device.value } })
}
function spark(item) {
  if (item.latest_rank == null) return ''
  const previous = Math.max(1, item.latest_rank + (item.rank_delta || 0))
  const max = Math.max(previous, item.latest_rank, 10)
  return `2,${2 + previous / max * 24} 90,${2 + item.latest_rank / max * 24}`
}
function exportCsv() {
  const data = [['关键词', '设备', '当前排名', '周期变化', '承接页面'], ...rows.value.map((item) => [item.keyword, device.value, item.latest_rank || '', item.rank_delta || 0, item.rank_url || item.landing_page || ''])]
  const blob = new Blob(['\ufeff' + data.map((line) => line.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(',')).join('\n')], { type: 'text/csv;charset=utf-8' })
  const anchor = document.createElement('a')
  anchor.href = URL.createObjectURL(blob)
  anchor.download = `SEO排名-${engineName.value}-${device.value}.csv`
  anchor.click()
  URL.revokeObjectURL(anchor.href)
}

async function load() {
  if (!currentTenantId.value) { error.value = '请先选择客户'; return }
  if (!siteId.value) { error.value = '请先选择或创建 SEO 网站'; return }
  loading.value = true
  try {
    const common = { tenantId: currentTenantId.value, siteId: siteId.value, engine: engine.value, device: device.value }
    ;[result.value, overview.value, serp.value] = await Promise.all([
      fetchSeoKeywords({ ...common, q: filters.q, pageSize: 200 }),
      fetchSeoOverview(common),
      fetchSeoSerpResults({ tenantId: currentTenantId.value, siteId: siteId.value, engine: engine.value, device: device.value, ownershipType: ownership.value, limit: 500 }),
    ])
    error.value = ''
  } catch (err) {
    error.value = err.message
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
    const selected = sites.value.some((item) => item.id === siteId.value)
      ? siteId.value
      : (sites.value.find((item) => item.status === 'active')?.id || sites.value[0]?.id || null)
    if (selected !== siteId.value) siteId.value = selected
    else await load()
  } catch (err) {
    error.value = err.message
  }
}

async function loadCollectStatus() {
  if (!currentTenantId.value || !siteId.value) return
  try { collectLimit.value = await fetchSeoRankCollectStatus({ tenantId: currentTenantId.value, siteId: siteId.value }) }
  catch (err) { error.value = err.message }
}

async function loadProviders() {
  if (!currentTenantId.value || !siteId.value) return
  try { providers.value = await fetchSeoRankProviders({ tenantId: currentTenantId.value, siteId: siteId.value }) }
  catch (err) { error.value = err.message }
}

function openCollect() {
  if (!currentTenantId.value) return ElMessage.warning('请先选择客户')
  if (!siteId.value) return ElMessage.warning('请先选择或创建 SEO 网站')
  if (!providers.value[engine.value]?.configured) return ElMessage.warning(`${engineName.value} 排名服务尚未配置`)
  if (!collectAllowed.value) return ElMessage.warning(collectButtonText.value)
  const availableIds = result.value.items.map((item) => item.id)
  const retainedIds = collectForm.keyword_ids.filter((id) => availableIds.includes(id))
  collectForm.keyword_ids = retainedIds.length ? retainedIds : availableIds.slice(0, 20)
  collectDialog.value = true
}

function showCollectedDevice() {
  if (collectOutcome.value?.device) device.value = collectOutcome.value.device
}

async function collect() {
  if (!currentTenantId.value) { ElMessage.warning('请先选择客户'); return }
  if (!siteId.value) { ElMessage.warning('请先选择或创建 SEO 网站'); return }
  if (!collectForm.keyword_ids.length) { ElMessage.warning('至少选择一个关键词'); return }
  if (!collectForm.devices.length) { ElMessage.warning('至少选择一个设备'); return }
  collecting.value = true
  try {
    const summary = await collectSeoRankSerp({
      tenant_id: currentTenantId.value,
      site_id: siteId.value,
      engine: engine.value,
      keyword_ids: collectForm.keyword_ids,
      max_keywords: collectForm.keyword_ids.length,
      devices: collectForm.devices,
      use_ai: collectForm.use_ai,
    })
    if (summary.manual_limit) collectLimit.value = summary.manual_limit
    collectDialog.value = false
    const failed = Array.isArray(summary.errors) ? summary.errors.length : 0
    const collectedDevice = collectForm.devices.length === 1 ? collectForm.devices[0] : null
    collectOutcome.value = {
      status: failed ? 'partial' : 'success',
      title: failed
        ? `采集部分完成：${summary.snapshots}/${summary.requests} 个排名快照成功，${failed} 个请求失败`
        : `采集完成：${summary.snapshots} 个排名快照成功`,
      requests: Number(summary.requests || 0),
      snapshots: Number(summary.snapshots || 0),
      serpResults: Number(summary.serp_results || 0),
      failed,
      device: collectedDevice,
      deviceText: collectForm.devices.map(deviceLabel).join('、'),
      completedAt: formatSeoRankTime(new Date()),
    }
    if (failed) {
      ElMessage.warning(collectOutcome.value.title)
    } else {
      ElMessage.success(`采集完成：${summary.snapshots} 个排名快照，确认 ${summary.confirmed_brand_results} 条品牌结果`)
    }
    await load()
  } catch (err) {
    collectDialog.value = false
    collectOutcome.value = {
      status: 'failed',
      title: `采集失败：${err.message}`,
      requests: requestCount.value,
      snapshots: 0,
      serpResults: 0,
      failed: requestCount.value,
      device: null,
      deviceText: collectForm.devices.map(deviceLabel).join('、'),
      completedAt: formatSeoRankTime(new Date()),
    }
    ElMessage.error(err.message)
    await loadCollectStatus()
  } finally {
    collecting.value = false
  }
}

async function openAssets() {
  if (!currentTenantId.value) return
  assets.value = await fetchSeoBrandAssets({ tenantId: currentTenantId.value, siteId: siteId.value })
  assetDialog.value = true
}
async function addAsset() {
  if (!assetForm.name.trim() || !assetForm.match_value.trim()) {
    ElMessage.warning('请填写名称和匹配内容')
    return
  }
  try {
    await createSeoBrandAsset({
      tenant_id: currentTenantId.value,
      site_id: siteId.value,
      asset_type: assetForm.asset_type,
      name: assetForm.name,
      match_value: assetForm.match_value,
      platform: assetForm.platform || undefined,
    })
    Object.assign(assetForm, { name: '', match_value: '', platform: '' })
    assets.value = await fetchSeoBrandAssets({ tenantId: currentTenantId.value, siteId: siteId.value })
    ElMessage.success('品牌识别规则已添加')
  } catch (err) {
    ElMessage.error(err.message)
  }
}

async function importManualRanks() {
  const keywordByName = new Map(result.value.items.map((item) => [item.keyword.trim().toLowerCase(), item]))
  const keywordById = new Map(result.value.items.map((item) => [String(item.id), item]))
  const lines = manualText.value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
  const items = []
  const errors = []
  lines.forEach((line, index) => {
    const cells = line.split(/\t|,/).map((cell) => cell.trim())
    const keyword = keywordById.get(cells[0]) || keywordByName.get((cells[0] || '').toLowerCase())
    const rank = Number(cells[1])
    const rowDevice = cells[2] || device.value
    if (!keyword) errors.push(`第 ${index + 1} 行关键词不存在`)
    else if (!Number.isInteger(rank) || rank < 1 || rank > 100) errors.push(`第 ${index + 1} 行排名应为 1–100`)
    else if (!['desktop','mobile'].includes(rowDevice)) errors.push(`第 ${index + 1} 行设备应为 desktop 或 mobile`)
    else items.push({ tenant_id: currentTenantId.value, site_id: siteId.value, keyword_id: keyword.id, engine: engine.value, device: rowDevice, region: '全国', rank, result_url: cells[3] || null, checked_at: new Date().toISOString(), source: 'manual_import' })
  })
  if (errors.length) return ElMessage.warning(errors.slice(0, 3).join('；'))
  if (!items.length) return ElMessage.warning('请粘贴至少一行真实排名数据')
  manualImporting.value = true
  try {
    await createSeoRankSnapshotBatch({ tenant_id: currentTenantId.value, items })
    manualDialog.value = false; manualText.value = ''; ElMessage.success(`已导入 ${items.length} 条 ${engineName.value} 真实排名快照`); await load()
  } catch (err) { ElMessage.error(err.message) } finally { manualImporting.value = false }
}
async function toggleAsset(item) {
  try {
    await updateSeoBrandAsset({ assetId: item.id, tenantId: currentTenantId.value, payload: { status: item.status === 'active' ? 'archived' : 'active' } })
    assets.value = await fetchSeoBrandAssets({ tenantId: currentTenantId.value, siteId: siteId.value })
    ElMessage.success(item.status === 'active' ? '品牌资产已归档' : '品牌资产已启用')
  } catch (err) { ElMessage.error(err.message) }
}
async function confirmOwnership(item, ownershipType) {
  try {
    await updateSeoSerpOwnership({ resultId: item.id, tenantId: currentTenantId.value, siteId: siteId.value, ownershipType })
    ElMessage.success(ownershipType === 'brand_content' ? '已确认品牌推文，并加入资产库' : ownershipType === 'official_site' ? '已确认官网结果' : '已标记非品牌')
    await load()
  } catch (err) {
    ElMessage.error(err.message)
  }
}

let timer
watch(() => filters.q, () => { clearTimeout(timer); timer = setTimeout(load, 260) })
watch([engine, device, siteId, ownership], load)
watch(siteId, loadCollectStatus)
watch(siteId, loadProviders)
watch([currentTenantId, siteId], () => { collectOutcome.value = null; collectForm.keyword_ids = [] })
watch(currentTenantId, loadSites)
let clockTimer
onMounted(async () => { clockTimer = window.setInterval(() => { clock.value = Date.now() }, 1000); await loadSites(); await Promise.all([loadCollectStatus(), loadProviders()]) })
onBeforeUnmount(() => window.clearInterval(clockTimer))
</script>

<template>
  <div class="keyword-assets ranking-prototype" v-loading="loading">
    <section class="kw-hero">
      <div>
        <div class="kw-kicker">Ranking monitor</div>
        <h2>排名监控</h2>
        <p>统一查看百度、Google、Bing、360 与搜狗排名；自动接口未配置时可导入真人实测数据。</p>
      </div>
      <div class="hero-controls">
        <el-select v-model="siteId" class="site-picker" placeholder="选择 SEO 网站">
          <el-option v-for="site in sites" :key="site.id" :label="site.name || site.canonical_domain" :value="site.id" />
        </el-select>
        <el-select v-model="engine" class="site-picker" placeholder="选择搜索引擎">
          <el-option v-for="item in engines" :key="item.k" :label="`${item.n}${providers[item.k]?.configured ? '' : '（可人工导入）'}`" :value="item.k" />
        </el-select>
        <div class="kw-segment device-switch">
          <button :class="{ active: device === 'desktop' }" @click="device = 'desktop'">{{ engineName }} PC</button>
          <button :class="{ active: device === 'mobile' }" @click="device = 'mobile'">{{ engineName }} 移动</button>
        </div>
        <div class="kw-actions">
          <button class="kw-btn" @click="openAssets">品牌资产</button>
          <button class="kw-btn" @click="manualDialog = true">导入实测排名</button>
          <button class="kw-btn" @click="exportCsv">⇩ 导出排名</button>
          <button class="kw-btn primary" :disabled="!collectAllowed || collecting || !providerConfigured" @click="openCollect">{{providerConfigured ? collectButtonText : '自动采集未配置'}}</button>
        </div>
      </div>
    </section>

    <el-alert v-if="error" :title="error" type="warning" :closable="false" />

    <section v-if="collectOutcome" class="collect-outcome" :class="collectOutcome.status" aria-live="polite">
      <header>
        <div>
          <strong>{{ collectOutcome.title }}</strong>
          <span>完成时间 {{ collectOutcome.completedAt }} · 本次设备 {{ collectOutcome.deviceText || '—' }}</span>
        </div>
        <button type="button" aria-label="关闭采集结果" @click="collectOutcome = null">×</button>
      </header>
      <div class="collect-outcome-stats">
        <span><b>{{ collectOutcome.requests }}</b>请求</span>
        <span><b>{{ collectOutcome.snapshots }}</b>成功快照</span>
        <span><b>{{ collectOutcome.serpResults }}</b>SERP 结果</span>
        <span><b>{{ collectOutcome.failed }}</b>失败</span>
      </div>
      <footer>
        <span>{{ collectOutcome.failed ? '失败请求已记录，本页面不会自动重试。' : '本次采集已完成。' }}结果会保留在页面上，避免重复采集。</span>
        <button
          v-if="collectOutcome.device && collectOutcome.device !== device"
          type="button"
          class="kw-btn small"
          @click="showCollectedDevice"
        >查看本次{{ deviceLabel(collectOutcome.device) }}结果</button>
      </footer>
    </section>

    <section class="kw-metrics">
      <article class="kw-metric" data-mark="K"><span>监控关键词</span><strong>{{ fmt(result.total) }}</strong><small>{{ deviceLabel(device) }}关键词资产</small></article>
      <article class="kw-metric" data-mark="R"><span>平均自然排名</span><strong>{{ avg }}</strong><small class="up">确认归属结果 · 越小越好</small></article>
      <article class="kw-metric" data-mark="官"><span>官网结果</span><strong>{{ fmt(serp.stats?.official_site || 0) }}</strong><small>官网域名与站内页面</small></article>
      <article class="kw-metric" data-mark="文"><span>品牌推文</span><strong>{{ fmt(serp.stats?.brand_content || 0) }}</strong><small class="up">URL / 账号规则确认</small></article>
      <article class="kw-metric coral" data-mark="AI"><span>AI 疑似</span><strong>{{ fmt(serp.stats?.ai_suspected || 0) }}</strong><small>等待人工复核</small></article>
    </section>

    <section class="kw-card">
      <header class="kw-card-head monitor-head">
        <div>
          <h3>{{ view === 'ranking' ? '自然排名明细' : `${engineName} 搜索结果品牌识别` }}</h3>
          <p>{{ serp.captured_at ? `最近采集 ${formatSeoRankTime(serp.captured_at)}` : '尚未采集前 50 搜索结果' }} · {{ device === 'desktop' ? 'PC' : '移动' }} · 全国</p>
        </div>
        <div class="kw-segment">
          <button :class="{ active: view === 'ranking' }" @click="view = 'ranking'">关键词排名</button>
          <button :class="{ active: view === 'serp' }" @click="view = 'serp'">品牌结果</button>
        </div>
      </header>

      <template v-if="view === 'ranking'">
        <div class="kw-card-body">
          <div class="kw-toolbar">
            <div class="kw-search"><input v-model="filters.q" class="kw-input" placeholder="搜索监控关键词"></div>
            <select v-model="filters.priority" class="kw-select"><option value="">全部优先级</option><option v-for="priority in ['P0', 'P1', 'P2', 'P3']" :key="priority">{{ priority }}</option></select>
            <button class="kw-btn ghost" :class="{ active: filters.alerts }" @click="filters.alerts = !filters.alerts">仅看异常 {{ result.items.filter((item) => item.rank_delta < 0).length }}</button>
          </div>
        </div>
        <div class="kw-table-wrap">
          <table class="kw-table">
            <thead><tr><th>关键词</th><th>优先级</th><th>当前排名</th><th>周期趋势</th><th>排名网址</th><th>状态</th><th>详情</th></tr></thead>
            <tbody>
              <tr v-for="row in rows" :key="row.id">
                <td class="keyword-cell"><span class="kw-name"><button @click="openKeywordDetail(row.id)">{{ row.keyword }}</button></span><small class="kw-sub">{{ row.cluster || '未归类' }}</small></td>
                <td><span class="kw-priority" :class="row.priority.toLowerCase()">{{ row.priority }}</span></td>
                <td><span class="kw-rank"><strong>{{ row.latest_rank || '50+' }}</strong><i :class="row.rank_delta > 0 ? 'up' : row.rank_delta < 0 ? 'down' : ''">{{ delta(row) }}</i></span></td>
                <td><svg v-if="spark(row)" width="92" height="28" viewBox="0 0 92 28"><polyline :points="spark(row)" fill="none" :stroke="row.rank_delta >= 0 ? '#248a64' : '#d9544d'" stroke-width="2" /></svg><span v-else>—</span></td>
                <td><div class="kw-link">{{ row.rank_url || '前 50 暂无已确认品牌结果' }}</div></td>
                <td><span class="kw-pill" :class="row.latest_rank == null ? 'gray' : row.rank_delta < 0 ? 'red' : 'green'">{{ row.latest_rank == null ? '50名外' : row.rank_delta < 0 ? '排名波动' : '已覆盖' }}</span></td>
                <td><button class="kw-btn small" @click="openKeywordDetail(row.id)">查看历史 →</button></td>
              </tr>
              <tr v-if="!rows.length"><td colspan="7"><div class="kw-empty"><b>暂无排名数据</b>{{providerConfigured ? `点击“更新排名”采集 ${engineName} 搜索结果` : `通过“导入实测排名”录入 ${engineName} 真人测试结果`}}</div></td></tr>
            </tbody>
          </table>
        </div>
      </template>

      <template v-else>
        <div class="kw-card-body ownership-toolbar">
          <div class="kw-segment ownership-tabs">
            <button v-for="item in ownershipTabs" :key="item.k" :class="{ active: ownership === item.k }" @click="ownership = item.k">{{ item.n }}</button>
          </div>
          <span>当前批次 {{ serp.total }} 条</span>
        </div>
        <div class="kw-table-wrap">
          <table class="kw-table serp-table">
            <thead><tr><th>关键词 / 排名</th><th>搜索结果</th><th>归属</th><th>判断依据</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="item in serp.items" :key="item.id">
                <td><b>{{ item.keyword }}</b><small class="kw-sub">第 {{ item.rank }} 名 · {{ item.device === 'desktop' ? 'PC' : '移动' }}</small></td>
                <td class="result-cell"><a :href="item.result_url" target="_blank" rel="noopener">{{ item.title || item.result_url }}</a><small>{{ item.domain }} · {{ item.description }}</small></td>
                <td><span class="kw-pill" :class="item.ownership_type === 'official_site' || item.ownership_type === 'brand_content' ? 'green' : item.ownership_type === 'ai_suspected' ? 'orange' : item.ownership_type === 'unresolved' ? 'red' : 'gray'">{{ ownershipLabel[item.ownership_type] }}</span></td>
                <td><b>{{ methodLabel[item.match_method] }}</b><small class="kw-sub">{{ item.confidence == null ? '无置信度' : `置信度 ${item.confidence}%` }}{{ item.is_confirmed ? ' · 已确认' : '' }}</small></td>
                <td class="review-actions">
                  <button v-if="!item.is_confirmed" @click="confirmOwnership(item, 'brand_content')">品牌推文</button>
                  <button v-if="!item.is_confirmed" @click="confirmOwnership(item, 'official_site')">官网</button>
                  <button v-if="!item.is_confirmed" class="muted" @click="confirmOwnership(item, 'unrelated')">非品牌</button>
                  <span v-else>已确认</span>
                </td>
              </tr>
              <tr v-if="!serp.items.length"><td colspan="5"><div class="kw-empty"><b>暂无搜索结果</b>采集后在这里逐条确认品牌推文</div></td></tr>
            </tbody>
          </table>
        </div>
      </template>
    </section>

    <el-dialog v-model="collectDialog" :title="`采集 ${engineName} 实时排名`" width="520px" destroy-on-close>
      <div class="collect-form">
        <label><span>采集关键词</span><el-select v-model="collectForm.keyword_ids" multiple filterable collapse-tags collapse-tags-tooltip :multiple-limit="50" placeholder="选择要更新的关键词"><el-option v-for="item in result.items" :key="item.id" :label="`${item.keyword}（ID ${item.id}）`" :value="item.id" /></el-select><small>已选择 {{ collectForm.keyword_ids.length }} 个关键词；只会采集明确勾选的关键词。</small></label>
        <label><span>采集设备</span><el-checkbox-group v-model="collectForm.devices"><el-checkbox value="desktop">{{ engineName }} PC</el-checkbox><el-checkbox value="mobile">{{ engineName }} 移动</el-checkbox></el-checkbox-group></label>
        <label><span>AI 兜底判断</span><el-switch v-model="collectForm.use_ai" /><small>仅处理 URL、官网域名和平台账号规则无法识别的结果</small></label>
        <div class="cost-note"><b>预计调用 {{ requestCount }} 次{{ engine === 'baidu' ? '站长之家' : 'DataForSEO' }}实时接口</b><span v-if="engine === 'baidu'">按最高单价 0.04 元/次估算，约 ¥{{ estimatedCost }}；实际以购买套餐为准。</span><span>同一网站人工更新后冷却 1 小时；今日已使用 {{collectLimit.daily_requests_used||0}} / {{collectLimit.daily_requests_limit||0}} 次请求。</span></div>
      </div>
      <template #footer><button class="kw-btn" @click="collectDialog = false">取消</button><button class="kw-btn primary" :disabled="collecting || !collectForm.keyword_ids.length || !collectForm.devices.length" @click="collect">{{ collecting ? '正在采集…' : '确认采集' }}</button></template>
    </el-dialog>

    <el-dialog v-model="manualDialog" :title="`导入 ${engineName} 真人实测排名`" width="620px">
      <p class="import-tip">每行格式：关键词或关键词ID、排名、设备、结果URL。支持逗号或制表符；设备填写 desktop 或 mobile，结果URL可留空。</p>
      <el-input v-model="manualText" type="textarea" :rows="10" placeholder="工业齿轮箱,8,desktop,https://example.com/product&#10;1024,12,mobile,https://example.com/mobile" />
      <template #footer><button class="kw-btn" @click="manualDialog=false">取消</button><button class="kw-btn primary" :disabled="manualImporting" @click="importManualRanks">{{manualImporting?'导入中…':'确认导入'}}</button></template>
    </el-dialog>

    <el-dialog v-model="assetDialog" title="品牌识别资产" width="760px">
      <div class="asset-create">
        <el-select v-model="assetForm.asset_type"><el-option label="官网域名" value="official_domain" /><el-option label="品牌推文 URL" value="content_url" /><el-option label="平台账号特征" value="platform_account" /></el-select>
        <el-input v-model="assetForm.name" placeholder="资产名称" />
        <el-input v-model="assetForm.match_value" :placeholder="assetForm.asset_type === 'official_domain' ? 'example.com' : assetForm.asset_type === 'content_url' ? 'https://...' : '账号名或账号ID'" />
        <el-input v-model="assetForm.platform" placeholder="平台（可选）" />
        <button class="kw-btn primary" @click="addAsset">添加</button>
      </div>
      <div class="asset-list"><div v-for="item in assets.items" :key="item.id"><span class="kw-pill" :class="item.status==='active'?'blue':'gray'">{{ item.asset_type === 'official_domain' ? '官网' : item.asset_type === 'content_url' ? '推文' : '账号' }}</span><b>{{ item.name }}<small>{{ item.platform || '未指定平台' }}</small></b><small>{{ item.match_value }}</small><button class="kw-btn small" @click="toggleAsset(item)">{{item.status==='active'?'归档':'启用'}}</button></div><div v-if="!assets.items.length" class="kw-empty">尚未登记品牌识别资产</div></div>
    </el-dialog>
  </div>
</template>

<style>@import url('../../../public/deal-sniper-prototype/seo/assets/keyword-assets-v2.css');</style>
<style scoped>
.site-picker{width:240px}
.collect-outcome{margin:14px 0;padding:16px 18px;border:1px solid #9ed8be;border-radius:12px;background:#f0fbf6;color:#1e5d47}.collect-outcome.partial{border-color:#f0ca78;background:#fff9eb;color:#76540d}.collect-outcome.failed{border-color:#efaaa6;background:#fff3f2;color:#8b302b}.collect-outcome header,.collect-outcome footer{display:flex;align-items:center;justify-content:space-between;gap:18px}.collect-outcome header strong,.collect-outcome header span{display:block}.collect-outcome header span,.collect-outcome footer span{margin-top:4px;font-size:13px;opacity:.8}.collect-outcome header>button{border:0;background:none;color:inherit;font-size:22px;cursor:pointer}.collect-outcome-stats{display:flex;flex-wrap:wrap;gap:12px;margin:14px 0}.collect-outcome-stats span{padding:7px 10px;border-radius:8px;background:rgba(255,255,255,.72);font-size:13px}.collect-outcome-stats b{margin-right:4px;font-size:17px}
.ranking-prototype{min-height:100%;padding:22px 26px 30px;background:#f5f7fb}.hero-controls{display:flex;flex-direction:column;align-items:flex-end;gap:18px}.device-switch{background:#f2f5fb}.kw-metrics{grid-template-columns:repeat(5,minmax(0,1fr))}.kw-metric.coral{border-top-color:#e66a5f}.monitor-head{align-items:center}.ownership-toolbar{display:flex;align-items:center;justify-content:space-between}.ownership-tabs{flex-wrap:wrap}.kw-name button{padding:0;border:0;background:none;color:#2457d6;font-weight:700;cursor:pointer}.kw-btn.active{border-color:#d9544d;color:#d9544d}.result-cell{max-width:580px}.result-cell a{display:block;color:#1a4fc4;font-weight:700;text-decoration:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.result-cell small{display:block;max-width:560px;margin-top:5px;color:#8792a8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.review-actions{white-space:nowrap}.review-actions button{border:0;background:none;color:#245fdb;font-weight:700;cursor:pointer;margin-right:10px}.review-actions button.muted{color:#8c96aa}.review-actions span{color:#248a64}.collect-form{display:grid;gap:22px}.collect-form>label{display:grid;grid-template-columns:120px 1fr;align-items:center;gap:12px}.collect-form label>span{font-weight:700;color:#27334a}.collect-form label>small{grid-column:2;color:#8490a5}.cost-note{padding:16px 18px;border:1px solid #dce5f5;border-radius:12px;background:#f6f9ff}.cost-note b,.cost-note span{display:block}.cost-note span{margin-top:6px;color:#77839a}.asset-create{display:grid;grid-template-columns:140px 150px minmax(220px,1fr) 150px auto;gap:10px}.asset-list{margin-top:20px;border:1px solid #e3e8f1;border-radius:12px;overflow:hidden}.asset-list>div{display:grid;grid-template-columns:70px 180px minmax(220px,1fr) auto;gap:12px;align-items:center;padding:13px 16px;border-bottom:1px solid #edf0f5}.asset-list>div:last-child{border-bottom:0}.asset-list b small{display:block;margin-top:3px;font-weight:400}.asset-list small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#7b879b}.import-tip{margin:0 0 12px;color:#6f7d91;font-size:13px;line-height:1.6}@media(max-width:1280px){.kw-metrics{grid-template-columns:repeat(3,1fr)}.hero-controls{align-items:flex-start}.kw-hero{flex-direction:column}.asset-create{grid-template-columns:1fr 1fr}.result-cell{max-width:360px}}
</style>
