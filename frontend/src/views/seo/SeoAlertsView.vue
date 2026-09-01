<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { fetchSeoSites } from '../../api/moduleAssets'
import { fetchSeoAlerts } from '../../api/seo'
import { currentTenantId } from '../../store/session'
import { currentSeoSiteId as siteId } from './seoSiteContext'
import './seo-suite.css'

const router = useRouter()
const loading = ref(false)
const error = ref('')
const engine = ref('baidu')
const severity = ref('')
const sites = ref([])
const selected = ref(null)
const drawerOpen = ref(false)
const data = ref({ items: [], total: 0, high: 0 })
const items = computed(() => severity.value ? data.value.items.filter((item) => item.severity === severity.value) : data.value.items)
const labels = { rank_drop: '排名骤降', missing_landing: '缺少承接页', site_issue: '站内问题', toxic_backlink: '风险外链' }

async function loadSites() {
  if (!currentTenantId.value) { sites.value = []; siteId.value = null; return }
  try {
    sites.value = (await fetchSeoSites(currentTenantId.value)).sites || []
    const nextSiteId = sites.value.some((item) => item.id === siteId.value)
      ? siteId.value
      : (sites.value.find((item) => item.status === 'active')?.id || sites.value[0]?.id || null)
    if (nextSiteId !== siteId.value) siteId.value = nextSiteId
    else await load()
  } catch (e) {
    sites.value = []; siteId.value = null; error.value = e.message
  }
}

async function load() {
  if (!currentTenantId.value) { error.value = '请先选择客户'; return }
  if (!siteId.value) { error.value = '请先选择或创建 SEO 网站'; data.value = { items: [], total: 0, high: 0 }; return }
  loading.value = true
  error.value = ''
  try {
    data.value = await fetchSeoAlerts({ tenantId: currentTenantId.value, siteId: siteId.value, engine: engine.value })
  } catch (e) { error.value = e.message } finally { loading.value = false }
}

function openDetail(item) { selected.value = item; drawerOpen.value = true }
function handleAction() { if (selected.value?.href) router.push(selected.value.href) }

watch(currentTenantId, () => { selected.value = null; drawerOpen.value = false; loadSites() })
watch([engine, siteId], () => { selected.value = null; load() })
onMounted(loadSites)
</script>

<template>
  <div class="seo-suite" v-loading="loading">
    <section class="suite-hero"><div><span class="eyebrow">SEO EARLY WARNING</span><h1>异常提醒</h1><p>自动聚合排名下降、缺少承接页、站内技术问题与高风险外链，按严重程度进入处理队列。</p></div></section>
    <el-alert v-if="error" class="suite-error" :title="error" type="warning" :closable="false"/>
    <section class="suite-metrics"><article><span>当前异常</span><strong>{{data.total}}</strong><small>由实时资产规则生成</small></article><article><span>高优先级</span><strong>{{data.high}}</strong><small>建议当日处理</small></article><article><span>排名引擎</span><strong>{{engine.toUpperCase()}}</strong><small>可切换排名口径</small></article><article><span>待处理类型</span><strong>{{new Set(data.items.map(i=>i.type)).size}}</strong><small>排名 / 页面 / 外链</small></article></section>
    <section class="suite-panel">
      <header><div><span class="panel-kicker">01 / ALERT QUEUE</span><h2>异常处理队列</h2></div><div class="switch"><button v-for="e in ['baidu','bing','360','sogou','google']" :key="e" :class="{active:engine===e}" @click="engine=e">{{e}}</button></div></header>
      <div class="suite-toolbar"><el-select v-model="siteId" placeholder="选择网站"><el-option v-for="site in sites" :key="site.id" :label="site.name" :value="site.id"/></el-select><el-select v-model="severity" clearable placeholder="全部级别"><el-option label="高优先级" value="high"/><el-option label="普通" value="medium"/></el-select><span>{{items.length}} 条</span></div>
      <ul v-if="items.length" class="suite-list"><li v-for="item in items" :key="`${item.type}-${item.object_id}-${item.device||''}-${item.region||''}`" tabindex="0" role="button" @click="openDetail(item)" @keydown.enter="openDetail(item)"><span class="suite-pill" :class="item.severity==='high'?'danger':'warn'">{{item.severity==='high'?'P0':'P1'}}</span><div class="grow"><b>{{item.title}}</b><small>{{item.detail}} · {{labels[item.type]}}</small></div><time>{{item.occurred_at?new Date(item.occurred_at).toLocaleString():'—'}}</time><b class="detail-arrow">查看详情 →</b></li></ul>
      <div v-else class="suite-empty">当前没有异常</div>
    </section>
    <el-drawer v-model="drawerOpen" title="异常详情" size="420px">
      <template v-if="selected"><div class="alert-detail"><span class="suite-pill" :class="selected.severity==='high'?'danger':'warn'">{{selected.severity==='high'?'P0':'P1'}}</span><h3>{{selected.title}}</h3><dl><dt>问题类型</dt><dd>{{labels[selected.type]}}</dd><dt>问题对象</dt><dd>{{selected.detail}}</dd><dt>判断依据</dt><dd>{{selected.evidence||'—'}}</dd><dt>发生时间</dt><dd>{{selected.occurred_at?new Date(selected.occurred_at).toLocaleString():'—'}}</dd></dl><el-button type="primary" @click="handleAction">{{selected.action_label||'立即处理'}}</el-button></div></template>
    </el-drawer>
  </div>
</template>

<style scoped>
.switch{display:flex;gap:4px}.switch button{padding:5px 8px;border:1px solid #e0e5ed;background:#fff;color:#778197;cursor:pointer}.switch button.active{color:#2658d7;border-color:#9fb3e7}.suite-toolbar{gap:10px}.suite-toolbar .el-select{width:210px}.suite-toolbar>span{align-self:center;margin-left:auto;color:#748097;font-size:11px}.suite-list li{cursor:pointer}.suite-list li:focus,.suite-list li:hover{outline:none;background:#f7f9fd}.detail-arrow{margin-left:12px;color:#245bd5;font-size:11px;white-space:nowrap}time{color:#8993a5;font-size:10px;white-space:nowrap}.alert-detail h3{margin:16px 0}.alert-detail dl{display:grid;grid-template-columns:72px 1fr;gap:13px 12px;margin:22px 0}.alert-detail dt{color:#8590a3}.alert-detail dd{margin:0;word-break:break-word}.alert-detail .el-button{width:100%}
</style>
