<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fetchMe, fetchTenants } from '../../api/auth'
import { session } from '../../store/session'

const route = useRoute()
const router = useRouter()
const mobileOpen = ref(false)

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
const tenantName = computed(() => (
  session.tenants.find((tenant) => tenant.id === session.tenantId)?.name || '请选择客户'
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
  router.push(path)
}

async function loadContext() {
  if (!session.isLoggedIn) return
  try {
    const [me, tenants] = await Promise.all([fetchMe(), fetchTenants('seo')])
    session.refreshUser(me.user)
    session.setTenants(tenants.tenants)
  } catch { /* 登录失效由统一拦截器处理 */ }
}

function onTenantChange(value) {
  if (!value || value === session.tenantId) return
  sessionStorage.removeItem('seo_pending_rewrite_source')
  sessionStorage.removeItem('seo_pending_rewrite_options')
  session.setTenant(value)
  if (route.path.startsWith('/seo/keywords/')) {
    router.replace('/seo/keywords')
  } else if (route.path === '/seo/content/editor') {
    router.replace(route.query.type === 'rewrite' ? '/seo/content/rewrites' : '/seo/content/articles')
  } else if (route.path === '/seo/content/answer-editor') {
    router.replace('/seo/content/qa')
  }
}

watch(() => route.path, () => { mobileOpen.value = false })
onMounted(loadContext)
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
          <label v-if="session.isLoggedIn && session.tenants.length > 1" class="tenant-select">
            <span>客户</span>
            <select :value="session.tenantId || ''" @change="onTenantChange(Number($event.target.value))">
              <option v-for="tenant in session.tenants" :key="tenant.id" :value="tenant.id">{{ tenant.name }}</option>
            </select>
          </label>
          <div v-else class="tenant-chip"><span>客户</span><b>{{ tenantName }}</b></div>
          <div class="product-chip">SEO</div>
        </div>
      </header>
      <main class="seo-content">
        <router-view />
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
