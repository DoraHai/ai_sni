import { createApp } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCheckbox,
  ElCheckboxGroup,
  ElDatePicker,
  ElDialog,
  ElDrawer,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElInput,
  ElInputNumber,
  ElOption,
  ElPagination,
  ElProgress,
  ElRadioButton,
  ElRadioGroup,
  ElSegmented,
  ElSelect,
  ElStep,
  ElSteps,
  ElSwitch,
  ElTable,
  ElTableColumn,
  ElTabs,
  ElTabPane,
  ElTag,
  provideGlobalConfig,
} from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import './style.css'
import SeoApp from './SeoApp.vue'
import router, { revalidateSessionRoute } from './seo-router'
import { AUTH_CONTEXT_EVENT } from './store/sessionStorage'
import { installAuthContextRouting } from './authContextRouting'

installAuthContextRouting(window, AUTH_CONTEXT_EVENT, revalidateSessionRoute)

const elementComponents = [
  ElAlert,
  ElButton,
  ElCheckbox,
  ElCheckboxGroup,
  ElDatePicker,
  ElDialog,
  ElDrawer,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElInput,
  ElInputNumber,
  ElOption,
  ElPagination,
  ElProgress,
  ElRadioButton,
  ElRadioGroup,
  ElSegmented,
  ElSelect,
  ElStep,
  ElSteps,
  ElSwitch,
  ElTable,
  ElTableColumn,
  ElTabs,
  ElTabPane,
  ElTag,
]

const app = createApp(SeoApp)
elementComponents.forEach((component) => app.use(component))
provideGlobalConfig({ locale: zhCn }, app, true)
app.use(router).mount('#app')
