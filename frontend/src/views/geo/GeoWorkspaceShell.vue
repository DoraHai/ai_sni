<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { GEO_WORKBENCH_NAV } from '../../utils/geoPrototypeNavigation'

const route = useRoute()
const router = useRouter()
const mobileOpen = ref(false)
const pageTitle = computed(() => route.meta.title || 'GEO 工作台')
const isActive = (item) => route.path === item.path || route.path.startsWith(`${item.path}/`)

function go(path) {
  mobileOpen.value = false
  router.push(path)
}
</script>

<template>
  <div class="geo-shell">
    <button class="geo-mobile-toggle" type="button" aria-label="打开 GEO 导航" @click="mobileOpen = true">☰</button>
    <div v-if="mobileOpen" class="geo-mobile-mask" @click="mobileOpen = false" />
    <aside class="geo-shell-side" :class="{ 'is-open': mobileOpen }">
      <div class="geo-shell-brand">
        <span class="geo-shell-logo">G</span>
        <span><b>GEO 工作台</b><small>生成式引擎获客</small></span>
        <button class="geo-mobile-close" type="button" aria-label="关闭 GEO 导航" @click="mobileOpen = false">×</button>
      </div>
      <nav class="geo-shell-nav">
        <section v-for="group in GEO_WORKBENCH_NAV" :key="group.label">
          <h2>{{ group.label }}</h2>
          <button v-for="item in group.children" :key="item.path" type="button" :class="{ active: isActive(item) }" @click="go(item.path)">
            <span class="geo-shell-item-icon">{{ item.icon }}</span><span>{{ item.label }}</span>
          </button>
        </section>
      </nav>
      <div class="geo-shell-links">
        <a href="/diagnostic-center/">!　诊断中心</a>
        <a href="/seo/dashboard">S　SEO 内容工作台</a>
        <a href="/deal-sniper/portal">←　返回平台门户</a>
      </div>
    </aside>
    <main class="geo-shell-main">
      <header class="geo-shell-header">
        <div><small>GEO 工作台</small><strong>{{ pageTitle }}</strong></div>
        <span class="geo-shell-status"><i />独立 GEO 工作区</span>
      </header>
      <div class="geo-shell-content"><router-view /></div>
    </main>
  </div>
</template>

<style src="../../styles/geo-page.css"></style>
<style src="../../styles/geo-v2.css"></style>
<style src="../../styles/geo-dashboard.css"></style>
<style scoped>
.geo-shell { min-height: 100vh; display: grid; grid-template-columns: 260px minmax(0, 1fr); background: #f5f7fb; color: #172033; }
.geo-shell-side { position: sticky; top: 0; height: 100vh; display: flex; flex-direction: column; background: #fff; border-right: 1px solid #e7ebf2; z-index: 30; }
.geo-shell-brand { min-height: 88px; display: flex; align-items: center; gap: 12px; padding: 18px 20px; border-bottom: 1px solid #edf0f5; }
.geo-shell-brand b, .geo-shell-brand small { display: block; }
.geo-shell-brand b { font-size: 18px; }
.geo-shell-brand small { margin-top: 4px; color: #8a94a6; }
.geo-shell-logo { width: 42px; height: 42px; display: grid; place-items: center; flex: none; border-radius: 12px; color: #fff; font-weight: 800; background: linear-gradient(135deg, #2563eb, #6d28d9); box-shadow: 0 8px 22px rgba(79, 70, 229, .22); }
.geo-shell-nav { flex: 1; overflow: auto; padding: 12px 12px 18px; }
.geo-shell-nav section + section { margin-top: 10px; }
.geo-shell-nav h2 { margin: 12px 10px 7px; color: #98a2b3; font-size: 12px; letter-spacing: .04em; }
.geo-shell-nav button { width: 100%; min-height: 42px; display: flex; align-items: center; gap: 11px; padding: 9px 12px; border: 0; border-radius: 10px; background: transparent; color: #536078; font: inherit; font-weight: 650; text-align: left; cursor: pointer; }
.geo-shell-nav button:hover { background: #f7f5ff; color: #6d28d9; }
.geo-shell-nav button.active { background: #f0edff; color: #6d28d9; }
.geo-shell-item-icon { width: 22px; color: #7b879a; text-align: center; }
.geo-shell-links { display: grid; gap: 3px; padding: 12px; border-top: 1px solid #edf0f5; }
.geo-shell-links a { padding: 9px 10px; border-radius: 8px; color: #667085; font-size: 13px; text-decoration: none; }
.geo-shell-links a:hover { background: #f7f8fb; color: #344054; }
.geo-shell-main { min-width: 0; }
.geo-shell-header { min-height: 72px; display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 12px 28px; background: #fff; border-bottom: 1px solid #e7ebf2; }
.geo-shell-header small, .geo-shell-header strong { display: block; }
.geo-shell-header small { color: #98a2b3; font-size: 12px; }
.geo-shell-header strong { margin-top: 4px; font-size: 17px; }
.geo-shell-status { display: inline-flex; align-items: center; gap: 7px; padding: 7px 11px; border: 1px solid #dce6f4; border-radius: 999px; color: #58708f; font-size: 12px; font-weight: 700; }
.geo-shell-status i { width: 8px; height: 8px; border-radius: 50%; background: #20b486; box-shadow: 0 0 0 4px rgba(32, 180, 134, .12); }
.geo-shell-content { min-width: 0; padding: 20px 26px 36px; }
.geo-mobile-toggle, .geo-mobile-close { display: none; }
@media (max-width: 900px) {
  .geo-shell { display: block; }
  .geo-shell-side { position: fixed; left: 0; top: 0; width: min(86vw, 300px); transform: translateX(-102%); transition: transform .2s ease; box-shadow: 16px 0 40px rgba(15, 23, 42, .18); }
  .geo-shell-side.is-open { transform: translateX(0); }
  .geo-mobile-mask { position: fixed; inset: 0; z-index: 20; background: rgba(15, 23, 42, .38); }
  .geo-mobile-toggle { display: grid; place-items: center; position: fixed; left: 12px; top: 15px; z-index: 15; width: 40px; height: 40px; border: 1px solid #e3e8f0; border-radius: 10px; background: #fff; color: #475467; font-size: 20px; }
  .geo-mobile-close { display: block; margin-left: auto; border: 0; background: transparent; color: #667085; font-size: 26px; }
  .geo-shell-header { padding-left: 64px; }
  .geo-shell-status { display: none; }
  .geo-shell-content { padding: 16px 12px 28px; }
}
</style>
