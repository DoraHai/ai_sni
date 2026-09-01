<script setup>
/**
 * 官网结构优化 — 对齐 structure.html。
 * 数据来自品牌信息 + /api/v1/geo/structure-scan，不填原型假数。
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createGeoActionTicket, fetchLatestGeoStructureScan, runGeoStructureScan } from '../../api/geo'
import { listGeoBusinesses } from '../../api/geoContent'
import GeoWorkbenchPage from '../../components/GeoWorkbenchPage.vue'
import { useGeoTenant } from '../../composables/useGeoTenant'

const router = useRouter()
const { tenantId } = useGeoTenant()

const loading = ref(false)
const scanning = ref(false)
const scanPct = ref(8)
const scanMsg = ref('连接官网…')
const error = ref('')
const businesses = ref([])
const report = ref(null)
const typeFilter = ref('全部')
const statusFilter = ref('全部')
const scoreHow = ref(false)
const drawer = ref(null)
const showCode = ref(false)
const showFields = ref(false)
const settingsOpen = ref(false)
const pageCard = ref(null)
const drawerOpen = computed({
  get: () => !!drawer.value,
  set: (open) => {
    if (!open) drawer.value = null
  },
})

const TYPE_FILTERS = ['全部', '产品', '服务', '文章', 'FAQ', '品牌页面']
const STATUS_FILTERS = ['全部', '正常', '可增强', '缺失', '错误', '冲突']

const website = computed(() => {
  for (const b of businesses.value) {
    const p = b?.profile || b || {}
    const url = p.website || p.website_url || p.official_url || ''
    if (url) return String(url)
  }
  return report.value?.website || ''
})

const pages = computed(() => report.value?.pages || [])
const assessmentUnavailable = computed(
  () => report.value?.assessment_status === 'insufficient_sample'
    || (pages.value.length > 0 && pages.value.every((page) => page.status === '错误')),
)
const successfulPageCount = computed(() => {
  if (!report.value) return null
  if (Number.isFinite(report.value.successful_page_count)) return report.value.successful_page_count
  return pages.value.filter((page) => page.status !== '错误').length
})
const failedPageCount = computed(() => {
  if (!report.value) return null
  if (Number.isFinite(report.value.failed_page_count)) return report.value.failed_page_count
  return pages.value.filter((page) => page.status === '错误').length
})
const filteredPages = computed(() =>
  pages.value.filter((p) => {
    if (typeFilter.value !== '全部' && p.type !== typeFilter.value) return false
    if (statusFilter.value !== '全部' && p.status !== statusFilter.value) return false
    return true
  }),
)

function fmtTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function jsonldText(obj) {
  const open = '<' + 'script type="application/ld+json">'
  return `${open}\n${JSON.stringify(obj || {}, null, 2)}\n</` + 'script>'
}

function badgeClass(status) {
  if (status === '正常' || status === '已建立') return 'green'
  if (status === '缺失' || status === '错误') return 'red'
  if (status === '冲突') return 'conflict'
  return 'amber'
}

function barClass(tone) {
  if (tone === '覆盖较好' || tone === 'green') return 'green'
  if (tone === '明显缺口' || tone === 'red') return 'red'
  return 'amber'
}

async function loadBrand() {
  if (!tenantId.value) {
    businesses.value = []
    error.value = '请先选择客户或配置本地 API Key'
    return
  }
  const res = await listGeoBusinesses(tenantId.value, { status: 'active' })
  businesses.value = res?.items || res || []
}

async function loadReport() {
  if (!tenantId.value) {
    report.value = null
    return
  }
  const res = await fetchLatestGeoStructureScan(tenantId.value)
  report.value = res?.report || null
}

async function load() {
  if (!tenantId.value) {
    businesses.value = []
    report.value = null
    error.value = '请先选择客户或配置本地 API Key'
    return
  }
  loading.value = true
  error.value = ''
  try {
    await loadBrand()
  } catch (e) {
    businesses.value = []
    error.value = e.message || '加载失败'
  }
  try {
    await loadReport()
  } catch {
    report.value = null
  } finally {
    loading.value = false
  }
}

let scanTimer = 0
function startScanUi() {
  const site = website.value
  const steps = [
    `连接 ${site}…`,
    '读取页面与已有结构化数据…',
    '识别品牌、产品、FAQ 实体…',
    '生成可实施的修改建议…',
  ]
  scanPct.value = 8
  scanMsg.value = steps[0]
  let i = 0
  clearInterval(scanTimer)
  scanTimer = window.setInterval(() => {
    i += 1
    scanPct.value = Math.min(90, 8 + i * 18)
    if (steps[i]) scanMsg.value = steps[i]
  }, 700)
}

function stopScanUi() {
  clearInterval(scanTimer)
  scanTimer = 0
}

async function rescan() {
  if (!website.value) {
    ElMessage.warning('请先在品牌信息中填写品牌网站')
    return
  }
  scanning.value = true
  startScanUi()
  error.value = ''
  try {
    report.value = await runGeoStructureScan(tenantId.value, website.value)
    scanPct.value = 100
    scanMsg.value = '扫描完成'
    if (assessmentUnavailable.value) {
      ElMessage.warning(`扫描样本不足：成功解析 ${successfulPageCount.value ?? 0} 页，抓取失败 ${failedPageCount.value ?? 0} 页`)
    } else {
      ElMessage.success(
        `扫描完成：结构完整度 ${report.value?.score ?? '—'} / 100，成功解析 ${report.value?.successful_page_count ?? 0} 页`,
      )
    }
  } catch (e) {
    error.value = e.message || '扫描失败'
    ElMessage.error(error.value)
  } finally {
    stopScanUi()
    scanning.value = false
  }
}

function showSettings() {
  settingsOpen.value = true
}

function revealSuggestedJsonld(jsonld) {
  if (!jsonld || typeof jsonld !== 'object' || !Object.keys(jsonld).length) {
    ElMessage.warning('本次扫描未生成建议代码，请先重新扫描')
    return
  }
  showCode.value = true
  showFields.value = true
  ElMessage.success('已展开扫描生成的 JSON-LD')
}

function jumpToPages(type, status = '全部') {
  typeFilter.value = type || '全部'
  statusFilter.value = status
  nextTick(() => {
    pageCard.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  })
}

function openPage(page) {
  showCode.value = false
  showFields.value = false
  drawer.value = { kind: 'page', page }
}

function openRel(card) {
  showCode.value = false
  showFields.value = false
  drawer.value = { kind: 'rel', card }
}

function openIssue(issue) {
  if (issue.open_id) {
    const page = pages.value.find((p) => p.id === issue.open_id)
    if (page) {
      openPage(page)
      return
    }
  }
  jumpToPages(issue.filter || '全部')
}

async function copyJson(obj) {
  const text = jsonldText(obj)
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('JSON-LD 已复制')
  } catch {
    ElMessage.error('复制失败')
  }
}

async function createTask(page) {
  try {
    await createGeoActionTicket(tenantId.value, {
      title: `${page.suggest || '结构优化'} · ${page.name}`,
      action: page.problem,
      priority: page.pri === 'P1' ? 'high' : 'medium',
      audit_id: report.value?.audit_id || null,
      acceptance_type: 'manual',
      acceptance_desc: `页面 ${page.url} 补齐 ${page.suggest || '结构化数据'}`,
    })
    ElMessage.success('已创建开发任务，可到验收工单查看')
    router.push('/geo/tickets')
  } catch (e) {
    ElMessage.error(e.message || '创建工单失败')
  }
}

watch(tenantId, load)
onMounted(load)
</script>

<template>
  <GeoWorkbenchPage
    title="官网结构优化"
    :show-period="false"
    sub="让机器更清楚地识别品牌、产品、服务和问答实体，并生成可交给开发实施的修改建议"
    :loading="loading"
  >
    <template #actions>
      <router-link class="gd-btn" to="/geo/brand">品牌信息</router-link>
      <button class="gd-btn" type="button" @click="load">刷新</button>
    </template>

    <div class="geo-dash structure-page">
      <el-alert v-if="error" type="error" :title="error" show-icon class="mb" />

      <section class="st-intro gd-card">
        <div class="st-intro-copy">
          <span class="st-kicker">AI-READABLE WEBSITE</span>
          <h2>让官网不只是“给人看”，也让 AI 更容易读懂。</h2>
          <p>扫描品牌、产品、FAQ 等实体，检查 Schema / JSON-LD 是否完整，并生成可交给开发实施的代码建议。</p>
          <div class="st-principles">
            <span>实体识别</span>
            <span>Schema.org</span>
            <span>JSON-LD</span>
            <span>代码建议</span>
          </div>
        </div>
        <div class="st-flow" aria-label="官网结构优化工作流">
          <div class="st-flow-step"><span class="st-flow-no">1</span><b>扫描结构</b><small>页面与已有标注</small></div>
          <div class="st-flow-step"><span class="st-flow-no">2</span><b>找缺失</b><small>品牌、产品、FAQ</small></div>
          <div class="st-flow-step"><span class="st-flow-no">3</span><b>给建议</b><small>Schema 代码</small></div>
          <div class="st-flow-step"><span class="st-flow-no">4</span><b>验证结果</b><small>复扫检查上线</small></div>
        </div>
      </section>

      <section class="gd-card st-summary">
        <div class="st-item">
          <span>官网</span>
          <b v-if="website"><a :href="website" target="_blank" rel="noopener">{{ website }}</a></b>
          <b v-else class="muted">尚未填写</b>
          <small>来自 <router-link to="/geo/brand">品牌信息</router-link></small>
        </div>
        <div class="st-item">
          <span>最近扫描</span>
          <b>{{ report ? fmtTime(report.scanned_at) : '—' }}</b>
        </div>
        <div class="st-item">
          <span>尝试页面</span>
          <b>{{ report ? report.page_count : '—' }}</b>
          <small v-if="report?.discovered">sitemap 发现 {{ report.discovered }}</small>
        </div>
        <div class="st-item">
          <span>成功解析</span>
          <b>{{ successfulPageCount ?? '—' }}</b>
        </div>
        <div class="st-item">
          <span>抓取失败</span>
          <b :class="{ 'st-count-warn': failedPageCount }">{{ failedPageCount ?? '—' }}</b>
        </div>
        <div class="st-item">
          <span>含 JSON-LD 页面</span>
          <b>{{ report ? report.structured_count : '—' }}</b>
        </div>
        <div class="st-ops">
          <button class="gd-btn" type="button" :disabled="scanning" @click="rescan">重新扫描</button>
          <button class="gd-btn" type="button" @click="showSettings">扫描设置</button>
        </div>
      </section>

      <section class="gd-card st-health-card">
        <div class="gd-hd">
          <h3>AI 可解析结构</h3>
          <div class="st-how">
            <span v-if="report" class="st-badge" :class="badgeClass(report.score_badge)">{{ assessmentUnavailable ? '无法评估' : report.score_badge }}</span>
            <span v-else class="st-badge amber">尚未扫描</span>
            <button type="button" class="st-how-btn" @click.stop="scoreHow = !scoreHow">评分怎么算？</button>
            <div v-if="scoreHow" class="st-pop" @click.stop>
              <p>这是产品内部的「机器可解析结构完整度」评分，用于衡量官网是否把品牌、产品、服务和内容关系表达清楚。不是 Google、Schema.org 或任何 AI 平台的官方评分。</p>
              <div v-for="d in (report?.score_dims || [])" :key="d.label" class="dim">
                <span>{{ d.label }}</span><b>{{ d.value }}</b>
              </div>
              <p v-if="!report" class="dim-empty">扫描完成后这里会显示四个维度的真实得分。</p>
              <small>四个维度加权后得到综合评分。主界面不展示计算公式。</small>
            </div>
          </div>
        </div>
        <template v-if="report && !assessmentUnavailable">
          <div class="st-health">
            <div class="st-health-score">
              <div class="subtle">综合评分</div>
              <div class="num">{{ report.score }}<span>/ 100</span></div>
            </div>
            <div class="st-callouts">
              <button
                v-for="c in report.callouts"
                :key="c.name"
                type="button"
                class="st-callout"
                @click="jumpToPages(c.filter)"
              >
                <em>{{ c.tone }}</em>
                <div class="row"><span>{{ c.name }}</span><b>{{ c.pct == null ? '—' : `${c.pct}%` }}</b></div>
                <div class="bar" :class="barClass(c.tone)">
                  <span :style="{ width: `${c.pct || 0}%` }" />
                </div>
              </button>
            </div>
          </div>
          <div class="st-insight">{{ report.insight }}</div>
        </template>
        <div v-else-if="report" class="st-unavailable">
          <h4>无法完成结构评估</h4>
          <p>本次尝试 {{ report.page_count }} 个 URL，成功解析 {{ successfulPageCount ?? '—' }} 页、抓取失败 {{ failedPageCount ?? '—' }} 页；因此不展示结构评分或缺口结论。</p>
          <p class="subtle">请确认官网可从服务端访问、首页返回 HTML，再重新扫描。</p>
          <button class="gd-btn primary" type="button" :disabled="scanning" @click="rescan">重新扫描</button>
        </div>
        <div v-else class="gd-bd">
          <el-empty
            :description="website
              ? '已读取官网地址。点「重新扫描」会按 sitemap 抽样页面并识别 JSON-LD。'
              : '请先在品牌信息中填写官网，再回来启动结构扫描。'"
          >
            <button v-if="website" class="gd-btn primary" type="button" @click="rescan">开始扫描</button>
            <router-link v-else class="gd-btn primary" to="/geo/brand">去填写品牌信息</router-link>
          </el-empty>
        </div>
      </section>

      <section v-if="report && !assessmentUnavailable" class="gd-card">
        <div class="gd-hd">
          <h3>当前官网已经建立哪些结构化信息？</h3>
          <span class="more">业务名称 + Schema.org 类型</span>
        </div>
        <div class="st-cover">
          <button
            v-for="item in report.coverage"
            :key="item.key"
            type="button"
            class="st-cover-item"
            @click="jumpToPages(item.filter)"
          >
            <span class="subtle">{{ item.label }}</span>
            <small>{{ item.schema }}</small>
            <b>{{ item.value }}</b>
            <span class="st-badge" :class="item.tone">{{ item.status }}</span>
          </button>
        </div>
      </section>

      <section v-if="report && !assessmentUnavailable" class="gd-card">
        <div class="gd-hd">
          <h3>最值得先处理的问题</h3>
          <span class="more">按对机器理解核心业务内容的影响排序</span>
        </div>
        <div class="st-issue-list">
          <div v-if="!report.issues?.length" class="st-empty">这次抽样没有高优先级结构缺口。</div>
          <div v-for="issue in report.issues" :key="issue.title" class="st-issue">
            <span class="st-pri" :class="issue.pri === 'P1' ? 'p1' : 'p2'">{{ issue.pri }}</span>
            <div>
              <h4>{{ issue.title }}</h4>
              <p>{{ issue.detail }}</p>
              <div class="st-pages">
                <code v-for="path in issue.paths || []" :key="path">{{ path }}</code>
                <span v-if="issue.extra">+{{ issue.extra }}</span>
              </div>
            </div>
            <button class="gd-btn" type="button" @click="openIssue(issue)">查看涉及页面</button>
          </div>
        </div>
      </section>

      <section v-if="report && !assessmentUnavailable" ref="pageCard" class="gd-card">
        <div class="gd-hd"><h3>哪些页面需要优化？</h3></div>
        <div class="st-filters">
          <div class="row">
            <button
              v-for="t in TYPE_FILTERS"
              :key="t"
              type="button"
              class="st-tag"
              :class="{ on: typeFilter === t }"
              @click="typeFilter = t"
            >{{ t }}</button>
          </div>
          <div class="row">
            <button
              v-for="s in STATUS_FILTERS"
              :key="s"
              type="button"
              class="st-tag"
              :class="{ on: statusFilter === (s === '全部' ? '全部' : s) }"
              @click="statusFilter = s === '全部' ? '全部' : s"
            >{{ s === '全部' ? '全部状态' : s }}</button>
          </div>
        </div>
        <table class="st-table">
          <thead>
            <tr>
              <th>页面</th><th>页面类型</th><th>当前结构</th><th>结构状态</th><th>主要问题</th><th>优先级</th><th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!filteredPages.length">
              <td colspan="7" class="st-empty">没有符合筛选的页面</td>
            </tr>
            <tr v-for="p in filteredPages" :key="p.id">
              <td>
                <b>{{ p.name }}</b>
                <div class="subtle">{{ p.url }}</div>
              </td>
              <td>{{ p.type }}</td>
              <td class="muted">{{ p.schema }}</td>
              <td><span class="st-badge" :class="badgeClass(p.status)">{{ p.status }}</span></td>
              <td>{{ p.issue }}</td>
              <td>{{ p.pri }}</td>
              <td><button type="button" class="st-link" @click="openPage(p)">查看</button></td>
            </tr>
          </tbody>
        </table>
      </section>

      <section v-if="report && !assessmentUnavailable" class="gd-card">
        <div class="gd-hd">
          <h3>官网内容关系完整度</h3>
          <span class="more">检查官网是否已经清晰表达品牌、产品、官方渠道、文章和作者之间的重要关系</span>
        </div>
        <div class="st-rel-summary">
          <div>
            <div class="subtle">完整度</div>
            <div class="pct">{{ report.relations?.completeness ?? '—' }}<span>%</span></div>
          </div>
          <div>
            <span class="st-badge amber">{{ report.relations?.badge }}</span>
            <p>{{ report.relations?.summary }}</p>
          </div>
        </div>
        <div class="st-rel-grid">
          <button
            v-for="card in report.relations?.cards || []"
            :key="card.id"
            type="button"
            class="st-rel-card"
            @click="openRel(card)"
          >
            <div class="row"><h4>{{ card.title }}</h4><span class="st-badge" :class="card.tone">{{ card.status }}</span></div>
            <div class="st-rel-expr"><b>{{ card.expr_left }}</b> <em>→</em> <b>{{ card.expr_right }}</b></div>
            <p>{{ card.detail }}</p>
            <small>技术说明：{{ card.tech }}</small>
            <span class="gd-btn">{{ card.cta }}</span>
          </button>
        </div>
      </section>

      <div class="st-scope">
        <b>使用边界：</b>
        <span>结构化数据可以为搜索引擎和机器系统提供更明确的实体、属性和关系表达，是提升官网机器可解析性的重要基础。AI 是否最终提及、推荐或引用品牌，还会受到内容质量、权威性、第三方信源、页面可访问性和信息时效性等因素影响。本页评分不是 Google、Schema.org 或任何 AI 平台的官方评分，也不承诺添加 JSON-LD 一定提升 AI 排名或保证被引用。</span>
      </div>
    </div>

    <div v-if="scanning" class="st-scan">
      <div class="box">
        <b>正在扫描官网结构</b>
        <p class="subtle">识别页面、已有结构化数据与可补充的实体关系</p>
        <div class="bar"><i :style="{ width: `${scanPct}%` }" /></div>
        <div class="subtle">{{ scanMsg }}</div>
      </div>
    </div>

    <el-drawer
      v-model="drawerOpen"
      :with-header="false"
      size="520px"
      destroy-on-close
    >
      <template v-if="drawer?.kind === 'page'">
        <header class="st-drawer-head">
          <div>
            <h2>{{ drawer.page.name }}</h2>
            <p>{{ drawer.page.url }}</p>
          </div>
          <button type="button" class="st-x" @click="drawer = null">×</button>
        </header>
        <div class="st-drawer-body">
          <div class="st-kv">
            <div><span>页面类型</span><b>{{ drawer.page.type }}</b></div>
            <div><span>状态</span><b><span class="st-badge" :class="badgeClass(drawer.page.status)">{{ drawer.page.status }}</span></b></div>
            <div><span>优先级</span><b>{{ drawer.page.pri }}</b></div>
          </div>
          <section class="st-drawer-sec">
            <h4>当前识别内容</h4>
            <div class="st-kv">
              <div v-for="row in drawer.page.detected" :key="row[0]"><span>{{ row[0] }}</span><b>{{ row[1] }}</b></div>
            </div>
          </section>
          <section class="st-drawer-sec">
            <h4>当前结构化数据</h4>
            <div class="st-struct">
              <span v-for="row in drawer.page.structures" :key="row[0]" class="st-badge" :class="row[1] ? 'green' : 'red'">
                {{ row[0] }} {{ row[1] ? '✓' : '×' }}
              </span>
            </div>
          </section>
          <section class="st-drawer-sec">
            <h4>发现的问题</h4>
            <p>{{ drawer.page.problem }}</p>
          </section>
          <section class="st-drawer-sec">
            <h4>建议结构</h4>
            <span class="st-badge blue">{{ drawer.page.suggest }}</span>
          </section>
          <section class="st-drawer-sec">
            <h4>预计改善</h4>
            <div class="st-improves"><span v-for="x in drawer.page.improves" :key="x" class="st-tag">{{ x }}</span></div>
          </section>
          <div v-if="showCode" class="st-code">
            <div class="st-code-bar">
              <button class="gd-btn" type="button" @click="copyJson(drawer.page.jsonld)">复制 JSON-LD</button>
            </div>
            <pre>{{ jsonldText(drawer.page.jsonld) }}</pre>
          </div>
          <section v-if="showFields" class="st-drawer-sec">
            <h4>字段来源</h4>
            <div class="st-fields">
              <div v-for="f in drawer.page.fields" :key="f.key" class="st-field">
                <b>{{ f.key }}</b>
                <div>{{ f.value }}<small>来源：{{ f.source }}</small></div>
              </div>
            </div>
          </section>
        </div>
        <footer class="st-drawer-foot">
          <button class="gd-btn" type="button" @click="showCode = true">查看建议代码</button>
          <button class="gd-btn" type="button" @click="revealSuggestedJsonld(drawer.page.jsonld)">AI 生成 JSON-LD</button>
          <button class="gd-btn primary" type="button" @click="createTask(drawer.page)">创建开发任务</button>
        </footer>
      </template>
      <template v-else-if="drawer?.kind === 'rel'">
        <header class="st-drawer-head">
          <div>
            <h2>{{ drawer.card.title }}</h2>
            <p>{{ drawer.card.sub }}</p>
          </div>
          <button type="button" class="st-x" @click="drawer = null">×</button>
        </header>
        <div class="st-drawer-body">
          <div class="st-kv">
            <div><span>状态</span><b><span class="st-badge" :class="drawer.card.tone">{{ drawer.card.status }}</span></b></div>
          </div>
          <section class="st-drawer-sec">
            <h4>业务判断</h4>
            <p>{{ drawer.card.detail }}</p>
          </section>
          <section v-if="drawer.card.uncovered?.length" class="st-drawer-sec">
            <h4>未覆盖示例</h4>
            <p>{{ drawer.card.uncovered.join('\n') }}</p>
          </section>
          <div v-if="showCode" class="st-code">
            <div class="st-code-bar">
              <button class="gd-btn" type="button" @click="copyJson(drawer.card.jsonld)">复制 JSON-LD</button>
            </div>
            <pre>{{ jsonldText(drawer.card.jsonld) }}</pre>
          </div>
          <section v-if="showFields" class="st-drawer-sec">
            <h4>字段来源</h4>
            <div class="st-fields">
              <div v-for="f in drawer.card.fields || []" :key="f.key" class="st-field">
                <b>{{ f.key }}</b>
                <div>{{ f.value }}<small>来源：{{ f.source }}</small></div>
              </div>
            </div>
          </section>
        </div>
        <footer class="st-drawer-foot">
          <button class="gd-btn" type="button" @click="showCode = true">查看建议代码</button>
          <button class="gd-btn primary" type="button" @click="revealSuggestedJsonld(drawer.card.jsonld)">AI 生成 JSON-LD</button>
        </footer>
      </template>
    </el-drawer>
    <el-dialog v-model="settingsOpen" title="扫描设置" width="480px">
      <el-form label-width="108px">
        <el-form-item label="扫描地址">
          <el-input :model-value="website" disabled placeholder="请先到品牌信息填写官网" />
        </el-form-item>
        <el-form-item label="抽样范围">
          <span class="muted">按 sitemap 最多 24 页，识别 JSON-LD / Schema</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="router.push('/geo/brand')">去品牌信息</el-button>
        <el-button type="primary" :disabled="!website" @click="settingsOpen = false; rescan()">按当前设置扫描</el-button>
      </template>
    </el-dialog>
  </GeoWorkbenchPage>
</template>

<style scoped>
.mb { margin-bottom: 12px; }
.muted { color: var(--el-text-color-secondary); font-weight: 500; }
.subtle { color: #8a93a3; font-size: 11px; }
.st-intro {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(280px, 1fr);
  min-height: 138px;
  overflow: hidden;
  margin-bottom: 16px;
  background: linear-gradient(135deg, #1e293b 0%, #334155 100%);
  color: #f8fafc;
}
.st-intro-copy { padding: 22px 24px; }
.st-kicker { display: block; margin-bottom: 6px; color: rgba(248,250,252,.55); font-size: 11px; letter-spacing: .06em; }
.st-intro h2 { margin: 6px 0; font-size: 20px; line-height: 1.35; }
.st-intro p { margin: 0; max-width: 640px; color: rgba(248,250,252,.78); font-size: 13px; line-height: 1.65; }
.st-principles { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.st-principles span {
  padding: 4px 10px; border: 1px solid rgba(255,255,255,.18); border-radius: 999px; font-size: 11px;
}
.st-flow {
  display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0; align-content: center;
  padding: 18px 18px 18px 8px; border-left: 1px solid rgba(255,255,255,.1);
}
.st-flow-step { position: relative; padding: 8px 10px; }
.st-flow-no {
  width: 22px; height: 22px; display: grid; place-items: center; margin-bottom: 8px;
  border-radius: 6px; background: rgba(255,255,255,.12); font-size: 11px; font-weight: 700;
}
.st-flow-step b { display: block; margin-bottom: 4px; font-size: 13px; }
.st-flow-step small { color: rgba(248,250,252,.6); font-size: 11px; }
.st-summary { display: flex; align-items: center; flex-wrap: wrap; gap: 22px; padding: 14px 18px; margin-bottom: 16px; }
.st-item { display: grid; gap: 2px; min-width: 0; }
.st-item span { color: var(--el-text-color-secondary); font-size: 11px; }
.st-item b { font-size: 13px; font-weight: 700; }
.st-count-warn { color: #c2410c; }
.st-item a { color: var(--el-color-primary); }
.st-item small { color: var(--el-text-color-secondary); font-size: 11px; }
.st-ops { margin-left: auto; display: flex; gap: 8px; }
.st-health-card { margin-bottom: 16px; }
.st-unavailable { padding: 28px 20px; }
.st-unavailable h4 { margin: 0 0 8px; color: #9a3412; font-size: 16px; }
.st-unavailable p { max-width: 660px; margin: 0 0 8px; color: #68717d; font-size: 13px; line-height: 1.7; }
.st-unavailable .gd-btn { margin-top: 8px; }
.st-how { position: relative; margin-left: auto; display: flex; align-items: center; gap: 10px; }
.st-how-btn { border: 0; background: none; color: var(--el-color-primary); font: inherit; font-size: 12px; font-weight: 650; cursor: pointer; }
.st-pop {
  position: absolute; top: 28px; right: 0; z-index: 30; width: min(380px, 82vw);
  padding: 14px 15px; color: #3c4658; text-align: left; border: 1px solid #e7eaee;
  border-radius: 10px; background: #fff; box-shadow: 0 12px 32px rgba(16,24,40,.12);
}
.st-pop p { margin: 0 0 10px; font-size: 12px; line-height: 1.65; }
.st-pop .dim { display: flex; justify-content: space-between; gap: 12px; padding: 6px 0; border-top: 1px solid #edf0f5; font-size: 12px; }
.st-pop .dim:first-of-type { border-top: 0; }
.st-pop small { display: block; margin-top: 8px; color: #8a93a3; font-size: 11px; line-height: 1.6; }
.st-health { display: grid; grid-template-columns: 220px minmax(0, 1fr); }
.st-health-score { padding: 22px 20px; border-right: 1px solid #eef0f4; }
.st-health-score .num { font-size: 36px; font-weight: 800; letter-spacing: -.03em; line-height: 1.1; }
.st-health-score .num span { margin-left: 4px; color: #8a93a3; font-size: 16px; font-weight: 700; }
.st-callouts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); }
.st-callout {
  display: block; padding: 18px 16px; border-right: 1px solid #eef0f4; border: 0; border-right: 1px solid #eef0f4;
  background: #fff; color: inherit; text-align: left; cursor: pointer;
}
.st-callout:last-child { border-right: 0; }
.st-callout:hover { background: #f8fafc; }
.st-callout em { display: block; margin-bottom: 8px; color: #8a93a3; font-size: 11px; font-style: normal; }
.st-callout .row { display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 12.5px; }
.bar { height: 6px; border-radius: 99px; background: #eef0f5; overflow: hidden; }
.bar span { display: block; height: 100%; background: #c88719; }
.bar.green span { background: #168566; }
.bar.red span { background: #dc2626; }
.st-insight { padding: 12px 18px 16px; border-top: 1px solid #eef0f4; color: #68717d; font-size: 12.5px; line-height: 1.7; }
.st-cover { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; padding: 16px 18px; }
.st-cover-item {
  display: block; padding: 12px; border: 1px solid #e7eaee; border-radius: 10px; background: #fff;
  color: inherit; min-height: 108px; text-align: left; cursor: pointer;
}
.st-cover-item:hover { border-color: var(--el-color-primary); }
.st-cover-item small { display: block; margin-top: 2px; color: #8a93a3; font-size: 11px; }
.st-cover-item b { display: block; margin: 8px 0 6px; font-size: 14px; }
.st-issue-list { padding: 4px 18px 8px; }
.st-issue { display: grid; grid-template-columns: 42px minmax(0, 1fr) auto; gap: 12px; padding: 16px 0; border-bottom: 1px solid #eef0f4; }
.st-issue:last-child { border-bottom: 0; }
.st-pri { width: 42px; height: 24px; display: grid; place-items: center; border-radius: 6px; font-size: 11px; font-weight: 800; }
.st-pri.p1 { background: #fdeaea; color: #dc2626; }
.st-pri.p2 { background: #fdf2e0; color: #c88719; }
.st-issue h4 { margin: 0 0 6px; font-size: 13.5px; }
.st-issue p { margin: 0 0 8px; color: #68717d; font-size: 12.5px; line-height: 1.65; }
.st-pages { font-size: 12px; color: #4b5563; }
.st-pages code { margin-right: 6px; font-size: 11px; }
.st-filters { padding: 12px 18px 0; display: grid; gap: 10px; }
.st-filters .row { display: flex; flex-wrap: wrap; gap: 8px; }
.st-tag {
  border: 1px solid #e7eaee; background: #fff; border-radius: 999px; padding: 4px 10px;
  font-size: 12px; cursor: pointer;
}
.st-tag.on { border-color: #246bfd; color: #246bfd; background: #edf4ff; }
.st-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.st-table th, .st-table td { padding: 12px 14px; border-top: 1px solid #eef0f4; text-align: left; vertical-align: top; }
.st-table th { color: #8a93a3; font-size: 12px; font-weight: 650; }
.st-link { border: 0; background: none; color: #246bfd; cursor: pointer; font: inherit; }
.st-empty { padding: 22px; text-align: center; color: #8a93a3; }
.st-rel-summary { display: flex; align-items: flex-start; gap: 16px; padding: 14px 18px; border-bottom: 1px solid #eef0f4; }
.st-rel-summary .pct { font-size: 22px; font-weight: 800; letter-spacing: -.03em; }
.st-rel-summary .pct span { margin-left: 2px; color: #8a93a3; font-size: 12px; }
.st-rel-summary p { margin: 6px 0 0; color: #68717d; font-size: 12.5px; line-height: 1.65; }
.st-rel-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; padding: 16px 18px; }
.st-rel-card {
  display: flex; flex-direction: column; min-width: 0; padding: 14px 16px; border: 1px solid #e7eaee;
  border-radius: 10px; background: #fff; color: inherit; text-align: left; cursor: pointer;
}
.st-rel-card:hover { border-color: #246bfd; }
.st-rel-card h4 { margin: 0; font-size: 13.5px; }
.st-rel-card .row { display: flex; justify-content: space-between; gap: 8px; margin-bottom: 10px; }
.st-rel-expr { margin: 0 0 10px; font-size: 13px; line-height: 1.6; }
.st-rel-expr em { color: #8a93a3; font-style: normal; }
.st-rel-card p { margin: 8px 0 0; color: #68717d; font-size: 12.5px; line-height: 1.65; }
.st-rel-card small { display: block; margin-top: 8px; color: #9aa3ad; font-size: 11px; }
.st-rel-card .gd-btn { margin-top: 12px; align-self: flex-start; }
.st-badge { display: inline-block; padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 700; background: #fff3dc; color: #a3640d; }
.st-badge.green { background: #ecfdf5; color: #168566; }
.st-badge.red { background: #fdeaea; color: #dc2626; }
.st-badge.amber { background: #fff3dc; color: #a3640d; }
.st-badge.blue { background: #edf4ff; color: #246bfd; }
.st-badge.conflict { background: #f3e8ff; color: #6d28d9; }
.st-scope { margin-top: 16px; padding: 12px 14px; border-radius: 10px; background: #f8fafc; color: #68717d; font-size: 12.5px; line-height: 1.7; }
.st-scan {
  position: fixed; inset: 0; z-index: 13000; display: flex; align-items: center; justify-content: center;
  background: rgba(17,24,39,.45);
}
.st-scan .box { width: min(420px, 92vw); padding: 22px; border-radius: 12px; background: #fff; }
.st-scan .bar { height: 8px; margin: 14px 0 8px; border-radius: 99px; background: #eef0f5; overflow: hidden; }
.st-scan .bar i { display: block; height: 100%; background: #246bfd; transition: width .35s; }
.st-drawer-head { display: flex; justify-content: space-between; gap: 12px; padding: 8px 4px 16px; }
.st-drawer-head h2 { margin: 0; font-size: 18px; }
.st-drawer-head p { margin: 4px 0 0; color: #8a93a3; font-size: 12px; }
.st-x { border: 0; background: none; font-size: 22px; cursor: pointer; }
.st-drawer-body { padding: 0 4px 24px; }
.st-drawer-sec { margin-bottom: 16px; }
.st-drawer-sec h4 { margin: 0 0 8px; color: #7a8393; font-size: 11px; font-weight: 700; }
.st-drawer-sec p { margin: 0; white-space: pre-line; line-height: 1.7; font-size: 12.5px; }
.st-kv { display: grid; gap: 6px; font-size: 12.5px; margin-bottom: 16px; }
.st-kv div { display: flex; gap: 8px; }
.st-kv span { color: #8a93a3; width: 72px; flex: none; }
.st-struct, .st-improves { display: flex; flex-wrap: wrap; gap: 6px; }
.st-code { margin-top: 12px; border: 1px solid #e7eaee; border-radius: 10px; overflow: hidden; background: #1e2330; }
.st-code pre { margin: 0; padding: 16px; color: #e8edf5; font-size: 12px; line-height: 1.6; overflow: auto; max-height: 280px; }
.st-code-bar { display: flex; justify-content: flex-end; gap: 8px; padding: 8px 10px; background: #161a24; }
.st-fields { display: grid; gap: 8px; }
.st-field { display: grid; grid-template-columns: 88px 1fr; gap: 10px; padding: 8px 10px; border: 1px solid #e7eaee; border-radius: 8px; background: #fff; font-size: 12.5px; }
.st-field small { display: block; margin-top: 2px; color: #8a93a3; font-size: 11px; }
.st-drawer-foot { display: flex; flex-wrap: wrap; gap: 8px; padding-top: 8px; border-top: 1px solid #eef0f4; }
@media (max-width: 1100px) {
  .st-intro { grid-template-columns: 1fr; }
  .st-health, .st-cover, .st-callouts, .st-rel-grid { grid-template-columns: 1fr; }
  .st-callout, .st-health-score { border-right: 0; border-bottom: 1px solid #eef0f4; }
  .st-ops { margin-left: 0; width: 100%; }
}
@media (max-width: 720px) {
  .st-flow { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .st-issue { grid-template-columns: 42px 1fr; }
}
</style>
