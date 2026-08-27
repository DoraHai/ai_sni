<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { session } from '../../store/session'
import { GEO_WORKBENCH_NAV } from '../../utils/geoPrototypeNavigation'

const route = useRoute()
const router = useRouter()
const mobileOpen = ref(false)
const tenantName = computed(() => {
  const tenant = session.tenants.find((item) => item.id === session.tenantId)
  if (tenant?.name) return tenant.name
  if (session.tenantId) return `客户 #${session.tenantId}`
  return '未选择客户'
})
const isActive = (item) => route.path === item.path || route.path.startsWith(`${item.path}/`)

function go(path) {
  mobileOpen.value = false
  router.push(path)
}

function onTenantChange(event) {
  const id = Number(event.target.value)
  if (!id || id === session.tenantId) return
  session.setTenant(id)
  if (route.path.startsWith('/geo/tasks/')) router.push('/geo/tasks')
}
</script>

<template>
  <div class="geo-shell">
    <button class="geo-mobile-toggle" type="button" aria-label="打开 GEO 导航" @click="mobileOpen = true">☰</button>
    <div v-if="mobileOpen" class="geo-mobile-mask" @click="mobileOpen = false" />
    <aside class="geo-shell-side" :class="{ 'is-open': mobileOpen }">
      <div class="geo-shell-brand">
        <span class="geo-shell-logo">G</span>
        <span class="geo-shell-brand-copy"><b>GEO 工作台</b><small>生成式引擎获客</small></span>
        <button class="geo-mobile-close" type="button" aria-label="关闭 GEO 导航" @click="mobileOpen = false">×</button>
      </div>
      <nav class="geo-shell-nav">
        <section v-for="group in GEO_WORKBENCH_NAV" :key="group.label">
          <h2>{{ group.label }}</h2>
          <button
            v-for="item in group.children"
            :key="item.path"
            type="button"
            :class="{ active: isActive(item) }"
            @click="go(item.path)"
          >
            <span class="geo-shell-item-icon">{{ item.icon }}</span>
            <span>{{ item.label }}</span>
          </button>
        </section>
      </nav>
      <div class="geo-shell-links">
        <a href="/diagnostic-center/"><span>!</span><span>诊断中心</span></a>
        <a href="/seo/dashboard"><span>S</span><span>SEO 内容工作台</span></a>
        <a href="/deal-sniper/portal"><span>←</span><span>返回平台门户</span></a>
      </div>
      <div class="geo-shell-tenant">
        <select
          v-if="session.tenants.length"
          :value="session.tenantId || ''"
          aria-label="切换客户"
          @change="onTenantChange"
        >
          <option v-for="tenant in session.tenants" :key="tenant.id" :value="tenant.id">{{ tenant.name }}</option>
        </select>
        <span v-else>{{ tenantName }}</span>
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
  min-height: 100vh;
  display: grid;
  grid-template-columns: 216px minmax(0, 1fr);
  background: #f6f7fb;
  color: #172033;
}
.geo-shell-side {
  position: sticky;
  top: 0;
  z-index: 30;
  height: 100vh;
  display: flex;
  flex-direction: column;
  padding: 16px 8px 0;
  background: #fff;
  border-right: 1px solid #e8eaf0;
}
.geo-shell-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 8px 14px;
}
.geo-shell-logo {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  flex: none;
  border-radius: 7px;
  color: #fff;
  font-size: 13px;
  font-weight: 750;
  background: linear-gradient(135deg, #7c3aed, #6d28d9);
}
.geo-shell-brand-copy b,
.geo-shell-brand-copy small {
  display: block;
}
.geo-shell-brand-copy b {
  color: #172033;
  font-size: 15px;
  line-height: 1.2;
}
.geo-shell-brand-copy small {
  margin-top: 1px;
  color: #8a94a6;
  font-size: 10.5px;
}
.geo-shell-nav {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 0 0 8px;
}
.geo-shell-nav h2 {
  margin: 0;
  padding: 13px 10px 5px;
  color: #9aa1ad;
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: .06em;
}
.geo-shell-nav button {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  padding: 7px 8px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: #5b6270;
  font: inherit;
  font-size: 13px;
  font-weight: 500;
  line-height: 1.3;
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
.geo-shell-links {
  display: grid;
  gap: 1px;
  padding: 8px 2px;
  border-top: 1px solid #e8eaf0;
}
.geo-shell-links a {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 8px;
  border-radius: 8px;
  color: #6b7280;
  font-size: 12px;
  text-decoration: none;
}
.geo-shell-links a span:first-child {
  width: 18px;
  text-align: center;
}
.geo-shell-links a:hover {
  background: #f5f0ff;
  color: #7c3aed;
}
.geo-shell-tenant {
  padding: 8px 10px 12px;
  border-top: 1px solid #e8eaf0;
  color: #6b7280;
  font-size: 12px;
}
.geo-shell-tenant select {
  width: 100%;
  padding: 7px 8px;
  border: 0;
  border-radius: 8px;
  outline: 0;
  background: transparent;
  color: #6b7280;
  font: inherit;
  cursor: pointer;
}
.geo-shell-tenant select:hover {
  background: #f5f0ff;
  color: #7c3aed;
}
.geo-shell-main,
.geo-shell-content {
  min-width: 0;
  min-height: 100vh;
}
.geo-shell-content {
  padding: 0;
}
.geo-mobile-toggle,
.geo-mobile-close {
  display: none;
}
@media (max-width: 900px) {
  .geo-shell {
    display: block;
  }
  .geo-shell-side {
    position: fixed;
    left: 0;
    top: 0;
    width: min(86vw, 260px);
    transform: translateX(-102%);
    transition: transform .2s ease;
    box-shadow: 16px 0 40px rgba(15, 23, 42, .18);
  }
  .geo-shell-side.is-open {
    transform: translateX(0);
  }
  .geo-mobile-mask {
    position: fixed;
    inset: 0;
    z-index: 20;
    background: rgba(15, 23, 42, .38);
  }
  .geo-mobile-toggle {
    position: fixed;
    left: 12px;
    top: 12px;
    z-index: 15;
    width: 36px;
    height: 36px;
    display: grid;
    place-items: center;
    border: 1px solid #e3e8f0;
    border-radius: 9px;
    background: #fff;
    color: #475467;
    font-size: 18px;
  }
  .geo-mobile-close {
    display: block;
    margin-left: auto;
    border: 0;
    background: transparent;
    color: #667085;
    font-size: 24px;
  }
}
</style>
