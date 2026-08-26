import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import '../src/style.css'
import LoginView from '../src/views/LoginView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: LoginView },
    { path: '/:pathMatch(.*)*', redirect: '/login' },
  ],
})

router.afterEach(() => {
  document.title = '登录 · G-Snipers 获客狙击手'
})

createApp(LoginView).use(ElementPlus, { locale: zhCn }).use(router).mount('#app')
