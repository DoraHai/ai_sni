<script setup>
import { computed,onMounted,reactive,ref,watch } from 'vue'
import { useRoute,useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createSeoKeyword,fetchSeoKeywords,importSeoKeywords,updateSeoKeyword } from '../../api/seo'
import { fetchSeoSites } from '../../api/moduleAssets'
import { currentTenantId,session } from '../../store/session'

const route=useRoute(),router=useRouter()
const loading=ref(false),saving=ref(false),error=ref(''),result=ref({items:[],total:0,stats:{}})
const sites=ref([]),siteId=ref(null)
const dialog=ref(false),importOpen=ref(false),editing=ref(null),importText=ref(''),segment=ref('all')
const query=ref(String(route.query.q||''))
const form=reactive({site_id:null,keyword:'',cluster:'',intent:'',monthly_volume:null,difficulty:null,priority:'P2',landing_page:'',status:'active',notes:''})
const stats=computed(()=>result.value.stats||{})
const canEdit=computed(()=>!session.isLoggedIn||session.canEdit('seo.keywords'))
const commercialIntents=new Set(['商业','产品','价格','方案','对比','决策'])
const informationIntents=new Set(['信息','指南','教育','教程','知识','泛需求'])
const engineNames={baidu:'百度',bing:'必应','360':'360',sogou:'搜狗',google:'Google'}
const deviceNames={desktop:'桌面',mobile:'移动'}
const pendingLanding=computed(()=>Math.max(0,(stats.value.active||0)-(stats.value.with_landing_page||0)))
const monitoredEngines=computed(()=>stats.value.monitored_engines||[])
const rows=computed(()=>result.value.items.filter(row=>{
  if(segment.value==='commercial')return commercialIntents.has((row.intent||'').trim())
  if(segment.value==='information')return informationIntents.has((row.intent||'').trim())
  if(segment.value==='unassigned')return !row.landing_page
  if(segment.value==='paused')return row.status!=='active'
  return true
}))
const segments=computed(()=>[
  {key:'all',label:'全部'},
  {key:'commercial',label:'商业意图'},
  {key:'information',label:'信息意图'},
  {key:'unassigned',label:'待分配'},
  {key:'paused',label:'暂停监控'},
])
const fmt=value=>Number(value||0).toLocaleString('zh-CN')
const intentClass=value=>value==='决策'?'decision':commercialIntents.has(value)?'commercial':informationIntents.has(value)?'information':'neutral'
const engineLabel=row=>(row.monitored_engines||[]).map(item=>engineNames[item]||item).join(' / ')||'待配置'
const regionDevice=row=>`${row.region||'全国'} · ${deviceNames[row.device]||'桌面'}`

function open(row=null){editing.value=row;Object.assign(form,{site_id:row?.site_id||siteId.value,keyword:row?.keyword||'',cluster:row?.cluster||'',intent:row?.intent||'',monthly_volume:row?.monthly_volume??null,difficulty:row?.difficulty??null,priority:row?.priority||'P2',landing_page:row?.landing_page||'',status:row?.status||'active',notes:row?.notes||''});dialog.value=true}
async function load(){if(!currentTenantId.value){error.value='请先选择客户';result.value={items:[],total:0,stats:{}};return}if(!siteId.value){error.value='请先选择或创建 SEO 网站';result.value={items:[],total:0,stats:{}};return}loading.value=true;try{result.value=await fetchSeoKeywords({tenantId:currentTenantId.value,siteId:siteId.value,q:query.value,status:'',pageSize:200});error.value=''}catch(e){error.value=e.message}finally{loading.value=false}}
async function loadSites(){if(!currentTenantId.value){sites.value=[];siteId.value=null;return load()}try{sites.value=(await fetchSeoSites(currentTenantId.value)).sites||[];const selected=sites.value.some(item=>item.id===siteId.value)?siteId.value:(sites.value.find(item=>item.status==='active')?.id||sites.value[0]?.id||null);if(selected!==siteId.value)siteId.value=selected;else await load()}catch(e){sites.value=[];siteId.value=null;error.value=e.message}}
async function save(){if(!form.site_id)return ElMessage.warning('请选择 SEO 网站');if(!form.keyword.trim())return ElMessage.warning('请填写关键词');saving.value=true;try{const payload={site_id:form.site_id,cluster:form.cluster||null,intent:form.intent||null,monthly_volume:form.monthly_volume,difficulty:form.difficulty,priority:form.priority,landing_page:form.landing_page||null,status:form.status,notes:form.notes||null};if(editing.value)await updateSeoKeyword({keywordId:editing.value.id,tenantId:currentTenantId.value,payload});else await createSeoKeyword({tenant_id:currentTenantId.value,keyword:form.keyword.trim(),...payload});dialog.value=false;const siteChanged=siteId.value!==form.site_id;siteId.value=form.site_id;ElMessage.success('关键词已保存');if(!siteChanged)await load()}catch(e){ElMessage.error(e.message)}finally{saving.value=false}}
async function importRows(){if(!siteId.value)return ElMessage.warning('请选择 SEO 网站');const lines=importText.value.split(/\r?\n/).map(v=>v.trim()).filter(Boolean);if(!lines.length)return ElMessage.warning('请填写关键词');saving.value=true;try{const items=lines.map(line=>{const [keyword,cluster,intent,volume,difficulty,priority,landing]=line.split(/\t|,/).map(v=>v?.trim());return{tenant_id:currentTenantId.value,site_id:siteId.value,keyword,cluster:cluster||null,intent:intent||null,monthly_volume:volume?Number(volume):null,difficulty:difficulty?Number(difficulty):null,priority:['P0','P1','P2','P3'].includes(priority)?priority:'P2',landing_page:landing||null}});await importSeoKeywords({tenant_id:currentTenantId.value,site_id:siteId.value,items});importOpen.value=false;importText.value='';ElMessage.success('关键词已导入');await load()}catch(e){ElMessage.error(e.message)}finally{saving.value=false}}
function toggleStatus(row){editing.value=row;Object.assign(form,{...row,status:row.status==='active'?'paused':'active'});save()}
let timer;watch(query,()=>{clearTimeout(timer);timer=setTimeout(load,260)});watch(siteId,load);watch(currentTenantId,loadSites);onMounted(loadSites)
</script>

<template>
  <div class="manage-page" v-loading="loading">
    <header class="manage-topbar">
      <div class="heading"><h1>关键词管理</h1><p>维护几十到上百个目标词，支持添加、导入、分组、搜索引擎与地区配置</p></div>
      <div class="top-actions"><el-select v-model="siteId" class="site-picker" placeholder="选择 SEO 网站"><el-option v-for="site in sites" :key="site.id" :label="site.name||site.canonical_domain" :value="site.id"/></el-select><label class="global-search"><span>⌕</span><input v-model="query" placeholder="搜索关键词…"></label><button v-if="canEdit" class="ui-btn" :disabled="!siteId" @click="importOpen=true">批量导入</button><button v-if="canEdit" class="ui-btn primary" :disabled="!siteId" @click="open()">＋ 添加关键词</button><span class="avatar">{{String(session.user?.name||session.user?.username||'DZ').slice(0,2).toUpperCase()}}</span></div>
    </header>
    <main class="manage-content">
      <el-alert v-if="error" class="page-alert" :title="error" type="warning" :closable="false"/>
      <section class="summary-grid">
        <article><span>目标关键词</span><strong>{{fmt(result.total)}}</strong><small>已启用 {{fmt(stats.active)}}</small></article>
        <article><span>商业意图词</span><strong>{{fmt(stats.commercial_intent)}}</strong><small class="positive">▲ {{fmt(stats.commercial_intent)}} 个重点词</small></article>
        <article><span>待分配落地页</span><strong class="warning">{{fmt(pendingLanding)}}</strong><small>需要处理</small></article>
        <article><span>监控搜索引擎</span><strong>{{monitoredEngines.length}}</strong><small>{{monitoredEngines.length?monitoredEngines.map(item=>engineNames[item]||item).join(' / '):'尚未导入排名快照'}}</small></article>
      </section>
      <section class="keyword-panel">
        <header class="panel-head"><h2>关键词列表</h2><div class="segment-tabs"><button v-for="item in segments" :key="item.key" :class="{active:segment===item.key}" @click="segment=item.key">{{item.label}}</button></div></header>
        <div class="table-wrap"><table><thead><tr><th>关键词</th><th>分组</th><th>意图</th><th>监控引擎</th><th>地区/设备</th><th>目标落地页</th><th>状态</th><th>操作</th></tr></thead><tbody><tr v-for="row in rows" :key="row.id"><td><button class="keyword-link" @click="router.push(`/seo/keywords/${row.id}`)">{{row.keyword}}</button></td><td>{{row.cluster||'未分组'}}</td><td><span class="intent-pill" :class="intentClass(row.intent)">{{row.intent||'泛需求'}}</span></td><td>{{engineLabel(row)}}</td><td>{{regionDevice(row)}}</td><td><span v-if="row.landing_page" class="landing">{{row.landing_page}}</span><span v-else class="pending-pill">待分配</span></td><td><span class="status-pill" :class="{paused:row.status!=='active'}">{{row.status==='active'?'启用':'暂停'}}</span></td><td><button class="text-action" @click="open(row)">编辑</button><button v-if="canEdit&&row.status!=='active'" class="text-action" @click="toggleStatus(row)">启用</button></td></tr><tr v-if="!rows.length"><td colspan="8"><div class="empty"><b>暂无关键词</b><span>{{query?'没有匹配的关键词':'添加或批量导入关键词后开始运营'}}</span></div></td></tr></tbody></table></div>
      </section>
    </main>
    <el-dialog v-model="dialog" :title="editing?'编辑关键词':'添加关键词'" width="620px"><el-form label-position="top" class="form-grid"><el-form-item label="SEO 网站" class="full"><el-select v-model="form.site_id" placeholder="选择 SEO 网站"><el-option v-for="site in sites" :key="site.id" :label="site.name||site.canonical_domain" :value="site.id"/></el-select></el-form-item><el-form-item label="关键词" class="full"><el-input v-model="form.keyword" :disabled="!!editing"/></el-form-item><el-form-item label="分组"><el-input v-model="form.cluster"/></el-form-item><el-form-item label="搜索意图"><el-select v-model="form.intent"><el-option v-for="item in ['商业','决策','信息','泛需求','产品','价格','方案','对比']" :key="item" :label="item" :value="item"/></el-select></el-form-item><el-form-item label="月搜索量"><el-input-number v-model="form.monthly_volume" :min="0"/></el-form-item><el-form-item label="竞争难度"><el-input-number v-model="form.difficulty" :min="0" :max="100"/></el-form-item><el-form-item label="优先级"><el-select v-model="form.priority"><el-option v-for="item in ['P0','P1','P2','P3']" :key="item" :label="item" :value="item"/></el-select></el-form-item><el-form-item label="状态"><el-select v-model="form.status"><el-option label="启用" value="active"/><el-option label="暂停" value="paused"/><el-option label="归档" value="archived"/></el-select></el-form-item><el-form-item label="目标落地页" class="full"><el-input v-model="form.landing_page" placeholder="/product/example"/></el-form-item></el-form><template #footer><el-button @click="dialog=false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存关键词</el-button></template></el-dialog>
    <el-dialog v-model="importOpen" title="批量导入关键词" width="680px"><p class="import-tip">每行一个关键词，支持制表符或逗号分隔：关键词、分组、意图、搜索量、难度、优先级、落地页。</p><el-input v-model="importText" type="textarea" :rows="10"/><template #footer><el-button @click="importOpen=false">取消</el-button><el-button type="primary" :loading="saving" @click="importRows">开始导入</el-button></template></el-dialog>
  </div>
</template>

<style scoped>
.manage-page{min-height:100vh;background:#f5f7fb;color:#1d2535;font-family:-apple-system,"PingFang SC","Microsoft YaHei","Segoe UI",sans-serif}.manage-topbar{height:70px;padding:0 28px;display:flex;align-items:center;justify-content:space-between;gap:24px;border-bottom:1px solid #e5e9f1;background:#fff}.heading h1{margin:0 0 3px;font-size:19px;line-height:1.2;font-weight:760}.heading p{margin:0;color:#7b8495;font-size:12px}.top-actions{display:flex;align-items:center;gap:12px}.site-picker{width:190px}.global-search{width:300px;height:38px;padding:0 13px;display:flex;align-items:center;gap:8px;border:1px solid #e1e5ec;border-radius:9px;background:#f7f8fb;color:#9aa2b0}.global-search input{width:100%;border:0;outline:0;background:transparent;color:#30394a;font-size:12px}.ui-btn{height:38px;padding:0 17px;border:1px solid #dfe3ea;border-radius:9px;background:#fff;color:#293244;font-size:12px;font-weight:700;cursor:pointer}.ui-btn:disabled{cursor:not-allowed;opacity:.55}.ui-btn.primary{border-color:#2563eb;background:#2563eb;color:#fff}.avatar{width:35px;height:35px;display:grid;place-items:center;border-radius:50%;background:#2563eb;color:#fff;font-size:12px;font-weight:800}.manage-content{padding:26px 30px 40px}.page-alert{margin-bottom:16px}.summary-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:20px;margin-bottom:22px}.summary-grid article{height:136px;padding:25px 26px;border:1px solid #e2e6ed;border-radius:13px;background:#fff;box-shadow:0 2px 6px rgba(27,39,60,.05)}.summary-grid span,.summary-grid small{display:block;color:#727c8e;font-size:12px}.summary-grid strong{display:block;margin:15px 0 8px;color:#1c2434;font-size:30px;line-height:1;font-weight:760}.summary-grid strong.warning{color:#d97800}.summary-grid small.positive{color:#16a34a;font-weight:700}.keyword-panel{overflow:hidden;border:1px solid #e0e4eb;border-radius:13px;background:#fff;box-shadow:0 2px 7px rgba(27,39,60,.05)}.panel-head{height:63px;padding:0 25px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #e7eaf0}.panel-head h2{margin:0;font-size:16px}.segment-tabs{display:flex;gap:9px}.segment-tabs button{height:29px;padding:0 11px;border:1px solid transparent;border-radius:7px;background:#f2f4f7;color:#737d8f;font-size:11px;font-weight:650;cursor:pointer}.segment-tabs button.active{border-color:#3973f3;background:#fff;color:#2563eb}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;table-layout:fixed}th,td{height:67px;padding:0 18px;border-bottom:1px solid #e7eaf0;text-align:left;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}th{height:49px;background:#fff;color:#727b8c;font-size:11px;font-weight:700}th:nth-child(1){width:18%}th:nth-child(2){width:11%}th:nth-child(3){width:11%}th:nth-child(4){width:18%}th:nth-child(5){width:13%}th:nth-child(6){width:19%}th:nth-child(7){width:9%}th:nth-child(8){width:8%}tbody tr:last-child td{border-bottom:0}tbody tr:hover{background:#fafbfe}.keyword-link,.text-action{padding:0;border:0;background:none;cursor:pointer}.keyword-link{color:#202838;font-weight:750}.keyword-link:hover,.text-action:hover{color:#2563eb}.text-action{margin-right:12px;color:#667083;font-size:12px}.intent-pill,.pending-pill,.status-pill{display:inline-flex;min-height:28px;padding:0 10px;align-items:center;border-radius:16px;background:#f0f2f5;color:#727b8a;font-size:11px;font-weight:700}.intent-pill.commercial{background:#eaf1ff;color:#2563eb}.intent-pill.decision{background:#fff3df;color:#d97706}.intent-pill.information{background:#eef0f4;color:#667083}.pending-pill{background:#fff2dc;color:#d97706}.status-pill{background:#e7f7ee;color:#16a34a}.status-pill.paused{background:#f0f1f4;color:#747d8c}.landing{color:#6d7688}.empty{height:190px;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:7px;color:#929baa}.empty b{color:#667083}.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:0 14px}.form-grid .full{grid-column:1/-1}.form-grid :deep(.el-select),.form-grid :deep(.el-input-number){width:100%}.import-tip{margin:0 0 12px;color:#727b8c;font-size:12px}@media(max-width:1100px){.summary-grid{grid-template-columns:repeat(2,1fr)}.global-search{width:220px}.heading p{display:none}}@media(max-width:760px){.manage-topbar{height:auto;padding:15px;align-items:flex-start;flex-direction:column}.top-actions{width:100%;flex-wrap:wrap}.site-picker,.global-search{width:100%}.manage-content{padding:15px}.summary-grid{grid-template-columns:1fr}.segment-tabs{overflow:auto}.panel-head{height:auto;padding:14px;align-items:flex-start;gap:12px;flex-direction:column}}
</style>
