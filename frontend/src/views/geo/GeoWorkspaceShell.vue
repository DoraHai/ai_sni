<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { session } from '../../store/session'
import { GEO_WORKBENCH_NAV } from '../../utils/geoPrototypeNavigation'

const route = useRoute()
const router = useRouter()
const mobileOpen = ref(false)
const tenantPopoverOpen = ref(false)
const geoNavCollapsed = ref(false)
const geoNavHover = ref(false)
const isMobile = ref(false)
const isEditor = computed(() => /^\/geo\/tasks\/[^/]+/.test(route.path))
const geoNavRail = computed(() => geoNavCollapsed.value && !geoNavHover.value && !isMobile.value)
const tenantName = computed(() => {
  const tenant = session.tenants.find((item) => item.id === session.tenantId)
  if (tenant?.name) return tenant.name
  if (session.tenantId) return `客户 #${session.tenantId}`
  return '未选择客户'
})
const isActive = (item) => route.path === item.path || route.path.startsWith(`${item.path}/`)

watch(isEditor, (v) => { geoNavCollapsed.value = !!v }, { immediate: true })

function go(path) {
  mobileOpen.value = false
  router.push(path)
}

function onTenantPick(id) {
  tenantPopoverOpen.value = false
  if (!id || id === session.tenantId) return
  session.setTenant(id)
  if (route.path.startsWith('/geo/tasks/')) router.push('/geo/tasks')
}

function tenantInitials(tenant) {
  const trimmed = String(tenant?.name || '').trim()
  if (!trimmed) return '—'
  const ascii = trimmed.match(/[A-Za-z]+/g)?.join('')
  if (ascii && /^[A-Za-z0-9_-]/.test(trimmed)) return ascii.slice(0, 2).toUpperCase()
  return Array.from(trimmed).slice(0, 2).join('')
}

function tenantTone(id) {
  return ['blue', 'green', 'amber', 'violet', 'red'][Math.abs(Number(id) || 0) % 5]
}

function onGeoNavEnter() {
  if (geoNavCollapsed.value) geoNavHover.value = true
}
function onGeoNavLeave() { geoNavHover.value = false }
function toggleGeoNav() {
  geoNavCollapsed.value = !geoNavCollapsed.value
  geoNavHover.value = false
}

function onGeoEditorFocus(ev) {
  if (ev.detail) {
    geoNavCollapsed.value = true
    geoNavHover.value = false
  }
}

let mobileMq
function syncMobile() {
  isMobile.value = mobileMq?.matches ?? false
  if (!isMobile.value) mobileOpen.value = false
}

onMounted(() => {
  window.addEventListener('geo-editor-focus', onGeoEditorFocus)
  mobileMq = window.matchMedia('(max-width: 767px)')
  syncMobile()
  mobileMq.addEventListener('change', syncMobile)
})
onUnmounted(() => {
  window.removeEventListener('geo-editor-focus', onGeoEditorFocus)
  mobileMq?.removeEventListener('change', syncMobile)
})
</script>

<template>
  <div class="geo-shell" :class="{ 'is-rail': geoNavRail }">
    <button class="geo-mobile-toggle" type="button" aria-label="打开 GEO 导航" @click="mobileOpen = true">☰</button>
    <div v-if="mobileOpen" class="geo-mobile-mask" @click="mobileOpen = false" />
    <aside
      class="geo-shell-side"
      :class="{ 'is-open': mobileOpen, 'is-rail': geoNavRail }"
      @mouseenter="onGeoNavEnter"
      @mouseleave="onGeoNavLeave"
    >
      <div class="geo-shell-brand" title="展开或收起导航" @click="toggleGeoNav">
        <span class="geo-shell-logo">G</span>
        <span class="geo-shell-brand-copy"><b>GEO 工作台</b><small>生成式引擎获客</small></span>
        <button class="geo-mobile-close" type="button" aria-label="关闭 GEO 导航" @click.stop="mobileOpen = false">×</button>
      </div>
      <nav class="geo-shell-nav">
        <section v-for="group in GEO_WORKBENCH_NAV" :key="group.label">
          <h2>{{ group.label }}</h2>
          <button
            v-for="item in group.children"
            :key="item.path"
            type="button"
            :class="{ active: isActive(item) }"
            :title="item.label"
            @click="go(item.path)"
          >
            <span class="geo-shell-item-icon">{{ item.icon }}</span>
            <span class="geo-nav-label">{{ item.label }}</span>
          </button>
        </section>
      </nav>
      <div class="geo-side-foot">
        <el-popover
          v-if="session.tenants.length"
          v-model:visible="tenantPopoverOpen"
          placement="top-start"
          :width="286"
          trigger="click"
          popper-class="tenant-popover"
        >
          <template #reference>
            <button type="button" class="geo-tenant" :title="tenantName">
              {{ geoNavRail ? tenantInitials({ name: tenantName }) : (tenantName + ' ▾') }}
            </button>
          </template>
          <div class="tenant-panel">
            <div class="tenant-section-title">切换客户</div>
            <button
              v-for="t in session.tenants"
              :key="'g-'+t.id"
              class="tenant-option"
              :class="{ active: t.id === session.tenantId }"
              type="button"
              @click="onTenantPick(t.id)"
            >
              <span class="tenant-avatar" :class="'tone-' + tenantTone(t.id)">{{ tenantInitials(t) }}</span>
              <span class="tenant-copy">
                <span class="tenant-title">{{ t.name }}</span>
                <span class="tenant-meta">独立账户数据 · 客户 ID {{ t.id }}</span>
              </span>
              <span v-if="t.id === session.tenantId" class="tenant-check">✓</span>
            </button>
          </div>
        </el-popover>
        <button v-else type="button" class="geo-tenant" disabled>选择客户</button>
      </div>
    </aside>
    <main class="geo-shell-main">
      <div class="geo-shell-content"><router-view /></div>
    </main>
  </div>
</template>

<style src="../../styles/geo-page.css"></style>
<style src="../../styles/geo-v2.css"></style>
<style src="../../styles/geo-dashboard.css"></style>
<style scoped>
.geo-shell {
  height: 100%;
  min-height: 0;
  overflow: hidden;
  display: grid;
  grid-template-columns: 216px minmax(0, 1fr);
  background: #f6f7fb;
  color: #172033;
}
.geo-shell.is-rail { grid-template-columns: 72px minmax(0, 1fr); }
.geo-shell-side {
  position: sticky;
  top: 0;
  z-index: 30;
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #fff;
  border-right: 1px solid #e8eaf0;
  padding: 16px 8px 0;
}
.geo-shell-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 8px 14px;
  cursor: pointer;
}
.geo-shell-logo {
  width: 28px;
  height: 28px;
  border-radius: 7px;
  display: grid;
  place-items: center;
  flex: none;
  background: linear-gradient(135deg, #7c3aed, #6d28d9);
  color: #fff;
  font-size: 13px;
  font-weight: 800;
}
.geo-shell-brand-copy { min-width: 0; display: grid; }
.geo-shell-brand-copy b { font-size: 15px; line-height: 1.2; }
.geo-shell-brand-copy small { color: #9aa1ad; font-size: 10.5px; }
.geo-mobile-close,
.geo-mobile-toggle { display: none; }
.geo-shell-nav { flex: 1; overflow: auto; padding-bottom: 8px; }
.geo-shell-nav h2 {
  margin: 0;
  padding: 13px 10px 5px;
  color: #9aa1ad;
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: .06em;
}
.geo-shell-nav button {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  margin: 0;
  padding: 7px 8px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: #5b6270;
  font-size: 13px;
  font-weight: 500;
  text-align: left;
  cursor: pointer;
  white-space: nowrap;
}
.geo-shell-nav button:hover,
.geo-shell-nav button.active {
  background: #f5f0ff;
  color: #7c3aed;
  font-weight: 600;
}
.geo-shell-item-icon {
  width: 18px;
  height: 18px;
  display: grid;
  place-items: center;
  flex: none;
  font-size: 13px;
}
.geo-side-foot {
  padding: 8px 10px 12px;
  border-top: 1px solid #e8eaf0;
}
.geo-tenant {
  display: block;
  width: 100%;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: #6b7280;
  font-size: 12px;
  text-align: left;
  padding: 8px 10px;
  cursor: pointer;
}
.geo-tenant:hover { background: #f5f0ff; color: #7c3aed; }
.geo-shell-side.is-rail { overflow: hidden; }
.geo-shell-side.is-rail .geo-shell-brand { justify-content: center; padding-left: 0; padding-right: 0; }
.geo-shell-side.is-rail .geo-shell-brand-copy,
.geo-shell-side.is-rail .geo-shell-nav h2,
.geo-shell-side.is-rail .geo-nav-label { display: none; }
.geo-shell-side.is-rail .geo-shell-nav button { justify-content: center; padding: 10px 0; }
.geo-shell-side.is-rail .geo-side-foot { padding: 8px 6px 12px; }
.geo-shell-side.is-rail .geo-tenant { text-align: center; padding: 8px 0; font-weight: 650; }
.geo-shell-main {
  min-width: 0;
  min-height: 0;
  overflow: auto;
}
.geo-shell-content { min-height: 100%; }
.geo-mobile-mask { display: none; }
@media (max-width: 767px) {
  .geo-shell,
  .geo-shell.is-rail { grid-template-columns: 1fr; }
  .geo-mobile-toggle {
    display: inline-flex;
    position: fixed;
    top: 12px;
    left: 12px;
    z-index: 40;
    width: 36px;
    height: 36px;
    border: 1px solid #e8eaf0;
    border-radius: 8px;
    background: #fff;
  }
  .geo-mobile-close { display: inline-flex; margin-left: auto; border: 0; background: transparent; font-size: 22px; }
  .geo-mobile-mask {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 45;
    background: rgba(15, 23, 42, .35);
  }
  .geo-shell-side {
    position: fixed;
    left: 0;
    top: 0;
    z-index: 50;
    width: min(86vw, 280px);
    transform: translateX(-110%);
    transition: transform .18s ease;
  }
  .geo-shell-side.is-open { transform: none; }
}
</style>
<style>
.tenant-popover.el-popper {
  padding: 0;
  border: 1px solid #e5ebf2;
  border-radius: 8px;
  box-shadow: 0 16px 38px rgba(15, 23, 42, 0.13);
  overflow: hidden;
}
.tenant-panel { padding: 13px 8px 10px; background: #fff; }
.tenant-section-title {
  margin: 0 0 6px;
  padding: 0 9px;
  color: #9aa6b5;
  font-size: 11px;
  font-weight: 700;
}
.tenant-option {
  width: 100%;
  min-height: 44px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr) 14px;
  align-items: center;
  gap: 9px;
  padding: 7px 9px;
  text-align: left;
  cursor: pointer;
  color: #1f2937;
}
.tenant-option:hover { background: #f6f9fd; }
.tenant-option.active { background: #edf4ff; }
.tenant-avatar {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 11px;
  font-weight: 700;
}
.tenant-avatar.tone-blue { background: #2069b4; }
.tenant-avatar.tone-green { background: #26a77a; }
.tenant-avatar.tone-amber { background: #ca8321; }
.tenant-avatar.tone-violet { background: #7657c8; }
.tenant-avatar.tone-red { background: #e55353; }
.tenant-copy { min-width: 0; display: grid; gap: 2px; }
.tenant-title {
  font-size: 13px;
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tenant-meta { color: #8a94a3; font-size: 11px; }
.tenant-check { color: #7c3aed; font-weight: 700; }
</style>
