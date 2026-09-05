<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import GeoAccountBar from '../../components/GeoAccountBar.vue'
import { GEO_WORKBENCH_NAV } from '../../utils/geoPrototypeNavigation'

const route = useRoute()
const router = useRouter()
const mobileOpen = ref(false)
const geoNavCollapsed = ref(false)
const geoNavHover = ref(false)
const isMobile = ref(false)
const isEditor = computed(() => /^\/geo\/tasks\/[^/]+/.test(route.path))
const geoNavRail = computed(() => geoNavCollapsed.value && !geoNavHover.value && !isMobile.value)
const expandedGroups = ref({
  [GEO_WORKBENCH_NAV[0]?.label]: true,
})
const isActive = (item) => route.path === item.path || route.path.startsWith(`${item.path}/`)
const isGroupExpanded = (group) => Boolean(expandedGroups.value[group.label])
const isCurrentGroup = (group) => group.children.some((item) => isActive(item))

const groupIcons = {
  数据看板: '▦',
  智能监测: '✦',
  内容与信源: 'Aa',
  设置: '⚙',
}

function toggleGroup(label) {
  expandedGroups.value = {
    ...expandedGroups.value,
    [label]: !expandedGroups.value[label],
  }
}

watch(isEditor, (v) => { geoNavCollapsed.value = !!v }, { immediate: true })

function go(path) {
  mobileOpen.value = false
  router.push(path)
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
        <div class="geo-nav-section-title">GEO 增长工作流</div>
        <section v-for="(group, groupIndex) in GEO_WORKBENCH_NAV" :key="group.label" class="geo-nav-group">
          <button
            type="button"
            class="geo-nav-group-toggle"
            :class="{ current: isCurrentGroup(group) }"
            :aria-expanded="isGroupExpanded(group)"
            :aria-controls="`geo-nav-group-${groupIndex}`"
            @click="toggleGroup(group.label)"
          >
            <span class="geo-nav-group-icon" aria-hidden="true">{{ groupIcons[group.label] || '·' }}</span>
            <span class="geo-nav-group-name">{{ group.label }}</span>
            <span class="geo-nav-group-chevron" aria-hidden="true">›</span>
          </button>
          <Transition name="geo-nav-section">
            <div
              v-show="isGroupExpanded(group)"
              :id="`geo-nav-group-${groupIndex}`"
              class="geo-nav-group-items"
            >
              <button
                v-for="item in group.children"
                :key="item.path"
                type="button"
                class="geo-shell-nav-item"
                :class="{ active: isActive(item) }"
                :title="item.label"
                @click="go(item.path)"
              >
                <span class="geo-shell-item-icon">{{ item.icon }}</span>
                <span class="geo-nav-item-dot" aria-hidden="true" />
                <span class="geo-nav-item-label">{{ item.label }}</span>
              </button>
            </div>
          </Transition>
        </section>
      </nav>
      <div class="geo-shell-links">
        <a href="/monitor/dashboard" target="_top"><span>SEM</span><span class="geo-quick-label">搜索广告工作台</span></a>
        <a href="/seo/dashboard"><span>SEO</span><span class="geo-quick-label">SEO 内容工作台</span></a>
        <a href="/diagnostic-center/"><span>DX</span><span class="geo-quick-label">诊断中心</span></a>
        <a class="portal-link" href="/deal-sniper/portal" target="_top"><span>←</span><span class="geo-quick-label">返回平台门户</span></a>
      </div>
    </aside>
    <main class="geo-shell-main">
      <GeoAccountBar />
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
  grid-template-columns: 220px minmax(0, 1fr);
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
  padding: 0;
  background: rgba(255, 255, 255, .97);
  border-right: 1px solid #e7e3ec;
  box-shadow: 8px 0 26px rgba(49, 35, 66, .035);
}
.geo-shell-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 20px 18px 16px;
  border-bottom: 1px solid #e7e3ec;
  cursor: pointer;
}
.geo-shell-logo {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  flex: none;
  border-radius: 8px;
  color: #fff;
  font-size: 13px;
  font-weight: 800;
  background: linear-gradient(180deg, #9b72f2 0%, #7444d8 100%);
  box-shadow: 0 8px 20px rgba(116, 68, 216, .22);
}
.geo-shell-brand-copy b,
.geo-shell-brand-copy small {
  display: block;
}
.geo-shell-brand-copy b {
  color: #65419b;
  font-size: 14px;
  font-weight: 700;
  line-height: 1.2;
}
.geo-shell-brand-copy small {
  margin-top: 1px;
  color: #8b8494;
  font-size: 10.5px;
}
.geo-mobile-close,
.geo-mobile-toggle { display: none; }
.geo-shell-nav {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 14px 12px 24px;
}
.geo-nav-section-title {
  padding: 0 10px 8px;
  color: #8b8494;
  font-size: 11px;
  font-weight: 500;
  letter-spacing: .04em;
}
.geo-nav-group { margin-bottom: 6px; user-select: none; }
.geo-nav-group-toggle {
  width: 100%;
  min-height: 38px;
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  padding: 0 10px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: #535a66;
  font: inherit;
  font-size: 13px;
  font-weight: 500;
  text-align: left;
  cursor: pointer;
  transition: background .12s ease, border-color .12s ease, color .12s ease, box-shadow .12s ease;
}
.geo-nav-group-toggle:hover {
  background: #faf7fd;
  color: #282230;
}
.geo-nav-group-toggle.current {
  background: linear-gradient(90deg, #f6efff 0%, #fff 100%);
  border-color: #ddc9f2;
  color: #6f3eb1;
  box-shadow: inset 3px 0 0 #7c3aed;
  font-weight: 650;
}
.geo-nav-group-icon {
  width: 16px;
  height: 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  color: #766e80;
  font-size: 13px;
}
.geo-nav-group-toggle.current .geo-nav-group-icon {
  border-radius: 5px;
  background: #efe4ff;
  color: #7844bd;
}
.geo-nav-group-name { flex: 1; text-align: left; }
.geo-nav-group-chevron {
  display: inline-grid;
  place-items: center;
  color: #9c94a5;
  font-size: 12px;
  line-height: 1;
  transform: rotate(0deg);
  transition: transform .18s ease, color .18s ease;
}
.geo-nav-group-toggle[aria-expanded="true"] .geo-nav-group-chevron {
  color: #7c3aed;
  transform: rotate(90deg);
}
.geo-nav-group-items { overflow: hidden; padding: 4px 0 2px; }
.geo-nav-section-enter-active,
.geo-nav-section-leave-active {
  transition: opacity .16s ease, transform .16s ease;
  transform-origin: top;
}
.geo-nav-section-enter-from,
.geo-nav-section-leave-to {
  opacity: 0;
  transform: translateY(-3px);
}
.geo-shell-nav-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 32px;
  margin: 1px 0;
  padding: 0 10px 0 36px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: #85808c;
  font: inherit;
  font-size: 12px;
  font-weight: 500;
  text-align: left;
  cursor: pointer;
  white-space: nowrap;
}
.geo-shell-nav-item:hover {
  background: #faf6fe;
  color: #7741ba;
}
.geo-shell-nav-item.active {
  background: #f3eaff;
  color: #7741ba;
  font-weight: 600;
}
.geo-shell-item-icon { display: none; }
.geo-nav-item-dot {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: #cdc7d3;
  flex: none;
}
.geo-shell-nav-item.active .geo-nav-item-dot { background: #7c3aed; }
.geo-nav-item-label { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.geo-shell-links {
  padding: 12px 18px 18px;
  border-top: 1px solid #e7e3ec;
  background: rgba(255, 255, 255, .97);
}
.geo-shell-links a {
  min-height: 32px;
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 6px 8px;
  border-radius: 8px;
  color: #6b7280;
  font-size: 12px;
  text-decoration: none;
}
.geo-shell-links a > span:first-child {
  width: 24px;
  flex: none;
  color: #8b95a5;
  font-size: 10px;
  font-weight: 700;
}
.geo-shell-links a:hover {
  background: transparent;
  color: #7741ba;
}
.geo-shell-links .portal-link {
  margin-top: 4px;
  border-top: 1px solid #e8eaf0;
  border-radius: 0;
}
.geo-shell-side.is-rail { overflow: hidden; }
.geo-shell-side.is-rail .geo-shell-brand { justify-content: center; padding-left: 0; padding-right: 0; }
.geo-shell-side.is-rail .geo-shell-brand-copy,
.geo-shell-side.is-rail .geo-nav-section-title,
.geo-shell-side.is-rail .geo-nav-group-toggle,
.geo-shell-side.is-rail .geo-nav-item-label,
.geo-shell-side.is-rail .geo-quick-label { display: none; }
.geo-shell-side.is-rail .geo-shell-item-icon {
  width: 18px;
  height: 18px;
  display: grid;
  place-items: center;
  flex: none;
  font-size: 13px;
}
.geo-shell-side.is-rail .geo-nav-item-dot { display: none; }
.geo-shell-side.is-rail .geo-shell-nav button { justify-content: center; padding: 10px 0; }
.geo-shell-side.is-rail .geo-shell-links { padding: 8px 6px; }
.geo-shell-side.is-rail .geo-shell-links a { justify-content: center; gap: 0; padding: 6px 0; }
.geo-shell-side.is-rail .geo-shell-links a > span:first-child { width: auto; }
.geo-shell-main {
  min-width: 0;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
}
.geo-shell-content { min-height: 100%; padding: 0; }
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
