<script setup>
import SeoBacklinkInsights from './SeoBacklinkInsights.vue'
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { discoverSeoBacklinks, fetchSeoBacklinks, fetchSeoBacklinkSources, verifySeoBacklink, monitorSeoBacklink } from '../../api/seo'
const props = defineProps({ tenantId: Number, siteId: Number, canEdit: Boolean })
const rows = ref([]), sources = ref([]), selected = ref([]), query = ref(''), filter = ref('all'), urls = ref(''), busy = ref(false), progress = ref(''), results = ref([]), error = ref(''), history = ref(null)
let generation = 0
const scope = () => ({ tenant_id: props.tenantId, site_id: props.siteId })
const names = { pending: '尚未核验', found: '发现外链', missing: '本次未发现', unreachable: '无法访问', blocked: '登录或验证拦截', readable: '页面可读取', internal:'站内发布，不计外链' }
const reasonName = value => ({timeout:'页面抓取超时',login_or_challenge:'需要登录或验证码',empty_response:'页面未返回正文',http_error:'来源页面返回错误',same_site:'来源属于当前网站'}[value] || value || '—')
const state = row => row.status === 'disavow' ? 'paused' : row.verification?.state || 'pending'
const visible = computed(() => rows.value.filter(row => (filter.value === 'all' || state(row) === filter.value || filter.value === 'lost' && row.status === 'lost') && `${row.source_url} ${row.target_url} ${row.anchor_text || ''}`.toLowerCase().includes(query.value.toLowerCase())))
const domains = computed(() => new Set(rows.value.map(row => row.source_domain)).size)
const confirmed = computed(() => rows.value.filter(row => state(row) === 'found').length)
const lost = computed(() => rows.value.filter(row => row.status === 'lost').length)
const time = value => value ? new Date(value.endsWith('Z') ? value : `${value}Z`).toLocaleString() : '—'
async function load() {
  const ticket = ++generation
  rows.value = []; sources.value = []; selected.value = []; history.value = null; results.value = []; error.value = ''
  if (!props.tenantId || !props.siteId) return
  const params = { tenantId: props.tenantId, siteId: props.siteId }
  const responses = await Promise.allSettled([fetchSeoBacklinks(params), fetchSeoBacklinkSources(params)])
  if (ticket !== generation) return
  if (responses[0].status === 'fulfilled') rows.value = responses[0].value.items || []
  else error.value = responses[0].reason.message
  if (responses[1].status === 'fulfilled') sources.value = responses[1].value.items || []
  else error.value += ` 分发来源加载失败：${responses[1].reason.message}`
}
async function run(items, action) {
  if (busy.value || !props.canEdit || !items.length) return
  if (items.length > 50) return ElMessage.warning('每批最多 50 条，请缩小范围')
  const ticket = generation, payload = scope()
  busy.value = true; results.value = []
  try {
    for (const [index, item] of items.entries()) {
      if (ticket !== generation) break
      progress.value = `处理 ${index + 1} / ${items.length}`
      try {
        const value = await action(item, payload)
        if (ticket !== generation) break
        results.value.push({ url: item.source_url, ...value })
      } catch (e) { if (ticket === generation) results.value.push({ url: item.source_url, state: 'error', reason: e.message }) }
    }
    if (ticket === generation) {
      const value = await fetchSeoBacklinks({ tenantId: payload.tenant_id, siteId: payload.site_id })
      if (ticket === generation) rows.value = value.items || []
      if (ticket === generation) {
        const sourceResult = await fetchSeoBacklinkSources({ tenantId: payload.tenant_id, siteId: payload.site_id })
        if (ticket === generation) sources.value = sourceResult.items || []
      }
    }
  } catch (e) { if (ticket === generation) error.value = e.message }
  finally { busy.value = false; progress.value = '' }
}
const discover = items => run(items, (item, payload) => discoverSeoBacklinks({ ...payload, source_url: item.source_url, publication_id: item.id || null }))
function scanUrls() {
  const items = [...new Set(urls.value.split(/\r?\n/).map(v => v.trim()).filter(Boolean))].map(source_url => ({ source_url }))
  if (!items.length) return ElMessage.warning('请粘贴要检查的站外页面地址')
  return discover(items)
}
const verify = items => run(items, async (item, payload) => (await verifySeoBacklink(item.id, payload)).verification)
const toggle = item => run([item], async (row, payload) => { await monitorSeoBacklink(row.id, { ...payload, enabled: row.status === 'disavow' }); return { state: row.status === 'disavow' ? 'pending' : 'paused' } })
function exportCsv() {
  const cell = value => `"${String(value ?? '').replace(/^\s*[=+@-]/, "'$&").replaceAll('"', '""')}"`
  const data = [['来源页面','目标页面','锚文本','核验状态','链接属性','最后核验'], ...visible.value.map(row => [row.source_url,row.target_url,row.anchor_text,names[state(row)] || state(row),(row.verification?.rel || []).join(' '),row.last_checked_at])]
  const url = URL.createObjectURL(new Blob(['\uFEFF'+data.map(row => row.map(cell).join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8' }))
  const a = document.createElement('a'); a.href = url; a.download = '外链清单.csv'; a.click(); URL.revokeObjectURL(url)
}
watch(() => [props.tenantId, props.siteId], () => { urls.value = ''; load() })
onMounted(load)
onBeforeUnmount(() => { generation++ })
defineExpose({ load })
</script>
<template>
  <el-alert v-if="error" :title="error" type="warning" :closable="false"/>
  <section class="suite-metrics"><article><span>已确认外链</span><strong>{{confirmed}}</strong><small>最近一次抓取发现真实链接</small></article><article><span>来源域名</span><strong>{{domains}}</strong><small>外部引荐来源</small></article><article><span>丢失外链</span><strong>{{lost}}</strong><small>间隔至少 20 小时连续两次未发现</small></article><article><span>分发来源</span><strong>{{sources.length}}</strong><small>最近 200 条已发布记录</small></article></section>
  <section class="suite-panel discovery"><header><div><h2>发现外链</h2><small>从分发记录或提供的站外页面提取链接，仅将真正指向当前网站的链接入库。</small></div></header>
    <el-input v-model="urls" type="textarea" :rows="3" placeholder="粘贴媒体报道、合作伙伴或已发布文章的 URL，每行一条；每批最多 50 页"/>
    <div class="actions"><el-button v-if="canEdit" type="primary" :disabled="busy" @click="scanUrls">扫描这些页面</el-button><el-button v-if="canEdit" :disabled="busy || !sources.length" @click="discover(sources.slice(0,50))">扫描最近分发页面（{{Math.min(sources.length,50)}}）</el-button><span>{{progress}}</span></div>
    <p>这是公开页面发现，不代表全网外链总量。无法访问、登录拦截和无外链会分别展示；收录、排名和权重不由外链数量保证。</p>
    <el-table v-if="results.length" :data="results" max-height="260"><el-table-column prop="url" label="来源页面" show-overflow-tooltip/><el-table-column label="扫描结果" width="160"><template #default="{row}">{{names[row.state] || (row.state==='paused'?'已停止监控':'处理失败')}}</template></el-table-column><el-table-column label="发现 / 新入库" width="130"><template #default="{row}">{{row.found ?? '—'}} / {{row.created ?? '—'}}</template></el-table-column><el-table-column prop="reason" label="原因"/></el-table>
  </section>
  <section class="suite-panel discovery"><header><div><h2>分发来源与发现结果</h2><small>每小时处理最多 20 条待扫描来源；正常页面 7 天后复查，失败页面 1 小时后重试。</small></div><el-button :disabled="busy" @click="load">刷新结果</el-button></header>
    <el-table :data="sources" max-height="320" empty-text="分发完成后回收公开文章链接，这里会自动纳入发现任务"><el-table-column prop="platform_name" label="平台" width="120"/><el-table-column label="来源页面" min-width="250" show-overflow-tooltip><template #default="{row}"><a :href="row.source_url" target="_blank" rel="noopener noreferrer">{{row.source_url}}</a></template></el-table-column><el-table-column label="最近结果" width="170"><template #default="{row}">{{row.discovery?.state==='readable' ? `发现 ${row.discovery.found || 0} 条外链` : names[row.discovery?.state || 'pending']}}<small class="url">{{reasonName(row.discovery?.reason)}}</small></template></el-table-column><el-table-column label="扫描时间" width="180"><template #default="{row}">{{time(row.discovery?.checked_at)}}</template></el-table-column><el-table-column label="操作" width="90"><template #default="{row}"><el-button v-if="canEdit && row.discovery?.state!=='internal'" link :disabled="busy" @click="discover([row])">{{row.discovery?'重试':'扫描'}}</el-button></template></el-table-column></el-table>
  </section>
  <SeoBacklinkInsights :tenant-id="tenantId" :site-id="siteId" :can-edit="canEdit" @changed="load"/>
  <section class="suite-panel"><header><h2>外链资产与监控</h2><el-button @click="exportCsv">导出筛选结果</el-button></header>
    <div class="actions"><el-input v-model="query" placeholder="搜索域名、来源、目标或锚文本" clearable style="max-width:340px"/><el-select v-model="filter" style="width:160px"><el-option label="全部" value="all"/><el-option v-for="(label,key) in names" :key="key" :label="label" :value="key"/><el-option label="确认丢失" value="lost"/><el-option label="停止监控" value="paused"/></el-select><el-button v-if="canEdit" :disabled="busy || !selected.length" @click="verify(selected.filter(row=>row.status!=='disavow'))">核验所选（{{selected.length}}）</el-button></div>
    <el-table :data="visible" @selection-change="selected=$event" empty-text="扫描已发布页面发现外链，或录入已知外链"><el-table-column type="selection" width="40"/><el-table-column label="来源 → 目标" min-width="300"><template #default="{row}"><a :href="row.source_url" target="_blank" rel="noopener noreferrer">{{row.source_domain}}</a><small class="url">{{row.source_url}}</small><small class="url">→ {{row.target_url}}</small></template></el-table-column><el-table-column prop="anchor_text" label="锚文本" width="130"/><el-table-column label="链接属性" width="140"><template #default="{row}">{{row.verification?.state==='found' ? (row.verification.rel?.join(', ') || '未声明 nofollow') : '待核验'}}</template></el-table-column><el-table-column label="核验与监控" width="180"><template #default="{row}"><b>{{state(row)==='paused'?'已停止监控':names[state(row)]}}</b><small class="url">{{row.status==='lost'?'已确认丢失 · ':''}}{{time(row.last_checked_at)}}</small></template></el-table-column><el-table-column label="操作" width="180"><template #default="{row}"><el-button v-if="canEdit && row.status!=='disavow'" link :disabled="busy" @click="verify([row])">核验</el-button><el-button link @click="history=row">证据</el-button><el-button v-if="canEdit" link :disabled="busy" @click="toggle(row)">{{row.status==='disavow'?'恢复监控':'停止监控'}}</el-button></template></el-table-column></el-table>
    <p>入库后由已有定时任务复查。停止监控仅影响本系统，不会向搜索引擎提交拒绝外链。</p>
  </section>
  <el-dialog :model-value="!!history" title="最近核验记录（最多 20 次）" @close="history=null"><p>{{history?.source_url}}</p><el-table :data="[...(history?.verification?.history || [])].reverse()" empty-text="尚无抓取证据"><el-table-column label="时间"><template #default="{row}">{{time(row.checked_at)}}</template></el-table-column><el-table-column label="结果"><template #default="{row}">{{names[row.state]}}</template></el-table-column><el-table-column prop="http_status" label="HTTP"/><el-table-column prop="reason" label="原因"/></el-table></el-dialog>
</template>
<style scoped>.actions{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:14px 0}.discovery{margin-bottom:18px}.url{display:block;overflow-wrap:anywhere;color:#748097;margin-top:4px}p{color:#64748b;font-size:13px}a{color:#2658d7}</style>
