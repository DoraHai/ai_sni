<script setup>
import { geoSnapshotLink } from '../../utils/geoRoutes'
import { opportunityExportRows } from '../../utils/geoSourceOpportunities'
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createGeoSourceOpportunityTask, backfillAttribution, fetchGeoCitationInsights, formatGeoError } from '../../api/geoContent'
import GeoEmptyState from '../../components/GeoEmptyState.vue'
import GeoWorkbenchPage from '../../components/GeoWorkbenchPage.vue'
import { useClientPager } from '../../composables/useClientPager'
import { useObservationPeriod } from '../../composables/useObservationPeriod'
import { session } from '../../store/session'
import {
  CITATION_ACCURACY_LABEL,
  CITATION_FORMAT_LABEL,
  REPORT_GLOSSARY,
  countsToRows,
  downloadCsv,
  engineDisplay,
  fmtInt,
  fmtPct,
} from '../../utils/geoReportLabels'
import { citationHeatFromItems, heatTone } from '../../utils/geoSnapshotSummary'
import { getGeoPrototypePageSurface } from '../../utils/geoEditorSurface'

/** 蓝图 P0/P1 渠道：用于「高价值待铺」缺口，不编造全国引用数字。 */
const HIGH_VALUE_CHANNELS = [
  { key: 'official', name: '官网', why: '事实口径来源' },
  { key: 'baike', name: '百度百科 / 搜狗百科', why: '实体消歧地基' },
  { key: 'ranking', name: '榜单/品牌库站', why: '「有哪些/哪个好」高杠杆' },
  { key: 'wechat', name: '微信公众号 / 腾讯新闻', why: '腾讯元宝常见来源' },
  { key: 'toutiao', name: '今日头条号', why: '豆包系常见来源' },
  { key: 'zhihu', name: '知乎', why: '承接哪个好/怎么选' },
  { key: 'tech', name: 'CSDN / 博客园', why: '技术 B2B 高权重' },
  { key: 'quark', name: '夸克 / 神马搜索', why: '千问常见来源' },
]
const OWN_HEAT_NAME = '本品牌官网/博客'
const ARTICLE_PREVIEW = 5

const router = useRouter()
const prototypeSurface = getGeoPrototypePageSurface()
const { days: observationDays, start: obsStart, end: obsEnd, label: obsLabel } = useObservationPeriod()
const tenantId = computed(() =>
  session.tenantId || (import.meta.env.DEV && import.meta.env.VITE_API_KEY ? 1 : null),
)

const loading = ref(false)
const backfilling = ref(false)
const error = ref('')
const data = ref(null)
let loadRequest = 0
const creatingOpportunity = ref(null)
const opportunities = computed(() => data.value?.source_opportunities?.items || [])
const ownOnly = ref(false)
const domainQuery = ref('')
const showAllArticles = ref(false)

const citeItems = computed(() => {
  let rows = data.value?.items || []
  if (ownOnly.value) rows = rows.filter((r) => r.is_own_domain)
  const q = domainQuery.value.trim().toLowerCase()
  if (q) rows = rows.filter((r) => rowMatchesQuery(r, q))
  return rows
})
const pager = useClientPager(citeItems, { pageSize: 20 })

const heatMap = computed(() => {
  const mapped = (data.value?.items || []).map((it) =>
    it.is_own_domain ? { ...it, blueprint_channel_name: OWN_HEAT_NAME } : it,
  )
  const heat = citationHeatFromItems(mapped)
  const own = heat.rows.filter((r) => r.name === OWN_HEAT_NAME)
  const rest = heat.rows.filter((r) => r.name !== OWN_HEAT_NAME)
  return { ...heat, rows: [...rest, ...own] }
})

const qualityRows = computed(() => {
  if (!data.value) return []
  return [
    ...countsToRows(data.value.format_counts, CITATION_FORMAT_LABEL, '引用格式'),
    ...countsToRows(data.value.accuracy_counts, CITATION_ACCURACY_LABEL, '引用准确性'),
  ]
})

const platformStats = computed(() => {
  const map = new Map()
  for (const it of data.value?.items || []) {
    const name = it.is_own_domain ? OWN_HEAT_NAME : (it.blueprint_channel_name || it.domain)
    const cur = map.get(name) || { name, cite_count: 0 }
    cur.cite_count += Number(it.cite_count || 0)
    map.set(name, cur)
  }
  const rows = [...map.values()].sort((a, b) => b.cite_count - a.cite_count)
  const total = rows.reduce((a, r) => a + r.cite_count, 0)
  return { rows, total }
})

const topPlatform = computed(() => platformStats.value.rows[0] || null)
const topShare = computed(() => {
  if (data.value?.rates_comparable === false) return null
  const { total } = platformStats.value
  if (!topPlatform.value || !total) return null
  return topPlatform.value.cite_count / total
})

const citedKeys = computed(() => {
  const keys = new Set()
  for (const it of data.value?.items || []) {
    if (it.blueprint_channel_key) keys.add(it.blueprint_channel_key)
    if (it.is_own_domain) keys.add('official')
  }
  return keys
})

const pendingChannels = computed(() => {
  if (!(data.value?.items || []).length) return []
  return HIGH_VALUE_CHANNELS.filter((ch) => !citedKeys.value.has(ch.key))
})

const articleRows = computed(() =>
  [...citeItems.value]
    .sort((a, b) => Number(b.cite_count || 0) - Number(a.cite_count || 0))
    .map((row) => ({
      ...row,
      title: articleLabel(row),
      url: (row.sample_urls || [])[0] || '',
      source: row.is_own_domain
        ? '官网'
        : (row.blueprint_channel_name || row.domain || '—'),
      owner: row.is_own_domain ? '本品牌' : '第三方',
    })),
)

const visibleArticles = computed(() =>
  showAllArticles.value ? articleRows.value : articleRows.value.slice(0, ARTICLE_PREVIEW),
)

const layoutAdvice = computed(() => ({
  rows: opportunities.value.slice(0, 5).map((item) => ({
    tone: item.priority === '优先核对' ? 'amber' : 'green',
    tag: item.priority,
    text: item.question,
    extra: item.reason,
  })),
  conclusion: opportunities.value.length
    ? '先核验引用与品牌事实，再补充内容并复测；展开上方机会可查看逐条证据。'
    : '当前没有可用机会结论，请检查样本量、采样方法和判读状态。',
}))

function rowMatchesQuery(row, q) {
  const hay = [
    row.domain,
    row.blueprint_channel_name,
    row.blueprint_channel_key,
    row.sample_prompt_question,
    ...(row.sample_urls || []),
  ]
    .join(' ')
    .toLowerCase()
  return hay.includes(q)
}

function articleLabel(row) {
  const url = (row.sample_urls || [])[0]
  if (url) {
    try {
      const u = new URL(url)
      const path = decodeURIComponent(u.pathname || '').replace(/\/+$/, '')
      const parts = path.split('/').filter(Boolean)
      const last = parts[parts.length - 1] || ''
      if (last && !/^\d+$/.test(last) && last.length > 2) {
        return last.replace(/[-_]+/g, ' ')
      }
      return u.hostname.replace(/^www\./, '') + (path || '')
    } catch {
      return url
    }
  }
  return row.sample_prompt_question || row.domain
}

async function load() {
  const request = ++loadRequest
  const requestedTenant = tenantId.value
  data.value = null
  if (!requestedTenant) {
    loading.value = false
    error.value = '请先选择客户或配置本地 API Key'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const result = await fetchGeoCitationInsights(requestedTenant, {
      date_from: obsStart.value,
      date_to: obsEnd.value,
      days: observationDays.value,
    })
    if (request !== loadRequest || requestedTenant !== tenantId.value) return
    data.value = result
    pager.resetPage()
    showAllArticles.value = false
  } catch (e) {
    if (request !== loadRequest || requestedTenant !== tenantId.value) return
    error.value = e.message || '加载失败'
    data.value = null
  } finally {
    if (request === loadRequest) loading.value = false
  }
}

async function createOpportunityTask(row) {
  if (creatingOpportunity.value !== null) return
  const owner = tenantId.value
  creatingOpportunity.value = row.prompt_id
  try {
    const result = await createGeoSourceOpportunityTask({
      tenant_id: owner, prompt_id: row.prompt_id, snapshot_ids: row.sample_ids, evidence_version: row.evidence_version,
    })
    if (owner !== tenantId.value) return
    ElMessage.success(result.created ? '已创建草稿任务并保留机会证据' : '该问题已有任务，已打开')
    router.push(result.editor_path)
  } catch (e) {
    if (owner === tenantId.value) ElMessage.error(formatGeoError(e, '创建失败，请刷新机会清单'))
  } finally {
    creatingOpportunity.value = null
  }
}

function exportOpportunities() {
  const rows = opportunityExportRows(opportunities.value)
  downloadCsv(`geo-source-opportunities-${tenantId.value}.csv`,
    ['问题', '核对顺序', '观察依据', '建议行动', '快照编号', '引擎', '采样时间', '提及品牌', '记录的引用（待核验）'], rows)
}

function exportCsv() {
  const rows = citeItems.value.map((r) => [
    r.domain,
    r.cite_count,
    (r.engines || []).map(engineDisplay).join(' / '),
    r.blueprint_channel_name || r.blueprint_channel_key || '',
    r.is_own_domain ? '是' : '否',
    r.prompt_count ?? '',
    r.latest_captured_at || '',
    (r.sample_urls || [])[0] || '',
  ])
  downloadCsv(
    `geo-citations-${tenantId.value}.csv`,
    ['域名', '引用次数', '引擎', '蓝图渠道', '自有域', '关联意图词数', '最近观测', '样例 URL'],
    rows,
  )
  ElMessage.success('已导出当前筛选结果')
}

async function runBackfill() {
  if (!tenantId.value) return
  backfilling.value = true
  try {
    const res = await backfillAttribution(tenantId.value, { limit: 1000, onlyEmpty: true })
    ElMessage.success(
      `归因回填完成：扫描 ${res.scanned || 0} · 更新 ${res.updated || 0} · 命中 ${res.matched_hits || 0}`,
    )
    await load()
  } catch (e) {
    ElMessage.error(formatGeoError(e, '回填失败'))
  } finally {
    backfilling.value = false
  }
}

/** 域名行 → 可见度快照（用域名作提示；引擎若唯一则带上） */
function openDomain(row) {
  if (!row) return
  const q = { domain: row.domain }
  if ((row.engines || []).length === 1) q.engine = row.engines[0]
  router.push({ path: '/geo/visibility/snapshots', query: q })
}

watch([tenantId, observationDays, obsStart, obsEnd], load)
watch([ownOnly, domainQuery], () => pager.resetPage())
onMounted(load)
</script>

<template>
  <GeoWorkbenchPage
    title="信源分析"
    :sub="`AI 回答时到底从哪些平台、哪些文章取数引用 · ${obsLabel}`"
    :loading="loading"
  >
    <template #actions>
      <input v-model="domainQuery" class="gd-search" placeholder="搜索信源 / 文章…" />
      <button class="gd-btn" type="button" :disabled="!citeItems.length" @click="exportCsv">数据导出</button>
    </template>
    <div class="geo-dash geo-page">

    <details v-if="prototypeSurface.showCitationRawMetrics" class="geo-glossary">
      <summary>统计口径（点击展开）</summary>
      <ul>
        <li v-for="(line, i) in REPORT_GLOSSARY.citations" :key="i">{{ line }}</li>
      </ul>
    </details>

    <el-alert v-if="error" :title="error" type="error" :closable="false" class="mb" show-icon />

    <section v-if="data?.source_opportunities" class="gd-card" style="margin-bottom:16px">
      <div class="gd-hd">
        <h3>有样本依据的内容机会</h3>
        <button class="gd-btn" :disabled="!opportunities.length" @click="exportOpportunities">导出机会与证据</button>
      </div>
      <div class="gd-bd">
        <p>{{ data.source_opportunities.note }}</p>
        <p>当前窗口可用样本 {{ data.source_opportunities.eligible_samples }} 条；
          排除非 API {{ data.source_opportunities.excluded_samples.non_api }} 条、
          旧方法 {{ data.source_opportunities.excluded_samples.legacy_method }} 条、
          待复核 {{ data.source_opportunities.excluded_samples.needs_review }} 条、
          点名或问题缺失 {{ data.source_opportunities.excluded_samples.brand_probe_or_missing_prompt }} 条、
          已标记引用不准确 {{ data.source_opportunities.excluded_samples.inaccurate_citation }} 条。
        </p>
        <el-alert v-if="!data.source_opportunities.own_domains_configured" title="尚未配置自有域，引用归属需核对，暂不判断自有域缺口。" type="info" :closable="false" />
        <el-table :data="opportunities" empty-text="当前没有满足条件的内容机会；这不代表没有缺口，请补充采样或核对排除原因。">
          <el-table-column type="expand">
            <template #default="{ row }">
              <div style="padding:12px 24px">
                <p>{{ row.next_action }}</p>
                <p v-for="evidence in row.evidence" :key="evidence.snapshot_id">
                  <el-button text type="primary" @click="router.push(geoSnapshotLink({ prompt_id: row.prompt_id, snapshot_id: evidence.snapshot_id }))">查看快照 #{{ evidence.snapshot_id }}</el-button>
                  {{ engineDisplay(evidence.engine) }} · {{ evidence.captured_at }} · {{ evidence.mentions_brand ? '已提及' : '未提及' }}
                  <span v-for="url in evidence.urls" :key="url" style="display:block;overflow-wrap:anywhere">{{ url }}</span>
                </p>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="question" label="问题" min-width="200" />
          <el-table-column prop="priority" label="核对顺序" width="110" />
          <el-table-column prop="reason" label="观察依据" min-width="250" />
          <el-table-column prop="sample_count" label="可用样本" width="95" />
          <el-table-column label="行动" width="135">
            <template #default="{ row }">
              <el-button text type="primary" :loading="creatingOpportunity === row.prompt_id" :disabled="creatingOpportunity !== null || !row.sample_ids?.length || row.sample_ids.length > 1000" @click="createOpportunityTask(row)">创建 / 打开任务</el-button>
              <small v-if="row.sample_ids?.length > 1000">请缩小观察窗口</small>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </section>

    <div v-if="data" style="margin-bottom:16px">
      <p>{{ data.statistics_note }} 已排除模拟 {{ data.excluded_simulated || 0 }} 条。</p>
      <p>{{ data.sample_composition?.label }}</p>
      <el-alert v-if="data.rates_comparable === false" title="当前样本方法混用或存在待复核判读，百分比暂不展示" type="warning" :closable="false" />
      <el-alert v-else-if="data.sample_composition?.suitable_for_client === false" :title="data.sample_composition.verdict_reason" type="info" :closable="false" />
      <p v-if="data.sample_composition?.legacy_method_warning">包含历史未标记方法，无法确认是否采用品牌中立提问。</p>
    </div>

    <div v-if="data" class="gd-kpis">
      <div class="gd-card gd-stat">
        <div class="label">已识别信源平台</div>
        <div class="value">{{ fmtInt(data.distinct_cited_domains) }}</div>
        <div class="delta hint">个</div>
      </div>
      <div class="gd-card gd-stat">
        <div class="label">最常被引平台</div>
        <div class="value value-platform">{{ topPlatform?.name || '—' }}</div>
        <div class="delta hint">{{ topShare != null ? `占比 ${fmtPct(topShare)}` : data?.rates_comparable === false ? '口径待核对' : '暂无引用' }}</div>
      </div>
      <div class="gd-card gd-stat">
        <div class="label">本品牌内容占比</div>
        <div class="value">{{ fmtPct(data.own_domain_cite_rate) }}</div>
        <div class="delta hint">
          {{
            !(data.own_domains || []).length
              ? '未配置官网渠道'
              : data.own_domain_cite_rate == null
                ? (data.rates_comparable === false ? '口径待核对' : '暂无引用')
                : '含引用快照中命中自有域'
          }}
        </div>
      </div>
      <div class="gd-card gd-stat">
        <div class="label">参考渠道未见引用</div>
        <div class="value" :style="pendingChannels.length ? { color: 'var(--gd-warn)' } : {}">
          {{ (data.items || []).length ? fmtInt(pendingChannels.length) : '—' }}
        </div>
        <div class="delta hint">固定参考清单，不代表内容缺口</div>
      </div>
    </div>

    <div v-if="heatMap.engines.length && data?.rates_comparable !== false" class="gd-card" style="margin-bottom:16px">
      <div class="gd-hd">
        <h3>信源平台 × 引擎的域名引用占比</h3>
        <span class="more">各列分母为该引擎全部域名引用次数</span>
      </div>
      <div class="gd-bd" style="padding:0;overflow:auto">
        <table class="gd-heat">
          <thead>
            <tr>
              <th>信源平台</th>
              <th v-for="e in heatMap.engines" :key="e">{{ engineDisplay(e) }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in heatMap.rows" :key="r.name" :class="{ 'own-row': r.name === OWN_HEAT_NAME }">
              <td class="kw">{{ r.name }}</td>
              <td
                v-for="(cell, i) in r.cells"
                :key="i"
                :style="{ background: heatTone(cell).bg, color: heatTone(cell).fg }"
              >{{ fmtPct(cell) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="prototypeSurface.showCitationRawMetrics && data" class="geo-kpi-grid">
      <div class="geo-kpi">
        <div class="kpi-label">含引用的快照</div>
        <div class="kpi-value">{{ fmtInt(data.snapshots_with_citations) }}</div>
        <div class="kpi-hint">至少有 1 条 URL 的快照</div>
      </div>
      <div class="geo-kpi">
        <div class="kpi-label">独立被引域名</div>
        <div class="kpi-value">{{ fmtInt(data.distinct_cited_domains) }}</div>
        <div class="kpi-hint">去重后的主机名</div>
      </div>
      <div class="geo-kpi">
        <div class="kpi-label">自有域引用率</div>
        <div class="kpi-value">{{ fmtPct(data.own_domain_cite_rate) }}</div>
        <div class="kpi-hint">
          含引用快照中命中自有域的占比
          <template v-if="!(data.own_domains || []).length"> · 未配置官网渠道</template>
        </div>
      </div>
      <div class="geo-kpi">
        <div class="kpi-label">快照总量</div>
        <div class="kpi-value">{{ fmtInt(data.total_snapshots) }}</div>
        <div class="kpi-hint">含无 URL 的快照</div>
      </div>
    </div>

    <template v-if="data">
      <section v-if="prototypeSurface.showCitationRawMetrics && qualityRows.length" class="geo-panel">
        <div class="panel-title">引用质量分布</div>
        <p class="geo-panel-desc">来自快照标注；未知偏多时请到可见度页补标或「校验引用」。</p>
        <el-table :data="qualityRows" size="small" empty-text="暂无标注">
          <el-table-column prop="dim" label="维度" width="120" />
          <el-table-column prop="value" label="取值" min-width="140" />
          <el-table-column prop="count" label="快照数" width="90" />
        </el-table>
      </section>

      <div v-if="(data.items || []).length" class="gd-bottom">
        <div class="gd-card">
          <div class="gd-hd">
            <h3>被引用域名与样例页面</h3>
            <span
              class="more"
              :class="{ 'is-action': articleRows.length > ARTICLE_PREVIEW }"
              @click="articleRows.length > ARTICLE_PREVIEW && (showAllArticles = !showAllArticles)"
            >{{ showAllArticles ? '收起' : '全部引擎' }}</span>
          </div>
          <div class="gd-bd" style="padding:0;overflow:auto">
            <table v-if="visibleArticles.length">
              <thead>
                <tr>
                  <th>样例页面</th>
                  <th>信源</th>
                  <th>域名引用次数</th>
                  <th>归属</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="row in visibleArticles"
                  :key="row.domain"
                  class="click-row"
                  @click="openDomain(row)"
                >
                  <td class="kw">
                    <a
                      v-if="row.url"
                      :href="row.url"
                      target="_blank"
                      rel="noopener"
                      class="article-link"
                      :title="row.url"
                      @click.stop
                    >{{ row.title }}</a>
                    <span v-else>{{ row.title }}</span>
                  </td>
                  <td class="muted">{{ row.source }}</td>
                  <td>{{ fmtInt(row.cite_count) }}</td>
                  <td>
                    <span class="gd-badge" :class="row.owner === '本品牌' ? 'green' : ''">{{ row.owner }}</span>
                  </td>
                </tr>
              </tbody>
            </table>
            <p v-else class="gd-sub" style="padding:18px">无匹配文章</p>
          </div>
        </div>

        <div class="gd-card">
          <div class="gd-hd">
            <h3>💡 信源布局建议</h3>
            <span class="gd-badge blue">根据引用数据</span>
          </div>
          <div class="gd-bd">
            <ul v-if="layoutAdvice.rows.length" class="gd-sources">
              <li v-for="(s, i) in layoutAdvice.rows" :key="i">
                <span class="gd-badge" :class="s.tone">{{ s.tag }}</span>
                <span>{{ s.text }}</span>
                <router-link v-if="s.to" class="gd-sub extra" :to="s.to">{{ s.extra }}</router-link>
                <span v-else class="gd-sub extra">{{ s.extra }}</span>
              </li>
            </ul>
            <p v-else class="gd-sub" style="margin:0">暂无布局建议</p>
            <p v-if="layoutAdvice.conclusion" class="gd-sub advice-foot">{{ layoutAdvice.conclusion }}</p>
          </div>
        </div>
      </div>

      <GeoEmptyState
        v-else
        icon="▤"
        title="还没有可聚合的引用"
        desc="请先在「AI 可见度」登记含 URL 的回答，或跑巡检后刷新。"
      >
        <template #action>
          <router-link class="el-button el-button--primary" :to="geoSnapshotLink()">去登记</router-link>
          <router-link class="el-button" to="/geo/placements">去信源策略</router-link>
          <button class="el-button" type="button" :disabled="backfilling" @click="runBackfill">
            {{ backfilling ? '回填中…' : '归因回填' }}
          </button>
        </template>
      </GeoEmptyState>

      <details class="domain-details">
        <summary>域名明细</summary>
        <template v-if="citeItems.length">
          <div class="geo-filter-bar">
            <el-checkbox v-if="prototypeSurface.showCitationRawMetrics" v-model="ownOnly">仅看自有域</el-checkbox>
            <span class="geo-muted">当前 {{ citeItems.length }} 个域名</span>
          </div>
          <el-table
            :data="pager.pagedItems"
            size="small"
            stripe
            class="clickable-rows"
            @row-click="openDomain"
          >
            <el-table-column prop="domain" label="域名" min-width="170" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="row-link">{{ row.domain }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="cite_count" label="出现次数" width="96" />
            <el-table-column prop="prompt_count" label="意图词数" width="96" />
            <el-table-column label="引擎" min-width="140">
              <template #default="{ row }">
                {{ (row.engines || []).map(engineDisplay).join(' · ') || '—' }}
              </template>
            </el-table-column>
            <el-table-column label="样例 URL" min-width="190" show-overflow-tooltip>
              <template #default="{ row }">
                {{ (row.sample_urls || [])[0] || '—' }}
              </template>
            </el-table-column>
            <el-table-column v-if="prototypeSurface.showCitationRawMetrics" label="蓝图渠道" min-width="140" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.blueprint_channel_name || row.blueprint_channel_key || '未匹配' }}
              </template>
            </el-table-column>
            <el-table-column v-if="prototypeSurface.showCitationRawMetrics" label="域名归属" width="100">
              <template #default="{ row }">
                <span :class="row.is_own_domain ? 'geo-tag-own' : 'geo-tag-ext'">
                  {{ row.is_own_domain ? '自有' : '外部' }}
                </span>
              </template>
            </el-table-column>
          </el-table>
          <div class="geo-pager">
            <el-pagination
              background
              layout="total, sizes, prev, pager, next"
              :total="pager.total"
              :page-size="pager.pageSize"
              :current-page="pager.page"
              :page-sizes="[10, 20, 50, 100]"
              @current-change="pager.onPageChange"
              @size-change="pager.onSizeChange"
            />
          </div>
        </template>
        <p v-else class="gd-sub">当前筛选下没有域名</p>
      </details>
    </template>
    </div>
  </GeoWorkbenchPage>
</template>

<style scoped>
.geo-page { display: flex; flex-direction: column; }
.mb { margin-bottom: 14px; }
.clickable-rows :deep(tbody tr),
.click-row { cursor: pointer; }
.row-link { color: #185fa5; font-weight: 600; }
.kw { font-weight: 600; }
.muted { color: var(--gd-muted); }
.value-platform { font-size: 20px; line-height: 1.25; word-break: break-word; }
.article-link { color: inherit; text-decoration: none; }
.article-link:hover { color: var(--gd-accent); }
.more.is-action { cursor: pointer; }
.gd-sources .extra { margin-left: auto; flex: none; }
.advice-foot {
  margin: 12px 0 0;
  padding: 10px 12px;
  background: var(--gd-bg);
  border-radius: 8px;
}
.domain-details {
  margin-top: 16px;
  background: #fff;
  border: 1px solid var(--gd-border);
  border-radius: 12px;
  padding: 12px 16px;
}
.domain-details summary {
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  color: var(--gd-muted);
}
.domain-details .geo-filter-bar { margin: 12px 0; }
</style>
