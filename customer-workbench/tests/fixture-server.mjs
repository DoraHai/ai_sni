import http from 'node:http';import fs from 'node:fs/promises';import path from 'node:path';import {fileURLToPath} from 'node:url';
import {executionFixture,handleExecutionFixture} from './execution-fixture.mjs';
import {initUi10,handleUi10} from './ui10-fixture.mjs';
import {cycleFields} from '../js/seo-cycle-config.mjs';
import {handleUi13} from './ui13-fixture.mjs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
export async function startFixtureServer(){
  const state={calls:[],forceError:null,holdNext:null,held:[],planDenied:false,contentTotals:new Map(),modules:['seo'],executions:executionFixture(),executionDenied:false,keywordLevel:'edit',
    contents:new Map([1,2].map(tenant=>[tenant,{id:tenant===1?88:188,tenant_id:tenant,site_id:tenant===1?9:19,title:`契约服务器客户${tenant}稿件`,body:`客户${tenant}的正文事实与产品资料。`,version_count:3,payload_hash:String(tenant).repeat(64),status:'ready',updated_at:'2026-10-07T12:00:00Z'}])),
    confirmations:new Map(),plans:new Map([1,2].map(tenant=>[tenant,{tenant_id:tenant,site_id:tenant===1?9:19,revision:2,status:'active',optimization_directions:['技术 SEO'],content_topics:['选型'],service_note:'接口夹具',updated_by:null,updated_at:null,...cycleFields}]))};
  initUi10(state);
  const server=http.createServer(async(req,res)=>{
    const url=new URL(req.url,'http://127.0.0.1');
    const send=(status,data)=>{res.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify(data));};
    try{
      if(!url.pathname.startsWith('/api/')){
        if(url.pathname.startsWith('/customer-workbench/')){
          const name=url.pathname.slice('/customer-workbench/'.length)||'index.html';
          if(!['index.html','app.js','app.css','release-manifest.json'].includes(name)){send(404,{detail:'Not found'});return;}
          const file=await fs.readFile(path.join(root,'dist/customer-workbench',name));res.writeHead(200,{'Content-Type':name.endsWith('.html')?'text/html':name.endsWith('.css')?'text/css':name.endsWith('.json')?'application/json':'text/javascript'});res.end(file);return;
        }
        if(url.pathname==='/fixture.html'){
          const html=await fs.readFile(path.join(root,'connected.html'),'utf8');res.writeHead(200,{'Content-Type':'text/html'});res.end(html.replace('<script type="module" src="js/connected-bootstrap.mjs">','<script type="module" src="tests/fixture-host.mjs"></script><script type="module" src="js/connected-bootstrap.mjs">'));return;
        }
        const name=url.pathname==='/'?'connected.html':decodeURIComponent(url.pathname.slice(1));
        if(!/^(connected\.html|index\.html|(css|js)\/[a-zA-Z0-9_.-]+|tests\/fixture-host\.mjs)$/.test(name)){send(404,{detail:'Not found'});return;}
        const file=await fs.readFile(path.join(root,name));res.writeHead(200,{'Content-Type':name.endsWith('.html')?'text/html':name.endsWith('.css')?'text/css':'text/javascript'});res.end(file);return;
      }
      let raw='';for await(const chunk of req)raw+=chunk;const body=raw?JSON.parse(raw):null;
      state.calls.push({method:req.method,path:url.pathname,query:Object.fromEntries(url.searchParams),body});
      if(state.holdNext&&url.pathname.includes(state.holdNext)){state.holdNext=null;await new Promise(resolve=>state.held.push(resolve));}
      const forced=state.forceError;if(forced&&url.pathname.includes(forced.path)){state.forceError=null;send(forced.status,{detail:forced.detail??'fixture denied'});return;}
      const auth=req.headers.authorization;const advisor=auth==='Bearer fixture-advisor';
      if(!advisor&&auth!=='Bearer fixture-customer'){send(401,{detail:'Fixture session expired'});return;}
      const userId=advisor?7:12,permissions={'seo.content':advisor?'edit':'view','seo.site':advisor?'edit':'view'};
      if(state.keywordLevel!=='none')permissions['seo.keywords']=advisor?state.keywordLevel:'view';
      if(url.pathname==='/api/v1/auth/me'){send(200,{user:{id:userId,tenant_id:advisor?null:1,display_name:advisor?'顾问接口夹具':'客户接口夹具',permissions}});return;}
      if(url.pathname==='/api/v1/auth/modules'){send(200,{tenant_id:advisor?null:1,modules:state.modules.map(module_code=>({module_code,available:true,status:'active'}))});return;}
      if(url.pathname==='/api/v1/auth/tenants'){send(200,{module:'seo',tenants:(advisor?[1,2]:[1]).map(id=>({id,name:`契约客户${id}`}))});return;}
      const tenant=Number(url.searchParams.get('tenant_id')??body?.tenant_id),site=tenant===1?9:19;
      if(![1,2].includes(tenant)||(!advisor&&tenant!==1)){send(403,{detail:'Fixture tenant denied'});return;}
      if(handleUi13({url,req,res,send,body,state,tenant,site,advisor}))return;
      if(handleUi10({url,req,res,send,body,state,tenant,site,advisor}))return;
      if(handleExecutionFixture({url,req,res,send,body,state,tenant,site,advisor}))return;
      if(url.pathname==='/api/v1/seo/workbench/sites'){send(200,{tenant_id:tenant,sites:[{id:site,name:`站点${site}`,domain:`fixture-${tenant}.invalid`,status:'active'}],selection_policy:{selectable_statuses:['active'],disabled_statuses:['paused','archived']}});return;}
      const content=state.contents.get(tenant),plan=state.plans.get(tenant);
      const delivery=()=>{
        const latest=state.confirmations.get(tenant)||null,confirmation=latest?.content_version===content.version_count&&latest?.payload_hash===content.payload_hash?latest:null,ready=content.status==='ready'&&!confirmation;
        return {content:{...content},workflow_status:confirmation?.decision==='approve'?'approved_waiting_publication':content.status==='drafting'?'awaiting_content_revision':'awaiting_customer_confirmation',
          confirmation:{status:state.confirmationUnavailable?'unavailable':confirmation?.decision==='approve'?'approved':confirmation?'rejected':latest?'stale':'pending',latest,requires_exact_version:true,approval_is_publication:false},
          allowed_actions:{confirm_as_customer:ready&&!advisor,confirm_as_advisor_proxy:ready&&advisor,reject_as_customer:ready&&!advisor,reject_as_advisor_proxy:ready&&advisor,edit_content:advisor&&['planned','drafting'].includes(content.status),submit_review:advisor&&['planned','drafting'].includes(content.status),review:advisor&&content.status==='review',start_publication:advisor&&confirmation?.decision==='approve'&&['ready','published'].includes(content.status)},
          permission_basis:{actor_user_id:userId,active_site_advisor_assignment:advisor},result_basis:{publication_status:'not_loaded',page_check_status:'not_loaded',search_effect_status:'not_attributed_to_single_content'}};
      };
      if(url.pathname==='/api/v1/seo/content-assets'){
        if(url.searchParams.has('content_id')){const items=Number(url.searchParams.get('content_id'))===content.id?[{draft:content.body,humanized_content:null,outline:'',keyword_ids:[21],...content}]:[];send(200,{items,total:items.length,page:1,page_size:50});return;}
        const page=Number(url.searchParams.get('page')),pageSize=Number(url.searchParams.get('page_size')),total=state.contentTotals.get(tenant)??1;
        if(!Number.isSafeInteger(page)||page<1||!Number.isSafeInteger(pageSize)||pageSize<1||pageSize>200){send(422,{detail:'Invalid pagination'});return;}
        const items=Array.from({length:total},(_,index)=>index===0?{...content}:{...content,id:1000+tenant*100+index,title:`客户${tenant}第${index+1}篇稿件`}).slice((page-1)*pageSize,page*pageSize);
        send(200,{items,total,page,page_size:pageSize});return;
      }
      if(url.pathname===`/api/v1/seo/workbench/content-assets/${content.id}/delivery`){send(200,delivery());return;}
      if(url.pathname===`/api/v1/seo/workbench/content-assets/${content.id}/confirmations`&&req.method==='POST'){
        if(body.version_count!==content.version_count||body.payload_hash!==content.payload_hash){send(409,{detail:{code:'content_version_conflict'}});return;}
        if((advisor?'advisor_proxy':'customer_direct')!==body.actor_mode){send(403,{detail:'Fixture actor mismatch'});return;}
        if(body.decision==='reject'&&!body.note?.trim()){send(400,{detail:'退回必须说明'});return;}
        state.confirmations.set(tenant,{id:1,content_version:content.version_count,payload_hash:content.payload_hash,decision:body.decision,actor_mode:body.actor_mode,actor_user_id:userId,actor_name:advisor?'顾问接口夹具':'客户接口夹具',actor_role_name:advisor?'顾问':'客户',note:body.note,created_at:'2026-10-07T12:05:00Z'});
        if(body.decision==='reject')content.status='drafting';send(200,delivery());return;
      }
      if(url.pathname===`/api/v1/seo/content-assets/${content.id}`&&req.method==='PATCH'){
        if(!advisor){send(403,{detail:'Advisor required'});return;}
        if(body.version_count==null){send(428,{detail:{code:'content_version_precondition_required'}});return;}
        if(body.version_count!==content.version_count){send(409,{detail:'内容已被其他操作更新，请刷新后重试'});return;}
        if(!['planned','drafting'].includes(content.status)){send(409,{detail:'Protected content'});return;}
        const fields=['title','outline','draft','humanized_content'];const changed=fields.some(k=>body[k]!==undefined&&body[k]!==content[k]);
        for(const k of fields)if(body[k]!==undefined)content[k]=body[k];
        if(changed){content.version_count++;content.payload_hash=String(content.version_count).padStart(64,'0');}content.body=content.humanized_content||content.draft||'';send(200,{...content});return;
      }
      if(url.pathname===`/api/v1/seo/content-assets/${content.id}/submit-review`||url.pathname===`/api/v1/seo/content-assets/${content.id}/review`){
        if(!advisor){send(403,{detail:'Advisor required'});return;}if(body.version_count!==content.version_count){send(409,{detail:{code:'content_version_conflict'}});return;}
        if(url.pathname.endsWith('/submit-review')){if(!['planned','drafting'].includes(content.status)||!content.body.trim()||content.keyword_ids?.length===0){send(409,{detail:'Content or keywords required'});return;}content.status='review';}
        else {if(content.status!=='review'||(body.decision==='reject'&&!body.note?.trim())){send(409,{detail:'Review gate'});return;}content.status=body.decision==='approve'?'ready':'drafting';}send(200,{...content});return;
      }
      if(url.pathname==='/api/v1/seo/content-distribution/publications'){send(200,{items:[{id:tenant===1?91:191,tenant_id:tenant,content_id:content.id,source_version:3,publish_mode:'manual',status:'manual_required',platform_name:'人工渠道',page_url:null,published_at:null}],total:1});return;}
      if(/^\/api\/v1\/seo\/content-distribution\/publications\/\d+\/attempts$/.test(url.pathname)){send(200,{items:[{id:1,action:'publish',status:'failed',response_summary:{outcome:'unknown',requires_manual_review:true},started_at:'2026-10-07T12:00:00Z',completed_at:null}]});return;}
      if(url.pathname==='/api/v1/seo/workbench/service-plan'){
        if(req.method==='GET'){send(200,{...plan,allowed_actions:{update_service_plan:advisor&&!state.planDenied},permission_basis:{actor_user_id:userId,schema_ready:true,active_site_advisor_assignment:advisor&&!state.planDenied,update_denial_reason:advisor&&!state.planDenied?null:'active_site_advisor_assignment_required'}});return;}
        if(req.method==='PUT'){
          if(!advisor||state.planDenied){send(403,{detail:'顾问资格已撤销'});return;}
          if(body.expected_revision!==plan.revision){send(409,{detail:{code:'service_plan_version_conflict',current_revision:plan.revision}});return;}
          Object.assign(plan,{revision:plan.revision+1,optimization_directions:body.optimization_directions,content_topics:body.content_topics,service_note:body.service_note,status:body.status,updated_by:userId,updated_at:'2026-10-07T12:06:00Z'},Object.fromEntries(Object.keys(cycleFields).filter(k=>body[k]!==undefined).map(k=>[k,body[k]])));send(200,plan);return;
        }
      }
      if(url.pathname==='/api/v1/seo/workbench/service-status'){
        send(200,{tenant_id:tenant,site_id:site,read_only:true,read_at:'2026-10-07T12:00:00Z',phases:Object.fromEntries(['SEO-A01','SEO-A02','SEO-A03','SEO-A05','SEO-A06','SEO-A07'].map(id=>[id,{state:id==='SEO-A03'?'no_data':'ready',blockers:id==='SEO-A03'?['rank_observation_missing']:[],facts:{fixture_count:1},as_of:null}])),semantics:{phase_state:'fact_readiness_only;not_task_completion',task_completion:'use_task_status_done_with_server_verified_completion_evidence'},evidence_endpoints:{task_ledger:'/api/v1/seo/tasks',content_delivery_template:'/api/v1/seo/workbench/content-assets/{content_id}/delivery'}});return;
      }
      send(404,{detail:'Fixture route absent'});
    }catch(e){send(500,{detail:'Fixture server error'});}
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  return {origin:`http://127.0.0.1:${server.address().port}`,state,async close(){for(const release of state.held)release();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}};
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  const fixture=await startFixtureServer();process.stdout.write(`Local contract fixture: ${fixture.origin}/fixture.html\nDisconnected entry: ${fixture.origin}/connected.html\n`);
}
