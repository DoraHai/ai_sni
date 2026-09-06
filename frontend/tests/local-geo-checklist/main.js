import {createApp,h,ref} from 'vue'
import {createRouter,createMemoryHistory} from 'vue-router'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import Checklist from '../../src/components/GeoLaunchChecklist.vue'
import client from '../../src/api/client'
const tenant=ref(7), task=ref({id:12,title:'测试稿件',article:{id:17},updated_at:'revision',review_status:'pending',variants:[{channel:'website',article_version_id:17}]})
client.defaults.adapter=async config=>{
 let data
 if(config.url.endsWith('/push-targets')) data={targets:[]}
 else if(config.url.endsWith('/execution-readiness')) data={task_id:5,status:'in_progress',baseline_valid:false,baseline_blocker:'完整自然周尚未结束',publication_candidates:[],publication_evidence:null}
 else if(config.method==='get') data=[{id:5,title:'测试指标验收',status:'in_progress',params:{content_task_id:12}}]
 else {task.value={...task.value,review_status:JSON.parse(config.data).decision};data=task.value}
 return{data,status:200,statusText:'OK',headers:{},config}
}
const router=createRouter({history:createMemoryHistory(),routes:[{path:'/:pathMatch(.*)*',component:{render:()=>null}}]})
createApp({setup:()=>()=>h('main',{style:'max-width:900px;margin:30px auto'},[h('h2','仅内存测试，不审核真实稿件'),h(Checklist,{tenantId:tenant.value,task:task.value})])}).use(router).use(ElementPlus).mount('#app')
