import { createApp, h } from 'vue'
import { createRouter, createWebHistory, RouterView } from 'vue-router'
import 'element-plus/theme-chalk/el-message.css'
import '../src/style.css'
import DiagnosisCenterView from '../src/views/diagnosis/DiagnosisCenterView.vue'
import { session } from '../src/store/session'

const devBypass = !session.isLoggedIn && import.meta.env.VITE_API_KEY && import.meta.env.DEV

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
