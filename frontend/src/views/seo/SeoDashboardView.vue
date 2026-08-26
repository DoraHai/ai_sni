<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { collectSeoOverviewMetrics, crawlSeoSite, createSeoKeyword, fetchSeoOverview } from '../../api/seo'
import { fetchSeoSites } from '../../api/moduleAssets'
import { currentTenantId, session } from '../../store/session'
import './seo-suite.css'

const router = useRouter()
const loading = ref(false)
const saving = ref(false)
const collecting = ref(false)
const crawling = ref(false)
const error = ref('')
const engine = ref('baidu')
const sites = ref([])
const siteId = ref(null)
const search = ref('')
const addDialog = ref(false)
const data = ref({ stats: {}, opportunities: [], page_issues: [], collection_status: [], trend: [], tasks: [] })
const form = reactive({ keyword: '', cluster: '', intent: '', monthly_volume: null, difficulty: null, priority: 'P2', landing_page: '' })
const engines = [
  { k: 'baidu', n: '百度', color: '#2563eb' },
  { k: 'bing', n: 'Bing', color: '#0ea5a1' },
  { k: '360', n: '360', color: '#ef6b55' },
  { k: 'sogou', n: '搜狗', color: '#79aa38' },
  { k: 'google', n: 'Google', color: '#8b5cf6' },
]
const stats = computed(() => data.value.stats || {})
const tasks = computed(() => data.value.tasks || [])
const metrics = computed(() => data.value.metrics || {})
const canEdit = computed(() => !session.isLoggedIn || session.canEdit('seo.keywords'))
const fmt = (value) => Number(value || 0).toLocaleString('zh-CN')
const updatedLabel = computed(() => data.value.last_updated_at ? new Date(data.value.last_updated_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '尚无采集记录')
const metricValue = (item) => item?.numeric_value ?? item?.text_value ?? '—'
const metricStatus = (item) => ({ available: '已采集', stale: '需更新', failed: '采集失败', pending: '待采集', not_configured: '未接入' }[item?.status] || '待采集')

function chartPoints(key) {
  const rows = data.value.trend || []
  if (!rows.length) return ''
  const max = Math.max(...rows.map((row) => Number(row[key] || 0)), 1)
  return rows.map((row, index) => {
    const x = rows.length === 1 ? 50 : 16 + index * (728 / (rows.length - 1))
    const y = 174 - Number(row[key] || 0) / max * 130
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
}

function goSearch() {
  router.push({ path: '/seo/keywords', query: search.value.trim() ? { q: search.value.trim() } : {} })
}

async function load() {
  if (!currentTenantId.value) { error.value = '请先选择客户'; return }
  loading.value = true
  error.value = ''
  try { data.value = await fetchSeoOverview({ tenantId: currentTenantId.value, siteId: siteId.value, engine: engine.value }) }
  catch (e) { error.value = e.message }
  finally { loading.value = false }
}

async function loadSites() {
  if (!currentTenantId.value) { sites.value = []; siteId.value = null; return load() }
  try {
    sites.value = (await fetchSeoSites(currentTenantId.value)).sites || []
    const nextSiteId = sites.value.some((item) => item.id === siteId.value) ? siteId.value : (sites.value.find((item) => item.status === 'active')?.id || sites.value[0]?.id || null)
    if (nextSiteId !== siteId.value) { siteId.value = nextSiteId; return }
  } catch (e) {
    error.value = e.message
    sites.value = []
    siteId.value = null
  }
  await load()
}

async function collectMetrics() {
  if (!siteId.value) return ElMessage.warning('请先选择或创建 SEO 网站')
  collecting.value = true
  try {
    await collectSeoOverviewMetrics({ tenant_id: currentTenantId.value, site_id: siteId.value })
    ElMessage.success('网站指标采集完成')
    await load()
  } catch (e) { ElMessage.error(e.message) }
  finally { collecting.value = false }
}

async function startCrawl() {
  if (!siteId.value) return ElMessage.warning('请先选择或创建 SEO 网站')
  crawling.value = true
  try {
    const result = await crawlSeoSite({ tenant_id: currentTenantId.value, site_id: siteId.value, max_urls: 50, max_depth: 3 })
    ElMessage.success(`网站扫描完成，共抓取 ${result.run?.fetched_count || 0} 个页面`)
    await load()
  } catch (e) { ElMessage.error(e.message) }
  finally { crawling.value = false }
}

function handleTask(task) {
  if (task.type === 'collection') return collectMetrics()
  if (task.type === 'crawl') return startCrawl()
  router.push(task.path)
}

async function saveKeyword() {
  if (!form.keyword.trim()) return ElMessage.warning('请填写关键词')
  saving.value = true
  try {
    await createSeoKeyword({
      tenant_id: currentTenantId.value,
      site_id: siteId.value,
      keyword: form.keyword.trim(),
      cluster: form.cluster || null,
      intent: form.intent || null,
      monthly_volume: form.monthly_volume,
      difficulty: form.difficulty,
      priority: form.priority,
      landing_page: form.landing_page || null,
    })
    addDialog.value = false
    Object.assign(form, { keyword: '', cluster: '', intent: '', monthly_volume: null, difficulty: null, priority: 'P2', landing_page: '' })
    ElMessage.success('关键词已加入资产库')
    await load()
  } catch (e) { ElMessage.error(e.message) }
  finally { saving.value = false }
}

watch([engine, siteId], load)
watch(currentTenantId, loadSites)
onMounted(loadSites)
</script>

<template>
  <div class="dashboard" v-loading="loading">
    <section class="command-bar">
      <div><h1>SEO 工作台</h1><p>自然搜索运营总览 · {{ engines.find(item => item.k === engine)?.n }}</p></div>
      <div class="command-actions">
        <el-select v-model="siteId" clearable placeholder="选择 SEO 网站" class="site-select">
          <el-option v-for="site in sites" :key="site.id" :label="site.name" :value="site.id"><span>{{ site.name }}</span><small>{{ site.canonical_domain }}</small></el-option>
        </el-select>
        <el-input v-model="search" clearable placeholder="搜索关键词 / 页面" @keyup.enter="goSearch"><template #prefix>⌕</template></el-input>
        <span class="freshness"><i />{{ updatedLabel }}</span>
        <button type="button" :disabled="!siteId" @click="collectMetrics">{{ collecting ? '采集中…' : '更新网站数据' }}</button>
        <button type="button" :disabled="!siteId || crawling" @click="startCrawl">{{ crawling ? '扫描中…' : '扫描网站' }}</button>
        <button type="button" @click="router.push('/seo/rankings')">查看历史</button>
        <button v-if="canEdit" class="primary" type="button" @click="addDialog = true">＋ 添加关键词</button>
      </div>
    </section>

    <el-alert v-if="error" :title="error" type="warning" :closable="false" />

    <section class="today-card">
      <div><h2>今天先处理 {{ tasks.length }} 项 SEO 任务</h2><p>排名异常、关键词内容缺口和站内页面问题已按获客影响排序。</p></div>
      <div class="flow"><span>关键词资产</span><b>→</b><span>每日采集</span><b>→</b><span>竞品对比</span><b>→</b><span>内容执行</span></div>
    </section>

    <section class="collector">
      <strong>排名数据采集</strong>
      <div v-for="item in data.collection_status" :key="item.engine" class="collector-item">
        <i :style="{ background: engines.find(engineItem => engineItem.k === item.engine)?.color }" />
        <b>{{ engines.find(engineItem => engineItem.k === item.engine)?.n }}</b>
        <span>{{ fmt(item.collected) }} / {{ fmt(item.total) }}</span>
        <em :class="item.status">{{ item.status === 'ready' ? '已覆盖' : item.status === 'partial' ? '部分覆盖' : '待接入' }}</em>
      </div>
      <small>数据来自排名快照；未接采集源时不会生成虚假数据</small>
    </section>

    <section class="engine-tabs">
      <button v-for="item in engines" :key="item.k" :class="{ active: engine === item.k }" @click="engine = item.k">{{ item.n }}</button>
    </section>

    <section class="metric-row">
      <article class="blue"><span>监控关键词</span><strong>{{ fmt(stats.keywords) }}</strong><small><b>+{{ fmt(stats.new_keywords_30d) }}</b> 近 30 天新增</small></article>
      <article class="teal"><span>进入搜索 Top 10</span><strong>{{ fmt(stats.top10) }}</strong><small><b>{{ stats.top10_rate || 0 }}%</b> 关键词覆盖</small></article>
      <article class="coral"><span>今日排名异动</span><strong>{{ fmt(stats.rank_anomalies) }}</strong><small><b>{{ fmt(stats.rank_anomalies) }} 个</b> 需要立即跟进</small></article>
      <article class="green"><span>待优化页面</span><strong>{{ fmt(stats.pages_needing_fix) }}</strong><small><b>{{ fmt(stats.healthy_pages) }} 个</b> 页面状态健康</small></article>
    </section>

    <section class="site-metric-grid">
      <article>
        <header><span>百度收录估算</span><em :class="metrics.indexing?.status">{{ metricStatus(metrics.indexing) }}</em></header>
        <strong>{{ metricValue(metrics.indexing) }}</strong><small>页面 · 第三方估算，不等同于百度官方数据</small>
      </article>
      <article>
        <header><span>百度关键词覆盖</span><em :class="metrics.keyword_coverage?.desktop?.status">{{ metricStatus(metrics.keyword_coverage?.desktop) }}</em></header>
        <strong>{{ metricValue(metrics.keyword_coverage?.desktop) }}</strong><small>PC / 移动 {{ metricValue(metrics.keyword_coverage?.mobile) }} 个</small>
      </article>
      <article>
        <header><span>预估自然流量</span><em :class="metrics.estimated_traffic?.desktop?.status">{{ metricStatus(metrics.estimated_traffic?.desktop) }}</em></header>
        <strong>{{ metricValue(metrics.estimated_traffic?.desktop) }}</strong><small>PC 日 UV 估算 / 移动 {{ metricValue(metrics.estimated_traffic?.mobile) }}</small>
      </article>
      <article>
        <header><span>真实自然流量</span><em :class="metrics.verified_traffic?.status">{{ metricStatus(metrics.verified_traffic) }}</em></header>
        <strong>{{ metricValue(metrics.verified_traffic) }}</strong><small>{{ metrics.verified_traffic?.source || '后续接入百度统计或 Google Search Console' }}</small>
      </article>
      <article>
        <header><span>网站技术扫描</span><em :class="data.crawl?.status">{{ data.crawl?.status === 'completed' ? '已完成' : data.crawl?.status === 'partial' ? '部分完成' : data.crawl?.status === 'failed' ? '失败' : '待扫描' }}</em></header>
        <strong>{{ data.crawl?.fetched_count ?? '—' }}</strong><small>页面 · {{ data.crawl?.issue_count || 0 }} 项问题 / {{ data.crawl?.failed_count || 0 }} 项失败</small>
      </article>
    </section>

    <section class="dashboard-grid">
      <article class="trend-card">
        <header><div><h2>关键词排名趋势</h2><p>基于实际排名快照计算最近 30 天变化</p></div><button @click="router.push('/seo/rankings')">完整趋势 →</button></header>
        <div class="legend"><span><i class="top10" />Top 10 关键词</span><span><i class="top20" />Top 20 关键词</span></div>
        <div v-if="data.trend?.length" class="chart-wrap">
          <svg viewBox="0 0 760 205" preserveAspectRatio="none" aria-label="关键词排名趋势图">
            <line v-for="y in [44,87,130,174]" :key="y" x1="16" :y1="y" x2="744" :y2="y" />
            <polyline class="line top20-line" :points="chartPoints('top20')" />
            <polyline class="line top10-line" :points="chartPoints('top10')" />
          </svg>
          <div class="chart-dates"><span>{{ data.trend[0]?.date }}</span><span>{{ data.trend[data.trend.length - 1]?.date }}</span></div>
        </div>
        <div v-else class="chart-empty"><b>尚无趋势数据</b><span>导入或记录至少两次排名快照后生成趋势</span></div>
        <footer><div><span>当前 Top 10 / 20</span><b>{{ fmt(stats.top10) }} / {{ fmt(stats.top20) }}</b></div><div><span>排名覆盖</span><b>{{ fmt(stats.ranked) }} / {{ fmt(stats.keywords) }}</b></div><div><span>平均排名</span><b>{{ stats.average_position ?? '—' }}</b></div><div><span>上升 / 下降</span><b :class="{ danger: stats.falls > stats.rises }">{{ fmt(stats.rises) }} / {{ fmt(stats.falls) }}</b></div></footer>
      </article>

      <article class="priority-card">
        <header><div><h2>今日优先级</h2><p>按流量机会与风险综合排序</p></div><span>{{ tasks.length }} 项</span></header>
        <div v-if="tasks.length" class="task-list">
          <button v-for="(task, index) in tasks" :key="`${task.type}-${index}`" @click="handleTask(task)">
            <i :class="task.type">0{{ index + 1 }}</i><span><b>{{ task.count ? `${task.count} 个` : '' }}{{ task.title }}</b><small>{{ task.detail }}</small></span><em>{{ task.action }} →</em>
          </button>
        </div>
        <div v-else class="task-empty">建立关键词资产后生成今日任务</div>
      </article>
    </section>

    <el-dialog v-model="addDialog" title="添加关键词" width="620px">
      <el-form label-position="top" class="suite-form">
        <el-form-item label="关键词" class="full"><el-input v-model="form.keyword" /></el-form-item>
        <el-form-item label="词簇"><el-input v-model="form.cluster" /></el-form-item>
        <el-form-item label="搜索意图"><el-select v-model="form.intent" clearable><el-option v-for="item in ['产品','价格','方案','指南','对比','品牌']" :key="item" :label="item" :value="item" /></el-select></el-form-item>
        <el-form-item label="月搜索量"><el-input-number v-model="form.monthly_volume" :min="0" /></el-form-item>
        <el-form-item label="竞争难度"><el-input-number v-model="form.difficulty" :min="0" :max="100" /></el-form-item>
        <el-form-item label="优先级"><el-select v-model="form.priority"><el-option v-for="item in ['P0','P1','P2','P3']" :key="item" :label="item" :value="item" /></el-select></el-form-item>
        <el-form-item label="承接页面" class="full"><el-input v-model="form.landing_page" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="addDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveKeyword">保存</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.dashboard{min-height:100%;padding:22px 26px 32px;background:#f5f7fb;color:#1c2940}.command-bar{display:flex;align-items:center;justify-content:space-between;gap:20px;margin:-22px -26px 20px;padding:14px 26px;border-bottom:1px solid #e5e9f0;background:#fff}.command-bar h1{margin:0;font-size:20px}.command-bar p{margin:3px 0 0;color:#7b8799;font-size:11px}.command-actions{display:flex;align-items:center;gap:9px}.command-actions .el-input{width:230px}.command-actions .site-select{width:190px}.command-actions .site-select small{float:right;color:#9aa3b1}.command-actions button{height:36px;padding:0 14px;border:1px solid #dce3ee;border-radius:8px;background:#fff;color:#28364e;font-weight:700;cursor:pointer}.command-actions button:disabled{cursor:not-allowed;opacity:.45}.command-actions button.primary{border-color:#2864e8;background:#2864e8;color:#fff}.freshness{height:36px;padding:0 11px;border:1px solid #dce3ee;border-radius:8px;display:flex;align-items:center;gap:7px;color:#68768b;font-size:11px;white-space:nowrap}.freshness i{width:7px;height:7px;border-radius:50%;background:#16a566}.today-card{min-height:112px;padding:23px 27px;border:1px solid #dfe5ee;border-radius:13px;display:flex;align-items:center;justify-content:space-between;gap:24px;background:#fff}.today-card h2{margin:0 0 7px;font-size:24px}.today-card p{margin:0;color:#778397;font-size:12px}.flow{display:flex;align-items:center;gap:9px}.flow span{padding:8px 11px;border-radius:7px;background:#f1f5fb;color:#526078;font-size:11px;font-weight:700}.flow b{color:#b5bfce}.collector{min-height:50px;margin:14px 0; padding:0 17px;border:1px solid #dfe5ee;border-radius:10px;display:flex;align-items:center;gap:18px;background:#fff}.collector>strong{font-size:11px;color:#68768a;white-space:nowrap}.collector-item{display:flex;align-items:center;gap:5px;font-size:10.5px}.collector-item i{width:6px;height:6px;border-radius:50%}.collector-item span{color:#758196}.collector-item em{padding:2px 5px;border-radius:4px;background:#f3f4f7;color:#929baa;font-size:8px;font-style:normal}.collector-item em.ready{background:#e8f7ef;color:#138b58}.collector-item em.partial{background:#fff4df;color:#ac7020}.collector>small{margin-left:auto;color:#9aa3b1;font-size:9px}.engine-tabs{display:flex;gap:4px;margin-bottom:10px}.engine-tabs button{padding:6px 12px;border:1px solid transparent;border-radius:7px;background:transparent;color:#758196;font-size:11px;cursor:pointer}.engine-tabs button.active{border-color:#dbe4f5;background:#fff;color:#2563eb;font-weight:800}.metric-row{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:15px}.metric-row article{position:relative;padding:18px 20px;border:1px solid #dfe5ee;border-radius:11px;background:#fff;overflow:hidden}.metric-row article:before{content:"";position:absolute;inset:0 auto 0 0;width:3px;background:#2864e8}.metric-row article.teal:before{background:#0ea5a1}.metric-row article.coral:before{background:#ef6b55}.metric-row article.green:before{background:#79aa38}.metric-row span,.metric-row small{display:block;color:#778397;font-size:11px}.metric-row strong{display:block;margin:8px 0 4px;font-size:30px}.metric-row small b{color:#2864e8}.metric-row .teal small b{color:#0a9b8f}.metric-row .coral small b{color:#e35a46}.metric-row .green small b{color:#679b2d}.site-metric-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin-bottom:15px}.site-metric-grid article{padding:16px 18px;border:1px solid #dfe5ee;border-radius:11px;background:#fff}.site-metric-grid header{display:flex;justify-content:space-between;gap:8px;color:#647186;font-size:11px}.site-metric-grid em{padding:2px 6px;border-radius:999px;background:#f2f4f7;color:#8b95a4;font-size:9px;font-style:normal}.site-metric-grid em.available,.site-metric-grid em.completed{background:#e8f7ef;color:#138b58}.site-metric-grid em.stale,.site-metric-grid em.failed{background:#fff0ee;color:#d85145}.site-metric-grid em.partial{background:#fff4df;color:#ac7020}.site-metric-grid strong{display:block;margin:10px 0 5px;font-size:25px}.site-metric-grid small{color:#8a94a4;font-size:9.5px}.dashboard-grid{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(330px,.78fr);gap:15px}.trend-card,.priority-card{border:1px solid #dfe5ee;border-radius:12px;background:#fff;overflow:hidden}.trend-card header,.priority-card header{padding:18px 20px;border-bottom:1px solid #e9edf3;display:flex;justify-content:space-between;align-items:flex-start}.trend-card h2,.priority-card h2{margin:0 0 5px;font-size:16px}.trend-card p,.priority-card p{margin:0;color:#8791a1;font-size:10.5px}.trend-card header button{border:0;background:none;color:#2864e8;font-weight:700;cursor:pointer}.priority-card header>span{padding:4px 9px;border-radius:999px;background:#fff0ee;color:#ef5d50;font-size:10px;font-weight:800}.legend{display:flex;gap:18px;padding:14px 20px;color:#758196;font-size:10px}.legend i{display:inline-block;width:14px;height:2px;margin-right:6px;vertical-align:middle}.legend .top10{background:#2864e8}.legend .top20{background:#0ea5a1}.chart-wrap{height:215px;padding:0 18px}.chart-wrap svg{width:100%;height:185px}.chart-wrap line{stroke:#edf0f5;stroke-width:1}.chart-wrap .line{fill:none;stroke-width:3;stroke-linecap:round;stroke-linejoin:round}.top10-line{stroke:#2864e8}.top20-line{stroke:#0ea5a1}.chart-dates{display:flex;justify-content:space-between;color:#a0a8b5;font-size:9px}.chart-empty{height:215px;display:grid;place-content:center;text-align:center;color:#7b8799}.chart-empty b,.chart-empty span{display:block}.chart-empty span{margin-top:7px;font-size:10px}.trend-card footer{display:grid;grid-template-columns:repeat(4,1fr);border-top:1px solid #e9edf3}.trend-card footer div{padding:13px 17px;border-right:1px solid #e9edf3}.trend-card footer div:last-child{border:0}.trend-card footer span,.trend-card footer b{display:block}.trend-card footer span{color:#8a94a4;font-size:9px}.trend-card footer b{margin-top:4px;font-size:13px}.trend-card footer .danger{color:#e55449}.task-list button{width:100%;min-height:76px;padding:14px 18px;border:0;border-bottom:1px solid #edf0f4;display:grid;grid-template-columns:35px 1fr auto;align-items:center;gap:12px;background:#fff;text-align:left;cursor:pointer}.task-list button:hover{background:#f9fbff}.task-list i{width:31px;height:31px;border-radius:8px;display:grid;place-items:center;background:#edf3ff;color:#2864e8;font-style:normal;font-weight:800}.task-list i.content{background:#fff0ec;color:#e76551}.task-list i.site{background:#e9f8f5;color:#159b8b}.task-list i.healthy{background:#ebf8ef;color:#2a9a58}.task-list b,.task-list small{display:block}.task-list b{font-size:12px}.task-list small{margin-top:4px;color:#8a94a4;font-size:9.5px}.task-list em{color:#2864e8;font-size:10px;font-style:normal;font-weight:700}.task-empty{padding:70px 20px;text-align:center;color:#8a94a4}.suite-form{display:grid;grid-template-columns:1fr 1fr;gap:0 14px}.suite-form .full{grid-column:1/-1}.suite-form :is(.el-select,.el-input-number){width:100%}@media(max-width:1180px){.command-bar{align-items:flex-start}.command-actions{flex-wrap:wrap;justify-content:flex-end}.flow{display:none}.collector{flex-wrap:wrap;padding:12px 17px}.collector>small{width:100%;margin:0}.dashboard-grid{grid-template-columns:1fr}.metric-row,.site-metric-grid{grid-template-columns:repeat(2,1fr)}}
</style>
