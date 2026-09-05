import {createApp,h,ref} from 'vue'
import {createRouter,createMemoryHistory} from 'vue-router'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import '../../src/styles/geo-dashboard.css'
import '../../src/styles/geo-page.css'
import '../../src/styles/geo-v2.css'
import CreateEvidence from '../../src/components/GeoCreateEvidenceTask.vue'
import Evidence from '../../src/components/GeoEvidenceTasks.vue'
import client from '../../src/api/client'
const task={id:10,title:'本地测试：验证真实指标改善',status:'in_progress',params:{content_task_id:12},assignee_role:'GEO运营'}
let baseline=false,proof=false,retest=false,createdTask=null
const tenant=ref(7), content=ref({id:12,title:'本地测试文章'})
client.defaults.adapter=async config=>{
 const path=config.url,method=config.method
 let data
 if(method==='post' && path.endsWith('/tasks')) {createdTask={...JSON.parse(config.data),id:11,status:'open'};data=createdTask}
 else if(method==='get' && path.endsWith('/tasks')) data=config.params.tenant_id===7?[task,...(createdTask?[createdTask]:[])].filter(x=>!config.params.status||x.status===config.params.status):[]
 else if(method==='get' && path.endsWith('/execution-readiness')) data={baseline_valid:baseline,baseline:{value:baseline?0:null,unit:'count',as_of:'2026-08-31',metric_key:'geo.visibility.ai_mention_count_7d'},baseline_blocker:baseline?null:'等待完整周基线',publishing:{ready_count:0},publication_candidates:[{id:99,channel:'官网',url:'https://example.invalid/article'}],publication_evidence:proof?{first_verified_at:'2026-09-01'}:null,retest_plan:baseline?{total_samples:10}:null,can_retest:baseline&&proof&&!retest,retest_blocker:baseline&&proof?null:'等待基线和发布核验',latest_retest:retest?{id:42,status:'running'}:null}
 else if(method==='patch' && ['in_progress','cancelled'].includes(JSON.parse(config.data).status)) {data=path.endsWith('/11')?createdTask:task;data.status=JSON.parse(config.data).status}
 else if(method==='get') data=path.endsWith('/11')?createdTask:task
 else if(path.endsWith('/baseline')) {baseline=true;data=task}
 else if(path.endsWith('/publication-check')) {proof=true;data=task}
 else if(path.endsWith('/retest')) {retest=true;data={run_id:42}}
 else throw Object.assign(new Error('完整后测周尚未结束，任务保持进行中'),{response:{status:409,data:{detail:'完整后测周尚未结束，任务保持进行中'}}})
 return {data:JSON.parse(JSON.stringify(data)),status:200,statusText:'OK',headers:{},config}
}
const router=createRouter({history:createMemoryHistory(),routes:[{path:'/:pathMatch(.*)*',component:{render:()=>null}}]})
const app=createApp({setup:()=>()=>h('main',{class:'geo-dash geo-page',style:'max-width:1000px;margin:24px auto;padding:20px'},[h('h2','仅内存数据，不连接生产'),h('button',{onClick:()=>tenant.value=tenant.value===7?8:7},'切换测试客户'),h('button',{onClick:()=>content.value={id:12,title:'本地测试文章'}},'建立指标验收任务'),h(CreateEvidence,{tenantId:tenant.value,content:content.value,onClose:()=>content.value=null}),h(Evidence,{tenantId:tenant.value})])})
app.use(router).use(ElementPlus).mount('#app')
