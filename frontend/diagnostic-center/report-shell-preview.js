// Development-only visual fixture. All HTTP calls are intercepted locally.
import { createApp, nextTick } from 'vue'
import DiagnosisCenterView from '../src/views/diagnosis/DiagnosisCenterView.vue'
import client from '../src/api/client'
import { session } from '../src/store/session'
import 'element-plus/theme-chalk/base.css'
import '../src/style.css'

export async function mountReportPreview() {
  if (!import.meta.env.DEV) return
  const brand = { name:'示例企业（本地测试）', website:'https://example.com', industry:'工业驱动技术', core_products:['减速机'] }
  client.defaults.adapter = async config => ({ status:200, statusText:'OK', headers:{}, config, data:config.url.includes('profile') ? { brand, audience:{} } : { status:'unavailable', reason:'本地测试未调用外部接口' } })
  session.setTenant(1)
  const app = createApp(DiagnosisCenterView)
  app.mount('#app')
  const state = app._instance.setupState
  state.brandReady = true
  state.brandProfile = brand
  state.url = brand.website
  const findings = [
    {code:'https',title:'HTTPS',category:'技术基础',passed:true,weight:5,deduction:0,evidence:'本地验收样例：HTTPS 可访问'},
    {code:'title',title:'页面标题',category:'页面语义',passed:false,weight:5,deduction:5,severity:'medium',evidence:'本地验收样例：标题缺失',reason:'测试证据'},
    {code:'schema',title:'结构化数据',category:'结构化数据',passed:false,weight:6,deduction:6,severity:'high',evidence:'本地验收样例：未发现结构化数据',reason:'测试证据'},
  ]
  state.audit = { id:999, status:'completed', score:89, created_at:'2026-09-06T05:22:00Z', rule_version:'1.1.0', url:brand.website, final_url:brand.website, page_title:'本地测试报告，非客户数据', findings, problems:findings.filter(f=>!f.passed), snapshot:{brand_profile:brand}, ai_enabled:false }
  state.flow.showReport()
  await nextTick()
  // Expose only local fixture controls for regression assertions.
  window.reportPreview = { state }
}
