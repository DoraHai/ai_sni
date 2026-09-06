<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import logo from '../../assets/g-snipers-purple-logo.png'

const props = defineProps({ audit: Object, brand: Object, user: Object, loading: Boolean, activeAsset: String, assetTitle: String, competitor: Boolean, siteAudit: Boolean, pageCount: Number })
const emit = defineEmits(['new', 'export', 'asset', 'section'])
const root = ref(null)
const active = ref('flow-overview')
const tabs = computed(() => [
  { id: 'flow-overview', label: '概览' },
  { id: 'flow-diagnosis', label: 'SEO / GEO' },
  ...(!props.competitor ? [{ id: 'flow-brand', label: 'AI 品牌可见性' }] : []),
  { id: 'flow-action', label: '问题与建议' },
])
const website = computed(() => props.audit?.final_url || props.audit?.url || '')
const host = computed(() => { try { return new URL(website.value).hostname } catch { return website.value || '网址未提供' } })
const brandName = computed(() => props.audit?.snapshot?.brand_profile?.name || (!props.competitor && props.brand?.name) || props.audit?.page_title || host.value)
const userName = computed(() => props.user?.display_name || props.user?.username || '用户')
const date = computed(() => {
  const value = props.audit?.created_at
  if (!value || Number.isNaN(new Date(value).getTime())) return '诊断时间未提供'
  return new Intl.DateTimeFormat('zh-CN', { year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', hour12:false }).format(new Date(value))
})
function closeMenus() { root.value?.querySelectorAll('.rs-menu[open]').forEach(menu => { menu.open = false }) }
function chooseAsset(page) { closeMenus(); emit('asset', page) }
function chooseSection(id) { closeMenus(); active.value = id; emit('section', id) }
function outside(event) { if (!event.target.closest?.('.rs-menu')) closeMenus() }
function escape(event) {
  if (event.key !== 'Escape') return
  const menu = root.value?.querySelector('.rs-menu[open]')
  menu?.querySelector('summary')?.focus(); closeMenus()
}
let frame = 0
function updateSection() {
  frame = 0
  if (props.activeAsset || !props.audit) return
  const edge = (root.value?.querySelector('.rs-tabs')?.getBoundingClientRect().bottom || 120) + 24
  let current = tabs.value[0].id
  for (const tab of tabs.value) {
    const section = document.getElementById(tab.id)
    if (section && section.getBoundingClientRect().top <= edge) current = tab.id
  }
  active.value = current
}
function onScroll() { if (!frame) frame = requestAnimationFrame(updateSection) }
watch(() => [props.activeAsset, props.audit?.id], async () => { await nextTick(); updateSection() })
onMounted(() => { window.addEventListener('scroll', onScroll, { passive:true }); window.addEventListener('resize', onScroll); document.addEventListener('click', outside); document.addEventListener('keydown', escape); updateSection() })
onBeforeUnmount(() => { cancelAnimationFrame(frame); window.removeEventListener('scroll', onScroll); window.removeEventListener('resize', onScroll); document.removeEventListener('click', outside); document.removeEventListener('keydown', escape) })
</script>

<template>
  <div ref="root" class="report-shell">
    <header class="rs-global">
      <div class="rs-global-inner">
        <a class="rs-logo" href="/deal-sniper/portal"><img :src="logo" alt=""><span>获客狙击手<small>G-SNIPERS</small></span></a>
        <div class="rs-tools">
          <button class="rs-desktop" :disabled="loading" @click="emit('new')">新建诊断</button>
          <button class="rs-desktop rs-export" :disabled="!audit" @click="emit('export')">导出报告</button>
          <details class="rs-menu">
            <summary aria-label="诊断设置与操作"><span class="rs-desktop">诊断设置</span><span class="rs-mobile">操作</span><span aria-hidden="true">⌄</span></summary>
            <div class="rs-menu-panel">
              <div class="rs-mobile rs-mobile-actions"><button :disabled="loading" @click="closeMenus(); emit('new')">新建诊断</button><button :disabled="!audit" @click="closeMenus(); emit('export')">导出报告</button></div>
              <button @click="chooseAsset('brand')">品牌资料</button>
              <button @click="chooseAsset('audience')">目标用户</button>
              <p>产品工作区</p>
              <a href="/deal-sniper/sem/dashboard">SEM 模块</a>
              <a href="/deal-sniper/seo/dashboard">SEO 模块</a>
              <a href="/deal-sniper/geo/dashboard">GEO 模块</a>
            </div>
          </details>
          <details class="rs-menu">
            <summary class="rs-user" :aria-label="`${userName}的用户菜单`">{{ Array.from(userName)[0].toUpperCase() }}</summary>
            <div class="rs-menu-panel"><p>{{ userName }}</p><a href="/deal-sniper/hub/dashboard">全域驾驶舱</a><a href="/deal-sniper/portal">返回平台</a></div>
          </details>
        </div>
      </div>
    </header>

    <header class="rs-report-header" :class="{ 'rs-report-identity': !activeAsset }">
      <template v-if="!activeAsset">
        <p class="rs-brand-name">{{ brandName }}</p>
        <h1>网站诊断报告</h1>
        <div class="rs-metadata">
          <span class="rs-host">{{ host }}</span>
          <span class="rs-print-url">{{ website }}</span>
          <span class="rs-status"><i :class="{ pending: loading || !audit }" />{{ loading ? '诊断进行中' : audit ? (competitor ? '竞品公开检测完成' : '诊断完成') : '尚未诊断' }}</span>
          <time v-if="audit?.created_at" :datetime="audit.created_at">{{ date }}</time><span v-else>{{ date }}</span>
          <span>{{ siteAudit ? `全站抽样 ${pageCount} 页` : '单页诊断' }}</span>
          <span>{{ audit?.rule_version ? `规则版本 v${audit.rule_version}` : '规则版本未提供' }}</span>
        </div>
      </template>
      <template v-else><p class="rs-brand-name">诊断设置</p><h1>{{ assetTitle }}</h1><button class="rs-return" @click="chooseSection('flow-overview')">← 返回诊断报告</button></template>
    </header>

    <nav v-if="audit && !activeAsset" class="rs-tabs" aria-label="报告章节">
      <div class="rs-tabs-inner"><a v-for="tab in tabs" :key="tab.id" :href="`#${tab.id}`" :aria-current="active === tab.id ? 'location' : undefined" :class="{ active:active === tab.id }" @click.prevent="chooseSection(tab.id)">{{ tab.label }}</a></div>
    </nav>
    <slot />
  </div>
</template>

<style scoped>
.report-shell { --rs-purple:#793bd7; --rs-border:#e6e4ea; --rs-muted:#706d79; --rs-header-height:68px; min-width:0; }
.rs-global { height:var(--rs-header-height); position:sticky; top:0; z-index:60; background:#fff; border-bottom:1px solid var(--rs-border); }
.rs-global-inner { max-width:1360px; height:100%; margin:auto; padding:0 40px; display:flex; align-items:center; justify-content:space-between; gap:20px; }
.rs-logo { display:flex; align-items:center; gap:10px; color:#28252e; text-decoration:none; font-size:16px; font-weight:700; white-space:nowrap; }
.rs-logo img { width:36px; height:36px; object-fit:contain; }
.rs-logo small { display:block; color:var(--rs-muted); font-size:9px; letter-spacing:.12em; margin-top:2px; }
.rs-tools { display:flex; align-items:center; gap:12px; }
button, summary { font:inherit; cursor:pointer; }
.rs-tools > button, .rs-menu > summary { min-height:36px; border:1px solid transparent; border-radius:6px; background:#fff; color:#494451; padding:8px 12px; font-size:13px; }
.rs-tools > .rs-export { border-color:#ddd4eb; color:var(--rs-purple); }
button:disabled { opacity:.45; cursor:not-allowed; }
button:hover:not(:disabled), summary:hover { background:#f5f2f9; }
:is(a,button,summary):focus-visible { outline:2px solid var(--rs-purple); outline-offset:3px; }
.rs-menu { position:relative; }
.rs-menu > summary { list-style:none; display:flex; align-items:center; gap:8px; }
summary::-webkit-details-marker { display:none; }
.rs-menu > .rs-user { border-radius:50%; width:36px; justify-content:center; background:#f0e9f9; color:#6932b2; font-weight:700; }
.rs-menu-panel { position:absolute; top:calc(100% + 10px); right:0; width:204px; border:1px solid var(--rs-border); border-radius:8px; padding:8px; background:#fff; box-shadow:0 8px 24px #26202f12; }
.rs-menu-panel :is(a,button) { display:block; width:100%; padding:10px 12px; border:0; text-align:left; text-decoration:none; background:transparent; color:#45404e; font-size:13px; border-radius:4px; }
.rs-menu-panel :is(a,button):hover { background:#f5f2f9; color:var(--rs-purple); }
.rs-menu-panel p { margin:4px 4px 6px; padding:10px 8px 6px; border-top:1px solid var(--rs-border); font-size:11px; color:var(--rs-muted); overflow-wrap:anywhere; }
.rs-report-header { max-width:1360px; margin:auto; padding:30px 40px 26px; color:#28252e; }
.rs-brand-name { font-size:15px; font-weight:600; margin:0 0 8px; overflow-wrap:anywhere; }
.rs-report-header h1 { font-size:32px; line-height:1.3; letter-spacing:-.025em; margin:0 0 18px; font-weight:650; }
.rs-metadata { display:flex; align-items:center; flex-wrap:wrap; gap:8px 18px; color:var(--rs-muted); font-size:12px; line-height:1.6; }
.rs-host { color:#3d3747; overflow-wrap:anywhere; }
.rs-status { display:inline-flex; align-items:center; gap:6px; }
.rs-status i { width:6px; height:6px; border-radius:50%; background:#219574; }
.rs-status i.pending { background:#ac7b27; }
.rs-return { border:0; padding:8px 0; background:transparent; color:var(--rs-purple); font-size:13px; }
.rs-tabs { position:sticky; top:var(--rs-header-height); z-index:50; background:#fff; border-block:1px solid var(--rs-border); }
.rs-tabs-inner { max-width:1360px; margin:auto; padding:0 40px; display:flex; gap:32px; overflow-x:auto; scrollbar-width:thin; }
.rs-tabs a { flex:none; display:flex; align-items:center; min-height:52px; border-bottom:2px solid transparent; color:#66616f; text-decoration:none; font-size:14px; font-weight:500; }
.rs-tabs a:hover { color:var(--rs-purple); }
.rs-tabs a.active { color:var(--rs-purple); border-bottom-color:var(--rs-purple); font-weight:650; }
.rs-mobile { display:none; }
.rs-print-url { display:none; overflow-wrap:anywhere; }
/* Keep report identity for export and headings for settings, not the report screen. */
@media screen {
  .rs-report-identity, .rs-tabs { display:none; }
}
@media(max-width:700px) {
  .report-shell { --rs-header-height:64px; }
  .rs-global-inner { padding-inline:18px; gap:10px; }
  .rs-logo { font-size:14px; gap:7px; }
  .rs-logo img { width:30px; height:30px; }
  .rs-tools { gap:4px; }
  .rs-desktop, .rs-tools > .rs-desktop { display:none; }
  .rs-mobile { display:block; }
  .rs-report-header { padding:24px 20px; }
  .rs-report-header h1 { font-size:28px; }
  .rs-metadata { gap:7px 14px; }
  .rs-tabs-inner { padding-inline:20px; gap:26px; }
  .rs-tabs a { min-height:48px; font-size:13px; }
}
@media print {
  .rs-global,.rs-tabs,.rs-return { display:none!important; }
  .rs-report-header { max-width:none; padding:0 0 16px; margin-bottom:16px; border-bottom:1px solid #ddd; }
  .rs-report-header h1 { font-size:24px; }
  .rs-metadata { color:#444; font-size:10px; }
  .rs-host { display:none; }
  .rs-print-url { display:inline; }
}
</style>
