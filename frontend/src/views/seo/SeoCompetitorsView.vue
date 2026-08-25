<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  collectSeoCompetitor,
  createSeoCompetitor,
  createSeoCompetitorEvent,
  fetchSeoCompetitorRankings,
  fetchSeoCompetitors,
  fetchSeoKeywords,
} from '../../api/seo'
import { fetchSeoSites } from '../../api/moduleAssets'
import { currentTenantId, session } from '../../store/session'
import { formatSeoRankTime, parseSeoRankTime } from './seoRankTime'
import '../../../public/deal-sniper-prototype/seo/assets/keyword-assets-v2.css'

const loading = ref(false)
const error = ref('')
const sites = ref([])
const siteId = ref(null)
const device = ref('desktop')
const data = ref({ items: [], events: [] })
const keywords = ref([])
const rankingData = ref({ competitors: [], items: [] })
const tab = ref('ranking')
const dialog = ref(false)
const eventDialog = ref(false)
const saving = ref(false)
const collectingId = ref(null)
const collectionOutcome = ref(null)
const cooldownClock = ref(Date.now())
const eventTarget = ref(null)
const form = reactive({ name: '', domain: '', notes: '' })
const eventForm = reactive({ event_type: 'content', title: '', url: '', source_url: '', summary: '', event_at: '' })

const canEdit = computed(() => !session.isLoggedIn || session.canEdit('seo.competitors'))
const visibleCompetitors = computed(() => data.value.items)
const rankingCompetitors = computed(() => data.value.items.slice(0, 5))
const highGaps = computed(() => keywords.value.filter((item) => !item.landing_page || item.latest_rank > 20).slice(0, 5))
const rankRows = computed(() => new Map(rankingData.value.items.map((item) => [Number(item.keyword_id), item])))

function competitorRank(keywordId, competitorId) {
  return rankRows.value.get(Number(keywordId))?.rankings?.[String(competitorId)] || { state: 'not_collected', rank: null }
}

function rankText(value) {
  if (value.state === 'ranked') return String(value.rank)
  if (value.state === 'outside_top50') return '50+'
  return '待采集'
}

function rankHint(value) {
  if (value.state === 'ranked') return '已进入前 50'
  if (value.state === 'outside_top50') return '本批前 50 未发现'
  return '该关键词尚无可用 SERP 批次'
}

function cooldownSeconds(item) {
  const nextAllowed = parseSeoRankTime(item.next_collection_allowed_at)
  if (!nextAllowed) return 0
  return Math.max(0, Math.ceil((nextAllowed.getTime() - cooldownClock.value) / 1000))
}

function collectButtonText(item) {
  if (collectingId.value === item.id) return '采集中…'
  const remaining = cooldownSeconds(item)
  return remaining ? `${Math.ceil(remaining / 60)} 分钟后可采集` : '手动采集'
}

async function load() {
  if (!currentTenantId.value) {
    error.value = '请先选择客户'
    return
  }
  if (!siteId.value) {
    error.value = '请先选择或创建 SEO 网站'
    return
  }
  loading.value = true
  try {
    const [competitors, keywordResult, rankings] = await Promise.all([
      fetchSeoCompetitors({ tenantId: currentTenantId.value, siteId: siteId.value }),
      fetchSeoKeywords({ tenantId: currentTenantId.value, siteId: siteId.value, engine: 'baidu', device: device.value, pageSize: 100 }),
      fetchSeoCompetitorRankings({ tenantId: currentTenantId.value, siteId: siteId.value, device: device.value }),
    ])
    data.value = competitors
    keywords.value = keywordResult.items || []
    rankingData.value = rankings
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
    return
  }
  try {
    sites.value = (await fetchSeoSites(currentTenantId.value)).sites || []
    const active = sites.value.find((site) => site.status === 'active') || sites.value[0]
    const nextSiteId = sites.value.some((site) => site.id === siteId.value) ? siteId.value : (active?.id || null)
    if (nextSiteId !== siteId.value) siteId.value = nextSiteId
    else if (nextSiteId) await load()
    if (!siteId.value) error.value = '请先选择或创建 SEO 网站'
  } catch (err) {
    sites.value = []
    siteId.value = null
    error.value = err.message
  }
}

async function save() {
  if (!siteId.value) return ElMessage.warning('请先选择 SEO 网站')
  if (!form.name.trim() || !form.domain.trim()) return ElMessage.warning('请填写竞品名称和域名')
  saving.value = true
  try {
    await createSeoCompetitor({
      tenant_id: currentTenantId.value,
      site_id: siteId.value,
      name: form.name.trim(),
      domain: form.domain.trim(),
      notes: form.notes.trim() || null,
    })
    dialog.value = false
    Object.assign(form, { name: '', domain: '', notes: '' })
    ElMessage.success('竞品已加入当前网站')
    await load()
  } catch (err) {
    ElMessage.error(err.message)
    await load()
  } finally {
    saving.value = false
  }
}

async function collect(item) {
  if (cooldownSeconds(item)) {
    collectionOutcome.value = {
      competitor: item.name,
      failed: true,
      cooldownRejected: true,
      message: '当前仍在冷却，请稍后重试',
    }
    return
  }
  try {
    await ElMessageBox.confirm(
      `本次最多检查 ${item.name} 的 10 个公开页面；无论成功或失败，本次尝试都会进入 1 小时冷却。`,
      '手动采集竞品内容',
      { confirmButtonText: '开始采集', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  collectingId.value = item.id
  try {
    const result = await collectSeoCompetitor({
      competitorId: item.id,
      tenantId: currentTenantId.value,
      siteId: siteId.value,
      maxPages: 10,
    })
    collectionOutcome.value = { competitor: item.name, ...result }
    if (result.failed_pages) {
      ElMessage.warning(`采集部分完成：成功 ${result.checked_pages} 个页面，失败 ${result.failed_pages} 个`)
    } else if (result.baseline) {
      ElMessage.success(`已建立内容基线：${result.created_events} 个页面`)
    } else {
      ElMessage.success(`采集完成：发现 ${result.created_events} 个新内容`)
    }
    await load()
  } catch (err) {
    const message = err.message || '竞品采集失败，请稍后重试'
    const cooldownRejected = message.includes('仍在冷却')
    collectionOutcome.value = {
      competitor: item.name,
      failed: true,
      cooldownRejected,
      message,
    }
    ElMessage.error(message)
    await load()
  } finally {
    collectingId.value = null
  }
}

function openEvent(item) {
  eventTarget.value = item
  eventDialog.value = true
}

async function saveEvent() {
  if (!eventForm.url.trim()) return ElMessage.warning('请填写动态页面 URL')
  saving.value = true
  try {
    await createSeoCompetitorEvent({
      tenant_id: currentTenantId.value,
      site_id: siteId.value,
      competitor_id: eventTarget.value.id,
      event_type: eventForm.event_type,
      title: eventForm.title.trim() || null,
      url: eventForm.url.trim(),
      source_url: eventForm.source_url.trim() || null,
      summary: eventForm.summary.trim() || null,
      event_at: eventForm.event_at ? new Date(eventForm.event_at).toISOString() : null,
    })
    eventDialog.value = false
    Object.assign(eventForm, { event_type: 'content', title: '', url: '', source_url: '', summary: '', event_at: '' })
    ElMessage.success('竞品动态已记录')
    await load()
  } catch (err) {
    ElMessage.error(err.message)
  } finally {
    saving.value = false
  }
}

let cooldownTimer
watch(currentTenantId, loadSites)
watch(siteId, () => { collectionOutcome.value = null; load() })
watch(device, load)
onMounted(() => {
  loadSites()
  cooldownTimer = window.setInterval(() => { cooldownClock.value = Date.now() }, 1000)
})
onUnmounted(() => window.clearInterval(cooldownTimer))
</script>

<template>
  <div class="keyword-assets competitor-prototype" v-loading="loading">
    <section class="kw-hero">
      <div>
        <div class="kw-kicker">Competitive landscape</div>
        <h2>竞品表现</h2>
        <p>复用已采集的百度前 50 数据对比竞品排名，并由用户手动采集竞品公开内容。</p>
      </div>
      <div class="hero-actions">
        <el-select v-model="siteId" class="site-picker" placeholder="选择 SEO 网站">
          <el-option v-for="site in sites" :key="site.id" :label="site.name || site.canonical_domain" :value="site.id" />
        </el-select>
        <button v-if="canEdit" class="kw-btn" :disabled="!siteId" @click="dialog = true">＋ 添加竞品</button>
        <button class="kw-btn primary" :disabled="!siteId" @click="load">刷新排名对比</button>
      </div>
    </section>

    <el-alert v-if="error" :title="error" type="warning" :closable="false" />
    <el-alert
      v-if="collectionOutcome"
      class="collection-outcome"
      :title="collectionOutcome.failed
        ? `${collectionOutcome.competitor} 采集失败`
        : collectionOutcome.baseline
          ? `${collectionOutcome.competitor} 已建立内容基线：${collectionOutcome.created_events} 个页面`
          : `${collectionOutcome.competitor} 采集完成：发现 ${collectionOutcome.created_events} 个新内容`"
      :description="collectionOutcome.failed
        ? collectionOutcome.cooldownRejected
          ? `${collectionOutcome.message}；本次请求没有重新开始冷却，页面不会自动重试。`
          : `${collectionOutcome.message}；本次尝试已进入 1 小时冷却，页面不会自动重试。`
        : `检查 ${collectionOutcome.checked_pages}/${collectionOutcome.attempted_pages} 个页面；1 小时后可再次手动采集。`"
      :type="collectionOutcome.failed ? 'error' : collectionOutcome.failed_pages ? 'warning' : 'success'"
      show-icon
      closable
      @close="collectionOutcome = null"
    />

    <div class="kw-competitor-strip">
      <article class="kw-domain-card mine">
        <div class="domain"><span class="favicon">我</span><div>我的网站<small>当前 SEO 网站</small></div></div>
        <strong>{{ keywords.filter((item) => item.latest_rank != null).length }}</strong>
        <small>已有排名关键词</small>
      </article>
      <article v-for="item in visibleCompetitors" :key="item.id" class="kw-domain-card">
        <div class="domain"><span class="favicon">{{ item.name.slice(0, 1) }}</span><div>{{ item.name }}<small>{{ item.domain }}</small></div></div>
        <strong>{{ (item.content || 0) + (item.backlink || 0) }}</strong>
        <small>{{ item.last_checked_at ? `最近采集尝试 ${formatSeoRankTime(item.last_checked_at)}` : '尚未手动采集' }}</small>
        <div class="card-actions">
          <button v-if="canEdit" class="kw-btn small" :disabled="collectingId === item.id || cooldownSeconds(item) > 0" @click="collect(item)">{{ collectButtonText(item) }}</button>
          <button v-if="canEdit" class="kw-btn small" @click="openEvent(item)">记录动态</button>
        </div>
      </article>
    </div>

    <section class="kw-card">
      <header class="kw-card-head">
        <div>
          <h3>{{ tab === 'ranking' ? '核心词排名对标' : '竞品内容 / 外链动态' }}</h3>
          <p>{{ tab === 'ranking' ? `百度${device === 'desktop' ? '桌面端' : '移动端'} · 全国 · 每个关键词最近一次有效 SERP` : '手动采集和人工记录，不会自动运行' }}</p>
        </div>
        <div class="head-controls">
          <div v-if="tab === 'ranking'" class="kw-segment">
            <button :class="{ active: device === 'desktop' }" @click="device = 'desktop'">百度 PC</button>
            <button :class="{ active: device === 'mobile' }" @click="device = 'mobile'">百度移动</button>
          </div>
          <div class="kw-segment">
            <button :class="{ active: tab === 'ranking' }" @click="tab = 'ranking'">排名对比</button>
            <button :class="{ active: tab === 'events' }" @click="tab = 'events'">内容 / 外链动态</button>
          </div>
        </div>
      </header>

      <div v-if="tab === 'ranking'" class="kw-table-wrap">
        <table class="kw-table">
          <thead><tr><th>关键词</th><th>我的网站</th><th v-for="item in rankingCompetitors" :key="item.id">{{ item.name }}</th><th>竞争状态</th></tr></thead>
          <tbody>
            <tr v-for="item in keywords.slice(0, 50)" :key="item.id">
              <td class="keyword-cell"><span class="kw-name">{{ item.keyword }}</span><small class="kw-sub">{{ item.cluster || '未归类' }}</small></td>
              <td><span class="kw-rank"><strong>{{ item.latest_rank || '50+' }}</strong></span></td>
              <td v-for="competitor in rankingCompetitors" :key="competitor.id">
                <span class="kw-rank competitor-rank" :title="rankHint(competitorRank(item.id, competitor.id))">
                  <strong>{{ rankText(competitorRank(item.id, competitor.id)) }}</strong>
                  <small>{{ rankHint(competitorRank(item.id, competitor.id)) }}</small>
                </span>
              </td>
              <td><span class="kw-pill" :class="!item.landing_page || item.latest_rank > 20 ? 'red' : 'green'">{{ !item.landing_page ? '待建页' : item.latest_rank > 20 ? '需追赶' : '已覆盖' }}</span></td>
            </tr>
            <tr v-if="!keywords.length"><td :colspan="3 + rankingCompetitors.length"><div class="kw-empty">暂无关键词排名数据</div></td></tr>
          </tbody>
        </table>
      </div>

      <div v-else class="event-list">
        <article v-for="event in data.events" :key="event.id">
          <span class="kw-pill" :class="event.event_type === 'backlink' ? 'orange' : 'blue'">{{ event.event_type === 'backlink' ? '外链记录' : '内容页面' }}</span>
          <div><b>{{ event.title || event.url }}</b><small>{{ event.summary || event.source_url || event.url }}</small></div>
        </article>
        <div v-if="!data.events.length" class="kw-empty">暂无竞品动态；可先对竞品执行一次手动采集建立基线。</div>
      </div>
    </section>

    <div class="kw-grid-equal lower">
      <section class="kw-card"><header class="kw-card-head"><div><h3>最大内容缺口</h3><p>本站覆盖不足的高价值搜索入口</p></div></header><div class="kw-card-body"><div class="kw-alert-list"><div v-for="item in highGaps" :key="item.id" class="kw-alert"><span class="mark">{{ item.priority }}</span><div><h4>{{ item.keyword }}</h4><p>{{ item.landing_page ? `当前排名 #${item.latest_rank || '50+'}` : '本站缺少承接页' }}</p></div><time>{{ item.monthly_volume || '—' }}</time></div><div v-if="!highGaps.length" class="kw-empty">暂无明显内容缺口</div></div></div></section>
      <section class="kw-card"><header class="kw-card-head"><div><h3>采集说明</h3><p>客户主动操作，绝不自动运行</p></div></header><div class="kw-card-body collection-policy"><p>每次最多检查 10 个公开 HTML 页面。</p><p>只保留登记竞品域名及其子域名的数据。</p><p>成功或失败都会冷却 1 小时，页面不会自动重试。</p><p>排名对比复用现有 SERP 数据，不额外调用排名接口。</p></div></section>
    </div>

    <el-dialog v-model="dialog" title="添加竞品" width="560px">
      <el-form label-position="top">
        <el-form-item label="竞品名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="竞品域名"><el-input v-model="form.domain" placeholder="example.com" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.notes" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="eventDialog" :title="`记录动态 · ${eventTarget?.name || ''}`" width="620px">
      <el-form label-position="top">
        <el-form-item label="类型"><el-select v-model="eventForm.event_type"><el-option label="内容" value="content" /><el-option label="外链" value="backlink" /></el-select></el-form-item>
        <el-form-item label="标题"><el-input v-model="eventForm.title" /></el-form-item>
        <el-form-item label="动态页面 URL"><el-input v-model="eventForm.url" /></el-form-item>
        <el-form-item label="来源 URL"><el-input v-model="eventForm.source_url" /></el-form-item>
        <el-form-item label="摘要"><el-input v-model="eventForm.summary" type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="发生时间"><el-date-picker v-model="eventForm.event_at" type="datetime" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="eventDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveEvent">保存</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.competitor-prototype{min-height:100%;padding:22px 26px 30px;background:#f5f7fb}.hero-actions,.head-controls,.card-actions{display:flex;align-items:center;gap:10px}.hero-actions{flex-wrap:wrap;justify-content:flex-end}.site-picker{width:260px}.collection-outcome{margin:14px 0}.kw-competitor-strip{grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}.kw-domain-card{min-height:150px}.card-actions{margin-top:12px}.lower{margin-top:15px}.event-list article{padding:14px 17px;display:flex;align-items:center;gap:12px;border-bottom:1px solid #e8eaf0}.event-list b,.event-list small{display:block}.event-list small{margin-top:4px;color:#7b8494}.blue{color:#2853b6!important;background:#edf2ff!important}.competitor-rank small{display:block;margin-top:3px;color:#8993a5;font-size:11px;font-weight:400}.collection-policy{display:grid;gap:10px;color:#59657b}.collection-policy p{margin:0;padding-left:16px;position:relative}.collection-policy p:before{content:'✓';position:absolute;left:0;color:#248a64;font-weight:800}@media(max-width:1100px){.kw-hero{flex-direction:column}.hero-actions{justify-content:flex-start}.head-controls{align-items:flex-start;flex-direction:column}}
</style>
