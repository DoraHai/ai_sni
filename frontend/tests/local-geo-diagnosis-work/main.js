import {createApp,h,ref} from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import Card from '../../src/components/GeoDiagnosisWorkCard.vue'
import client from '../../src/api/client'
const ticket=ref({id:4,status:'todo',owner_name:'',due_date:null})
const saved=ref('')
client.defaults.adapter=async config=>{
 let data
 if(config.method==='get')data={ticket_id:4,page_url:'https://example.invalid/page',page_title:'测试页面',diagnosed_at:'2026-09-06',source_evidence:'页面缺少主要标题',source_passed:false,suggested_role:'内容编辑',steps:['打开目标页面核对原始问题','在对应页面修改主要标题','保存并实际应用到网站','重抓验收'],acceptance:'重新抓取后标题检查通过',acceptance_type:'auto',outcome_note:'页面整改通过不等于 AI 可见度提升。'}
 else {data={...ticket.value,...JSON.parse(config.data)};ticket.value=data;saved.value=JSON.stringify(data)}
 return{data,status:200,statusText:'OK',headers:{},config}
}
createApp({setup:()=>()=>h('main',{style:'max-width:900px;margin:25px auto'},[h('h2','仅内存测试，不修改客户网站'),h(Card,{tenantId:7,ticket:ticket.value}),h('p','保存结果：'+saved.value)])}).use(ElementPlus).mount('#app')
