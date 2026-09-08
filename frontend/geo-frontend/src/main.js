import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import '../../src/style.css'
import '../../src/styles/geo-page.css'
import './standalone.css'
import App from './App.vue'
import router, { revalidateSessionRoute } from './router'
import { installGeoAuthContextRouting } from './authRouteDecision'
import { AUTH_CONTEXT_EVENT } from '../../src/store/session'

installGeoAuthContextRouting(window, {
  eventName: AUTH_CONTEXT_EVENT,
  revalidate: revalidateSessionRoute,
  reload: () => window.location.reload(),
})

createApp(App).use(ElementPlus, { locale: zhCn }).use(router).mount('#app')
