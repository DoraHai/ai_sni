import {createApp,h,ref} from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import Recovery from '../../src/components/GeoDeliveryRecovery.vue'
import client from '../../src/api/client'
const tenant=ref(7)
let state='unknown',history=[],blocked=false
client.defaults.adapter=async config=>{
 let data
 if(config.method==='get') data={items:config.params.tenant_id===7?[{variant_id:3,channel:'website',account_id:4,delivery_key:'a'.repeat(64),mode:'publish',state,can_confirm_published:!blocked,can_allow_retry:!blocked,blocked_reason:blocked?'未通过审校，请完成审批后再核对':null,updated_at:'2026-09-06T00:00:00Z',recovery_history:history}]:[]}
 else {
  const p=JSON.parse(config.data)
  if(p.action==='confirm_published') throw Object.assign(new Error('测试正文不匹配'),{response:{status:409,data:{detail:'发布页正文尚未匹配当前稿件，不能生成发布证据'}}})
  state='failed';history.push({action:p.action,user_id:99,note:p.note,at:'本地测试时间'})
  data={ok:true,state}
 }
 return {data,status:200,statusText:'OK',headers:{},config}
}
createApp({setup:()=>()=>h('main',{style:'max-width:850px;margin:24px auto;padding:16px'},[
 h('h1','本地恢复流程验证'),h('p','仅内存模拟，不连接数据库、不发送文章。'),
 h('button',{onClick:()=>tenant.value=tenant.value===7?8:7},'切换测试客户'),
 h('button',{onClick:()=>blocked=!blocked},'切换审批阻止状态（点击后刷新记录）'),
 h(Recovery,{tenantId:tenant.value,taskId:12})
])}).use(ElementPlus).mount('#app')
