import { createApp } from 'vue'
import 'element-plus/dist/index.css'
import './style.css'
import App from './App.vue'
import router, { revalidateSessionRoute } from './router'
import { AUTH_CONTEXT_EVENT } from './store/sessionStorage'
import { installAuthContextRouting } from './router/authContextRouting'

installAuthContextRouting(window, AUTH_CONTEXT_EVENT, revalidateSessionRoute)

createApp(App).use(router).mount('#app')
