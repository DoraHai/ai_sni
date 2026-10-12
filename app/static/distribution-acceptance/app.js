const $=id=>document.getElementById(id);
if(location.protocol!=='https:'||location.hostname!=='127.0.0.1'||!['55851','55852'].includes(location.port))throw Error('仅支持指定本机隔离环境');
let token='',ctx=null,original=null,master=null,delivery=null,variant=null,connection=null,project=null,busy=false;
let epoch=0,refreshSerial=0;const pendingRequests=new Set();
const marker=' · 本地公众号验收';
const same=(generation,credential)=>epoch===generation&&token===credential;
const stale=()=>Object.assign(new Error('SESSION_CHANGED'),{stale:true});
function clearSession(){
 epoch++;refreshSerial++;for(const request of pendingRequests)request.abort();pendingRequests.clear();
 token='';ctx=original=master=delivery=variant=connection=project=null;busy=false;
 $('workspace').hidden=true;$('login-panel').hidden=false;$('original-body').value='';$('local-body').value='';$('password').value='';$('checked').checked=false;
 for(const id of ['actor','scope','original-title','original-state','local-state','project-state','planner-state','local-preview-title'])$(id).textContent='';
 $('tasks').replaceChildren();$('events').replaceChildren();controls();
}
function log(text){const li=document.createElement('li');li.textContent=new Date().toLocaleTimeString()+' '+text;$('events').prepend(li);$('status').textContent=text;}
async function api(path,method='GET',body,params,identity){
 if(!path.startsWith('/api/')&&!path.startsWith('/acceptance/'))throw Error('不允许外部接口');
 const generation=identity?.epoch??epoch,credential=identity?.token??token;if(!same(generation,credential))throw stale();
 const controller=new AbortController();pendingRequests.add(controller);
 const url=new URL(path,location.origin);if(params)for(const[k,v]of Object.entries(params))if(v!=null)url.searchParams.set(k,String(v));
 try{
 const r=await fetch(url,{method,redirect:'error',signal:controller.signal,headers:{'Content-Type':'application/json',...(credential?{Authorization:'Bearer '+credential}:{})},...(body?{body:JSON.stringify(body)}:{})});
 if(!same(generation,credential))throw stale();
 let value;try{value=await r.json();}catch{if(!same(generation,credential))throw stale();throw Error('接口未返回有效结果');}
 if(!same(generation,credential))throw stale();
 log(method+' '+path+' → '+r.status);
 if(!r.ok){const d=value.detail;throw Error(typeof d==='string'?d.slice(0,180):d?.code||'请求被拒绝');}
 return value;
 }catch(error){if(!same(generation,credential))throw stale();throw error;}finally{pendingRequests.delete(controller);}
}
function controls(){
 const edit=!!ctx?.canEdit&&!busy,check=$('checked').checked;
 $('actions').hidden=!ctx?.canEdit;$('readonly-note').hidden=!!ctx?.canEdit;$('geo-note').hidden=ctx?.module!=='geo';
 $('clone').disabled=!edit||ctx.module!=='seo'||!!master;
 $('submit-master').disabled=!edit||!master||!['planned','drafting'].includes(master.status);
 $('approve-master').disabled=!edit||!check||ctx.actorId!==100012||master?.status!=='review';
 $('confirm').disabled=!edit||!check||ctx.actorId!==100007||master?.status!=='ready'||delivery?.confirmation?.status==='approved';
 $('adapt').disabled=!edit||!check||ctx.actorId!==100007||delivery?.confirmation?.status!=='approved'||!!variant;
 $('approve-variant').disabled=!edit||!check||ctx.actorId!==100012||variant?.status!=='pending_review';
 $('resume').disabled=!edit||ctx.actorId!==100007||project?.state!=='paused';
 $('pause').disabled=!edit||ctx.actorId!==100007||project?.state!=='running';
}
async function refresh(){
 const generation=epoch,credential=token,serial=++refreshSerial,identity={epoch:generation,token:credential};
 const get=(path,params)=>api(path,'GET',null,params,identity);
 const nextCtx=await get('/acceptance/context'),nextOriginal=await get('/acceptance/original');
 let nextMaster=null,nextDelivery=null,nextConnection=null,nextVariant=null,nextProject=null,nextPlans=null,nextGeoTask=null;
 if(nextCtx.module==='seo'){
  const assets=await get('/api/v1/seo/content-assets',{tenant_id:nextCtx.scope.tenant_id,site_id:nextCtx.scope.scope_id});
  nextMaster=assets.items.filter(x=>x.title===nextOriginal.title+marker).sort((a,b)=>b.id-a.id)[0]||null;
  nextDelivery=nextMaster?await get('/api/v1/seo/workbench/content-assets/'+nextMaster.id+'/delivery',{tenant_id:nextCtx.scope.tenant_id,site_id:nextCtx.scope.scope_id}):null;
  if(nextMaster&&nextDelivery){nextMaster.version_count=nextDelivery.content.version_count;nextMaster.status=nextDelivery.content.status;}
  const connections=await get('/api/v1/seo/content-distribution/connections',{tenant_id:nextCtx.scope.tenant_id});
  const rows=Array.isArray(connections)?connections:connections.items||connections.connections||[];
  nextConnection=rows.find(x=>x.name==='公众号浏览器 · 本地验收'&&x.platform_code==='wechat_browser')||null;
  if(nextMaster&&nextConnection){const v=await get('/api/v1/seo/content-distribution/variants',{tenant_id:nextCtx.scope.tenant_id,site_id:nextCtx.scope.scope_id,content_id:nextMaster.id});nextVariant=v.items.filter(x=>x.connection_id===nextConnection.id).sort((a,b)=>b.id-a.id)[0]||null;}
 }else{
  nextGeoTask=await get('/api/v1/geo/content-tasks/'+(nextCtx.localMasterId||nextOriginal.masterId),{tenant_id:nextCtx.scope.tenant_id});
  nextMaster=nextGeoTask.article;nextVariant=nextGeoTask.variants.find(x=>x.channel==='wechat')||null;
 }
 if(nextCtx.canEdit&&nextCtx.actorId===100007){nextProject=(await get('/api/distribution/v1/scope',nextCtx.scope)).project;nextPlans=await get('/api/distribution/v1/plans',nextCtx.scope);}
 const ledger=await get('/acceptance/handoff-results',{tenant_id:nextCtx.scope.tenant_id,scope_id:nextCtx.scope.scope_id});
 if(!same(generation,credential)||serial!==refreshSerial)return;
 ctx=nextCtx;original=nextOriginal;master=nextMaster;delivery=nextDelivery;connection=nextConnection;variant=nextVariant;project=nextProject;
 $('local-preview-title').textContent=variant?'渠道稿 '+variant.id+' / '+variant.status+' / '+variant.title:master?'本地母稿 '+master.id+' / '+master.status:'尚无本地衍生版本';
 $('local-body').value=variant?.content||variant?.body_markdown||delivery?.content?.body||'';
 $('workspace').hidden=false;$('login-panel').hidden=true;$('heading').textContent=ctx.module.toUpperCase()+' 独立分发验收';
 $('actor').textContent='当前实名测试账号：'+ctx.actorName;$('scope').textContent='客户 '+ctx.scope.tenant_id+' / 项目 '+ctx.scope.scope_id+' · 所有操作仅在隔离库';
 $('original-title').textContent=original.title;$('original-body').value=original.body;
 $('original-state').textContent='原快照版本 '+original.version+' / '+(original.platform||'GEO 母稿')+' / '+original.status+'；不授予分发权限';
 if(ctx.module==='seo'){
  $('local-state').textContent=master?'本地副本 '+master.id+'：'+master.status+' / 确认 '+(delivery?.confirmation?.status||'未确认')+' / 渠道稿 '+(variant?.status||'未适配'):'尚无本地副本；原已发布稿不能直接补做确认';
 }else{$('local-state').textContent='当前母稿 '+(master?.id||'无')+' / 版本 '+(master?.version_no||'无')+' / 客户审核 '+nextGeoTask.review_status+' / 人工定版 '+(variant?.adapt_meta?.manual_finalization?.state||'尚未定版')+'；未发布';}
 if(project){$('project-state').textContent='中央项目：'+project.state+' / revision '+project.revision;$('planner-state').textContent='本地模拟节奏：'+nextPlans.items.length+' 条计划；非真实供应商提案';}
 else{project=null;$('project-state').textContent='中央项目控制由已分配顾问负责；当前账号用于审核或只读查看';}
 $('tasks').replaceChildren();
 for(const row of ledger.items){const div=document.createElement('div');div.className='task';div.textContent='任务 '+row.task_id+' / '+row.status+' / '+row.code+' · 尚未发布';$('tasks').append(div);}if(!ledger.items.length)$('tasks').textContent='尚无交接记录';controls();
}
async function act(fn){if(busy)return;const generation=epoch,credential=token;busy=true;controls();try{await fn();if(same(generation,credential))await refresh();}catch(e){if(same(generation,credential)&&!e.stale)log('操作未完成：'+e.message);}finally{if(same(generation,credential)){busy=false;controls();}}}
$('login').onclick=async()=>{const username=$('username').value,password=$('password').value;clearSession();const generation=epoch;try{const r=await api('/api/v1/auth/login','POST',{username,password});if(epoch!==generation)return;token=r.token;await refresh();if(same(generation,r.token))log('登录完成，状态来自实际本机 API');}catch(e){if(epoch===generation&&!e.stale)log('登录未完成：'+e.message);}};
$('refresh').onclick=()=>act(refresh);$('checked').onchange=controls;
$('logout').onclick=()=>{clearSession();log('已退出');};
$('clone').onclick=()=>act(()=>api('/api/v1/seo/content-assets','POST',{tenant_id:ctx.scope.tenant_id,site_id:ctx.scope.scope_id,title:original.title+marker,keyword_ids:original.keywordIds,content_type:'article',draft:original.body,status:'drafting'}));
$('submit-master').onclick=()=>act(()=>api('/api/v1/seo/content-assets/'+master.id+'/submit-review','POST',{version_count:master.version_count,note:'基于现有客户正文的独立本地副本，生产未变更'},{tenant_id:ctx.scope.tenant_id}));
$('approve-master').onclick=()=>act(()=>api('/api/v1/seo/content-assets/'+master.id+'/review','POST',{version_count:master.version_count,decision:'approve',note:'独立本地测试审核人批准，不代表真人客户批准'},{tenant_id:ctx.scope.tenant_id}));
$('confirm').onclick=()=>act(()=>api('/api/v1/seo/workbench/content-assets/'+master.id+'/confirmations','POST',{version_count:delivery.content.version_count,payload_hash:delivery.content.payload_hash,decision:'approve',actor_mode:'advisor_proxy',note:'独立本地测试顾问代确认；生产没有发生'},{tenant_id:ctx.scope.tenant_id}));
$('adapt').onclick=()=>act(async()=>{
 if(!connection)connection=await api('/api/v1/seo/content-distribution/connections','POST',{tenant_id:ctx.scope.tenant_id,platform_code:'wechat_browser',name:'公众号浏览器 · 本地验收',enabled:true});
 const a=await api('/api/v1/seo/content-distribution/adapt','POST',{tenant_id:ctx.scope.tenant_id,site_id:ctx.scope.scope_id,content_id:master.id,connection_id:connection.id,use_ai:false});
 await api('/api/v1/seo/content-distribution/variants','POST',{tenant_id:ctx.scope.tenant_id,site_id:ctx.scope.scope_id,content_id:master.id,connection_id:connection.id,source_version:a.source_version,title:a.title,content:a.content,status:'pending_review',ai_generated:false,instruction:'现有客户正文的本地公众号适配，待人工重审'});
});
$('approve-variant').onclick=()=>act(()=>api('/api/v1/seo/content-distribution/variants/'+variant.id+'/review','POST',{tenant_id:ctx.scope.tenant_id,site_id:ctx.scope.scope_id,decision:'approve',note:'本地测试审核人核对适配稿；未正式发布'}));
for(const action of ['resume','pause'])$(action).onclick=()=>act(()=>api('/api/distribution/v1/control','POST',{...ctx.scope,action,expected_revision:project.revision,request_id:crypto.randomUUID()}));
