import { createApp, h } from 'vue'
import { createRouter, createWebHistory, RouterView } from 'vue-router'
import 'element-plus/theme-chalk/base.css'
import 'element-plus/theme-chalk/el-overlay.css'
import 'element-plus/theme-chalk/el-icon.css'
import 'element-plus/theme-chalk/el-button.css'
import 'element-plus/theme-chalk/el-message.css'
import 'element-plus/theme-chalk/el-message-box.css'
import '../src/style.css'
import DiagnosisCenterView from '../src/views/diagnosis/DiagnosisCenterView.vue'
import { session } from '../src/store/session'

const hasDevKey = Boolean(import.meta.env.VITE_API_KEY && import.meta.env.DEV)
const devBypass = !session.isLoggedIn && hasDevKey

// Stale token without a usable session user: fall back to API Key in local demo
if (session.isLoggedIn && !session.user && hasDevKey) {
  session.logout()
}

if (!session.isLoggedIn && !devBypass && !hasDevKey) {
  // Mini-app has no /login route; show a clear message instead of blank redirect
  document.getElementById('app').innerHTML =
    '<main style="min-height:100vh;display:grid;place-items:center;font:600 14px sans-serif;color:#5f7478;background:#f4f7f6;padding:24px;text-align:center">' +
    '<div><p>请先登录主站，或在本地配置 VITE_API_KEY。</p>' +
    '<p style="margin-top:12px;font-weight:500">见 docs/LOCAL_GEO_DEMO.md</p></div></main>'
} else {
  const router = createRouter({
    history: createWebHistory('/diagnostic-center/'),
    routes: [
      { path: '/', component: DiagnosisCenterView },
      { path: '/:pathMatch(.*)*', redirect: '/' },
    ],
    scrollBehavior(to) {
      if (to.hash) return { el: to.hash, behavior: 'smooth' }
      return { top: 0 }
    },
  })

  // runtime-only Vue build: use render(), not template string
  createApp({ render: () => h(RouterView) })
    .use(router)
    .mount('#app')
}
