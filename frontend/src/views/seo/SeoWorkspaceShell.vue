<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fetchMe } from '../../api/auth'
import client from '../../api/client'
import { fetchSeoWorkbenchSites } from '../../api/moduleAssets'
import { session } from '../../store/session'
import { clearSeoSiteId, currentSeoSiteId } from './seoSiteContext'
import { canRenderSeoRoute, createSeoWorkspaceAccess, reconcileSeoRouteSite } from './seoWorkspaceAccess'

const route = useRoute()
const router = useRouter()
const mobileOpen = ref(false)
const accessState = ref('checking')
const accessError = ref('')
const validatedSites = ref([])
const selectableSiteStatuses = ref([])
const seoTenants = ref([])

const groups = [
  {
    label: '基础资产',
    index: '00',
    items: [
      { label: '网站管理', path: '/seo/sites', perm: 'seo.assets', mark: 'W' },
      { label: '品牌资产中心', path: '/seo/brand-assets', perm: 'seo.keywords', mark: 'B' },
    ],
  },
  {
    label: '今日概览',
    index: '01',
    items: [
      { label: 'SEO 工作台', path: '/seo/dashboard', perm: 'seo.dashboard', mark: '▦' },
      { label: '自动任务中心', path: '/seo/tasks', perm: 'seo.dashboard', mark: '◷' },
      { label: '异常提醒', path: '/seo/alerts', perm: 'seo.alerts', mark: '!' },
    ],
  },
  {
    label: '关键词资产',
    index: '02',
    items: [
      { label: '关键词管理', path: '/seo/keywords', perm: 'seo.keywords', mark: '⌕' },
      { label: '排名监控', path: '/seo/rankings', perm: 'seo.keywords', mark: '↗' },
      { label: '趋势总览', path: '/seo/trends', perm: 'seo.keywords', mark: '⌁' },
      { label: '竞品表现', path: '/seo/competitors', perm: 'seo.competitors', mark: '≋' },
    ],
  },
  {
    label: '内容增长',
    index: '03',
    items: [
      { label: '原创文章', path: '/seo/content/articles', perm: 'seo.content', mark: 'Aa' },
      { label: '文章改写', path: '/seo/content/rewrites', perm: 'seo.content', mark: '↻' },
      { label: '问答运营', path: '/seo/content/qa', perm: 'seo.content', mark: 'Q' },
      { label: '分发平台', path: '/seo/distribution', perm: 'seo.content', mark: '⇧' },
    ],
  },
  {
    label: '站内优化',
    index: '04',
    items: [
      { label: 'TDK / 站内优化', path: '/seo/site', perm: 'seo.site', mark: 'T' },
      { label: '内外链管理', path: '/seo/links', perm: 'seo.links', mark: '链' },
    ],
  },
]

const visibleGroups = computed(() => {
  const devMode = !session.isLoggedIn
  return groups
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => devMode || session.canView(item.perm)),
    }))
    .filter((group) => group.items.length)
})

const title = computed(() => route.meta.title || 'SEO 工作台')
const workflow = computed(() => route.meta.workflow || '搜索增长')
const immersive = computed(() => Boolean(route.meta.immersive))
const renderRoute = computed(() => canRenderSeoRoute(accessState.value, route.path))
const tenantName = computed(() => (
  seoTenants.value.find((tenant) => tenant.id === session.tenantId)?.name
    || session.tenants.find((tenant) => tenant.id === session.tenantId)?.name
    || '请选择客户'
))
const showTenantSelect = computed(() => session.isLoggedIn && (
  seoTenants.value.length > 1
  || (session.tenantId && !seoTenants.value.some((tenant) => tenant.id === session.tenantId))
))

function active(path) {
  if (path === '/seo/keywords') return route.path === '/seo/keywords' || route.path.startsWith('/seo/keywords/')
  if (path === '/seo/content/articles') return route.path === path || (route.path === '/seo/content/editor' && route.query.type !== 'rewrite')
  if (path === '/seo/content/rewrites') return route.path === path || (route.path === '/seo/content/editor' && route.query.type === 'rewrite')
  if (path === '/seo/content/qa') return route.path === path || route.path === '/seo/content/answer-editor'
  return route.path === path
}

function navigate(path) {
  mobileOpen.value = false
  router.push({ path, query: currentSeoSiteId.value ? { site_id: currentSeoSiteId.value } : {} })
}

function removeSiteQuery() {
  if (!route.query.site_id) return
  const query = { ...route.query }
  delete query.site_id
  void router.replace({ path: route.path, query })
}

const access = createSeoWorkspaceAccess({
  async fetchSites(tenantId) {
    const [siteResult, tenantResult] = await Promise.allSettled([
      fetchSeoWorkbenchSites(tenantId),
      client.get('/api/v1/auth/tenants', { params: { module: 'seo' } }),
    ])
    const tenants = tenantResult.status === 'fulfilled' ? (tenantResult.value.tenants || []) : []
    if (siteResult.status === 'rejected') {
      const error = siteResult.reason instanceof Error ? siteResult.reason : new Error('无法核对 SEO 访问范围')
      error.seoTenants = tenants
      throw error
    }
    return { ...siteResult.value, tenants }
  },
  reset() {
    accessState.value = 'checking'
    accessError.value = ''
    validatedSites.value = []
    selectableSiteStatuses.value = []
    seoTenants.value = []
    clearSeoSiteId()
    sessionStorage.removeItem('seo_pending_rewrite_source')
    sessionStorage.removeItem('seo_pending_rewrite_options')
    removeSiteQuery()
  },
  ready({ tenantId, sites, tenants, selectableStatuses, siteId }) {
    if (tenantId !== session.tenantId) return
    validatedSites.value = sites
    selectableSiteStatuses.value = selectableStatuses
    seoTenants.value = tenants
    currentSeoSiteId.value = siteId
    accessState.value = 'ready'
  },
  noSite({ tenantId, sites, tenants, selectableStatuses }) {
    if (tenantId !== session.tenantId) return
    validatedSites.value = sites
    selectableSiteStatuses.value = selectableStatuses
    seoTenants.value = tenants
    clearSeoSiteId()
    accessState.value = 'no-active-site'
  },
  unavailable({ tenantId, error, tenants }) {
    if (tenantId && tenantId !== session.tenantId) return
    validatedSites.value = []
    selectableSiteStatuses.value = []
    seoTenants.value = tenants
    clearSeoSiteId()
    accessError.value = error?.message || (tenantId ? '当前客户的 SEO 模块未启用或已过期' : '请先选择客户')
    accessState.value = 'unavailable'
  },
})

function validateCurrentScope() {
  const requestedSiteId = Number(route.query.site_id) || currentSeoSiteId.value || null
  void access.validate({ tenantId: session.tenantId, requestedSiteId })
}

async function refreshCurrentUser() {
  if (!session.isLoggedIn) return
  try {
    const response = await fetchMe()
    session.refreshUser(response.user)
  } catch { /* 登录失效由统一拦截器处理 */ }
}

async function onTenantChange(value) {
  if (!value || value === session.tenantId) return
  access.invalidate()
  clearSeoSiteId()
  sessionStorage.removeItem('seo_pending_rewrite_source')
  sessionStorage.removeItem('seo_pending_rewrite_options')
  const query = { ...route.query }
  delete query.site_id
  if (route.path.startsWith('/seo/keywords/')) {
    await router.replace('/seo/keywords')
  } else if (route.path === '/seo/content/editor') {
    await router.replace(route.query.type === 'rewrite' ? '/seo/content/rewrites' : '/seo/content/articles')
  } else if (route.path === '/seo/content/answer-editor') {
    await router.replace('/seo/content/qa')
  } else {
    await router.replace({ path: route.path, query })
  }
  session.setTenant(value)
}

watch(() => route.path, () => { mobileOpen.value = false })
watch(() => session.tenantId, validateCurrentScope, { immediate: true })
watch(() => session.authRevision, validateCurrentScope)
watch(() => session.tenantListRevision, validateCurrentScope)
watch(() => route.query.site_id, (value, previous) => {
  const requestedSiteId = Number(value) || null
  if (requestedSiteId === (Number(previous) || null)) return
  if (accessState.value === 'ready') {
    reconcileSeoRouteSite({
      sites: validatedSites.value,
      selectableStatuses: selectableSiteStatuses.value,
      requestedSiteId,
      selectSite: (siteId) => { currentSeoSiteId.value = siteId },
      replaceSiteQuery: (siteId) => {
        void router.replace({ path: route.path, query: { ...route.query, site_id: String(siteId) } })
      },
      noSite: () => {
        clearSeoSiteId()
        accessState.value = 'no-active-site'
      },
    })
    return
  }
  validateCurrentScope()
})
watch(currentSeoSiteId, (siteId) => {
  if (accessState.value !== 'ready' || (!session.tenantId && !siteId)) return
  const routeSiteId = Number(route.query.site_id) || null
  if (siteId === routeSiteId) return
  const query = { ...route.query }
  if (siteId) query.site_id = String(siteId)
  else delete query.site_id
  router.replace({ query })
})
onBeforeUnmount(access.dispose)
onMounted(refreshCurrentUser)
</script>

<template>
  <div class="seo-workspace">
    <button class="mobile-menu" type="button" aria-label="打开导航" @click="mobileOpen = !mobileOpen">
      <span /> <span /> <span />
    </button>
    <div v-if="mobileOpen" class="mobile-shade" @click="mobileOpen = false" />

    <aside class="seo-rail" :class="{ open: mobileOpen }">
      <div class="seo-brand" @click="navigate('/seo/dashboard')">
        <div class="brand-glyph" aria-hidden="true"><span>S</span></div>
        <div>
          <strong>SEO 工作台</strong>
          <small>搜索引擎获客</small>
        </div>
      </div>

      <nav class="seo-nav" aria-label="SEO 功能导航">
        <section v-for="group in visibleGroups" :key="group.label" class="nav-group">
          <div class="nav-label">{{ group.label }}</div>
          <button
            v-for="item in group.items"
            :key="item.path"
            type="button"
            :class="{ active: active(item.path) }"
            @click="navigate(item.path)"
          >
            <span class="nav-mark">{{ item.mark }}</span>
            <span>{{ item.label }}</span>
          </button>
        </section>
      </nav>

      <div class="rail-footer">
        <a href="/monitor/dashboard"><span>SEM</span>搜索广告工作台</a>
        <a href="/deal-sniper/geo/dashboard.html#/geo/overview"><span>GEO</span>生成式搜索工作台</a>
        <a href="/diagnostic-center/"><span>DX</span>诊断中心</a>
        <a class="portal-link" href="/deal-sniper/portal">← 返回平台门户</a>
      </div>
    </aside>

    <div class="seo-stage">
      <header v-if="!immersive" class="seo-topbar">
        <div class="page-identity">
          <small>{{ workflow }} /</small>
          <strong>{{ title }}</strong>
        </div>
        <div class="topbar-actions">
          <label v-if="showTenantSelect" class="tenant-select">
            <span>客户</span>
            <select :value="session.tenantId || ''" @change="onTenantChange(Number($event.target.value))">
              <option
                v-if="session.tenantId && !seoTenants.some((tenant) => tenant.id === session.tenantId)"
                :value="session.tenantId"
                disabled
              >{{ tenantName }}</option>
              <option v-for="tenant in seoTenants" :key="tenant.id" :value="tenant.id">{{ tenant.name }}</option>
            </select>
          </label>
          <div v-else class="tenant-chip"><span>客户</span><b>{{ tenantName }}</b></div>
          <div class="product-chip">SEO</div>
        </div>
      </header>
      <main class="seo-content">
        <section v-if="!renderRoute" class="scope-gate" role="status">
          <strong>{{ accessState === 'checking' ? '正在核对 SEO 访问范围' : accessState === 'no-active-site' ? '当前客户没有可用的 SEO 网站' : '当前客户无法显示 SEO 数据' }}</strong>
          <p>{{ accessState === 'checking' ? '完成模块有效期和网站归属校验后再显示数据。' : accessState === 'no-active-site' ? '只有 active 网站可以进入 SEO 数据页。' : accessError }}</p>
        </section>
        <!-- Child views do not exist before entitlement and site ownership are validated.
             Unmounting them also makes late responses unable to restore old customer data. -->
        <router-view v-else :key="`${session.tenantId}:${currentSeoSiteId || 'none'}:${route.path}`" />
      </main>
    </div>
  </div>
</template>

<style scoped>
.seo-workspace {
  --accent: #2658d7;
  --accent-soft: #edf3ff;
  --line: #e8eaf0;
  --paper: #f5f7fb;
  min-height: 100vh;
  background: var(--paper);
  color: #17233d;
  font-family: -apple-system, "PingFang SC", "Microsoft YaHei", "Segoe UI", Roboto, sans-serif;
}
.seo-rail {
  position: fixed;
  inset: 0 auto 0 0;
  z-index: 30;
  width: 216px;
  padding: 16px 10px;
  display: flex;
  flex-direction: column;
  gap: 1px;
  overflow-y: auto;
  background: #fff;
  color: #1e2330;
  border-right: 1px solid var(--line);
}
.seo-rail::-webkit-scrollbar { width: 6px; }
.seo-rail::-webkit-scrollbar-thumb { background: #e2e4ea; border-radius: 3px; }
.seo-brand {
  padding: 4px 8px 14px;
  display: flex;
  align-items: center;
  gap: 9px;
  cursor: pointer;
}
.brand-glyph {
  width: 28px;
  height: 28px;
  border-radius: 7px;
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
}
.brand-glyph span { color: white; font-size: 13px; font-weight: 800; }
.seo-brand strong { display: block; font-size: 15px; font-weight: 700; }
.seo-brand small { display: block; margin-top: 1px; color: #6b7280; font-size: 10.5px; font-weight: 500; }
.seo-nav { flex: 1; padding-bottom: 20px; }
.nav-group { margin: 0; }
.nav-label { padding: 13px 10px 5px; color: #9aa1ad; font-size: 10.5px; font-weight: 600; letter-spacing: .06em; }
.nav-group button {
  width: 100%;
  min-height: 34px;
  padding: 6px 10px;
  border: 0;
  border-radius: 8px;
  display: flex;
  align-items: center;
  gap: 9px;
  background: transparent;
  color: #5b6270;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  line-height: 1.35;
  text-align: left;
  transition: .15s ease;
}
.nav-group button:hover, .nav-group button.active { color: var(--accent); background: var(--accent-soft); }
.nav-group button.active { font-weight: 600; }
.nav-mark { width: 16px; color: inherit; font-size: 13.5px; text-align: center; }
.rail-footer { padding-top: 8px; border-top: 1px solid var(--line); }
.rail-footer a { min-height: 32px; padding: 6px 10px; display: flex; align-items: center; gap: 9px; border-radius: 8px; color: #6b7280; font-size: 12px; text-decoration: none; }
.rail-footer a:hover { color: var(--accent); background: var(--accent-soft); }
.rail-footer a span { width: 24px; color: #8b95a5; font-size: 10px; font-weight: 700; }
.rail-footer .portal-link { margin-top: 4px; border-top: 1px solid var(--line); border-radius: 0; color: #6b7280; }
.seo-stage { min-height: 100vh; margin-left: 216px; }
.seo-topbar {
  position: sticky;
  top: 0;
  z-index: 20;
  height: 60px;
  padding: 0 28px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #e1e7f0;
  background: #fff;
}
.page-identity { display: flex; align-items: baseline; gap: 9px; }
.page-identity small { color: #8390a5; font-size: 11px; }
.page-identity strong { font-size: 17px; }
.topbar-actions { display: flex; align-items: center; gap: 10px; }
.tenant-select, .tenant-chip { height: 34px; padding: 0 11px; border: 1px solid #dce3ee; border-radius: 8px; display: flex; align-items: center; gap: 8px; background: #fff; }
.tenant-select span, .tenant-chip span { color: #8995a7; font-size: 9px; font-weight: 800; letter-spacing: .08em; }
.tenant-select select { max-width: 190px; border: 0; outline: 0; background: transparent; color: #273654; font-weight: 700; }
.tenant-chip b { max-width: 190px; overflow: hidden; color: #273654; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.product-chip { width: 34px; height: 34px; border-radius: 9px; display: grid; place-items: center; background: #eaf0ff; color: #2c5bd2; font: 800 9px ui-monospace, monospace; }
.seo-content { min-width: 0; }
.scope-gate { margin: 28px; padding: 28px; border: 1px solid #dce3ee; border-radius: 12px; background: #fff; }
.scope-gate strong { color: #273654; font-size: 16px; }
.scope-gate p { margin: 10px 0 0; color: #6b7280; font-size: 13px; }
.mobile-menu { display: none; }
@media (max-width: 900px) {
  .seo-rail { transform: translateX(-105%); transition: transform .22s ease; }
  .seo-rail.open { transform: translateX(0); }
  .seo-stage { margin-left: 0; }
  .seo-topbar { padding-left: 64px; }
  .mobile-menu { position: fixed; top: 15px; left: 16px; z-index: 45; width: 34px; height: 32px; padding: 7px; border: 1px solid #dce3ee; border-radius: 8px; display: grid; align-content: space-around; background: white; }
  .mobile-menu span { height: 2px; border-radius: 2px; background: #263650; }
  .mobile-shade { position: fixed; inset: 0; z-index: 25; background: rgba(9,16,30,.38); }
}
@media (max-width: 620px) {
  .seo-topbar { padding-right: 12px; }
  .page-identity small, .tenant-chip span, .tenant-select span, .product-chip { display: none; }
  .tenant-select, .tenant-chip { max-width: 150px; }
}
</style>
