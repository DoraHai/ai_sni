import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import './style.css'
import SeoApp from './SeoApp.vue'
import router from './seo-router'

createApp(SeoApp).use(ElementPlus, { locale: zhCn }).use(router).mount('#app')
