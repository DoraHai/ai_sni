import { createApp, h } from 'vue'
import { createRouter, createWebHistory, RouterView } from 'vue-router'
import 'element-plus/theme-chalk/el-message.css'
import '../src/style.css'
import DiagnosisCenterView from '../src/views/diagnosis/DiagnosisCenterView.vue'
import { session } from '../src/store/session'

// The standalone dev server only serves /diagnostic-center/, so its root-level
// /login redirect cannot be rendered locally. Keep production authentication
// intact while allowing the dedicated local preview to open directly.
const devBypass = import.meta.env.DEV

if (!session.isLoggedIn && !devBypass) {
  const redirect = encodeURIComponent('/diagnostic-center/')
  window.location.replace(`/login?redirect=${redirect}`)
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

  createApp({ render: () => h(RouterView) })
    .use(router)
    .mount('#app')
}
