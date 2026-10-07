import {cycleFields} from '../js/seo-cycle-config.mjs';
const kinds={content:'content_delivery',website:'site_diagnosis',monitoring:'ranking_followup',report:'monthly_report'};
export function initUi10(state){
  state.publications=new Map([1,2].map(t=>[t,[{id:t===1?91:191,tenant_id:t,content_id:t===1?88:188,source_version:3,publish_mode:'manual',status:'manual_required',platform_name:'人工渠道',page_url:null,published_at:null}]]));
  state.facts=new Map([1,2].map(t=>[t,[{id:30+t,tenant_id:t,site_id:t===1?9:19,title:`客户${t}产品事实`,statement:'本产品支持已核对的功能。',source_name:'客户产品手册',source_url:null,expires_at:null,status:'active',current:true,version:1},{id:40+t,tenant_id:t,site_id:t===1?9:19,title:'过期资料',statement:'旧资料',source_name:'旧手册',expires_at:'2020-01-01T00:00:00Z',status:'active',current:false,version:1}]]));
  state.keywords=new Map([1,2].map(t=>[t,Array.from({length:52},(_,i)=>({id:t*1000+i+1,tenant_id:t,site_id:t===1?9:19,keyword:`本站关键词${i+1}`,status:'active'}))]));
  for(const plan of state.plans.values())Object.assign(plan,{content_ai_enabled:false,content_ai_fact_ids:[],content_ai_keyword_ids:[],content_ai_authorized_by:null,content_ai_authorized_at:null});
}
export function triggerCapabilities(state,tenant,advisor){
  const plan=state.plans.get(tenant);return Object.fromEntries(Object.entries(kinds).map(([kind,type])=>{
    let reason=!advisor||state.planDenied?'active_site_advisor_assignment_required':plan.status==='paused'?'service_plan_paused':[...state.executions.values()].some(v=>v.tenant===tenant&&v.task.action_type===type&&['open','in_progress'].includes(v.task.status))?(kind==='content'?'content_workflow_already_active':'service_workflow_already_active'):null;
    if(!reason&&kind==='monitoring'&&state.keywordLevel!=='edit')reason='keyword_edit_permission_required';
    return [kind,{allowed:!reason,reason,endpoint:'/api/v1/seo/workbench/'+(kind==='content'?'service-plan/run':'service-cycles/run'),method:'POST',kind:kind==='content'?null:kind,expected_revision:plan.revision,request_id_format:'uuid',meaning:'new_execution_only'}];
  }));
}
export function handleUi10({url,req,send,body,state,tenant,site,advisor,res}){
  const plan=state.plans.get(tenant),content=state.contents.get(tenant),confirmation=state.confirmations.get(tenant),confirmed=!state.confirmationUnavailable&&confirmation?.decision==='approve'&&confirmation.content_version===content.version_count&&confirmation.payload_hash===content.payload_hash;
  if(url.pathname==='/api/v1/seo/qa/facts'){send(200,state.facts.get(tenant));return true;}
  if(url.pathname==='/api/v1/seo/keywords'){
    if(state.keywordLevel==='none'){send(403,{detail:'Keyword permission required'});return true;}
    const page=Number(url.searchParams.get('page')),all=state.keywords.get(tenant);send(200,{items:all.slice((page-1)*50,page*50),total:all.length,page,page_size:50});return true;
  }
  if(url.pathname==='/api/v1/seo/workbench/service-plan'){
    const allowed=advisor&&!state.planDenied;
    if(req.method==='GET'){send(200,{...plan,allowed_actions:{update_service_plan:allowed},permission_basis:{actor_user_id:advisor?7:12,active_site_advisor_assignment:allowed,update_denial_reason:allowed?null:'active_site_advisor_assignment_required'},content_ai_policy:{can_configure:allowed&&state.keywordLevel!=='none',can_disable:allowed,provider_configured:false,output_status:'drafting',automatic_review:false,automatic_confirmation:false,automatic_publication:false,attempts_per_workflow:1},trigger_actions:triggerCapabilities(state,tenant,advisor)});return true;}
    if(!allowed){send(403,{detail:'顾问资格已撤销'});return true;}
    if(body.expected_revision!==plan.revision){send(409,{detail:{code:'service_plan_version_conflict'}});return true;}
    if(body.content_ai_enabled===true){
      if(state.keywordLevel==='none'){send(403,{detail:'Keyword permission required'});return true;}
      if(!body.content_ai_fact_ids?.length||!body.content_ai_keyword_ids?.length||body.content_ai_fact_ids.some(id=>!state.facts.get(tenant).some(f=>f.id===id&&f.current&&f.status==='active'))||body.content_ai_keyword_ids.some(id=>!state.keywords.get(tenant).some(k=>k.id===id&&k.status==='active'))){send(409,{detail:{code:'ai_draft_material_missing_or_expired'}});return true;}
    }
    Object.assign(plan,{revision:plan.revision+1,optimization_directions:body.optimization_directions,content_topics:body.content_topics,service_note:body.service_note,status:body.status,updated_by:7,updated_at:'2026-10-07T12:06:00Z'},Object.fromEntries([...Object.keys(cycleFields),'content_ai_enabled','content_ai_fact_ids','content_ai_keyword_ids'].filter(k=>body[k]!==undefined).map(k=>[k,body[k]])));
    if(body.content_ai_enabled===true)Object.assign(plan,{content_ai_authorized_by:7,content_ai_authorized_at:'2026-10-07T12:06:00Z'});send(200,plan);return true;
  }
  if(['/api/v1/seo/workbench/service-plan/run','/api/v1/seo/workbench/service-cycles/run'].includes(url.pathname)){
    const kind=body.kind||'content',a=triggerCapabilities(state,tenant,advisor)[kind];
    const existing=[...state.executions.values()].find(v=>v.tenant===tenant&&v.task.action_type===kinds[kind]&&v.task.params.request_key==='request:'+body.request_id);if(existing){send(200,{created:false,task:existing.task});return true;}
    if(!a?.allowed){send(advisor?409:403,{detail:{code:a?.reason||'denied'}});return true;}
    if(body.expected_revision!==plan.revision){send(409,{detail:{code:'service_plan_version_conflict'}});return true;}
    const id=Math.max(1000,...state.executions.keys())+1,task={id,module:'seo',action_type:kinds[kind],title:'本次顾问触发 '+kind,status:'open',created_by:'7',assignee_role:'seo_advisor',completion_evidence:null,created_at:'2026-10-07T12:00:00Z',updated_at:'2026-10-07T12:00:00Z',params:{kind,request_key:'request:'+body.request_id,plan_revision:plan.revision,phase:kind==='content'?'awaiting_draft':kind+'_queued',waiting_for:'system',...(kind==='content'?{content_id:content.id}:{} )}};
    state.executions.set(id,{tenant,task});if(state.dropTriggerResponse){state.dropTriggerResponse=false;res.writeHead(200,{'Content-Type':'application/json'});res.write('{');setImmediate(()=>res.destroy());return true;}send(200,{created:true,task});return true;
  }
  const list=state.publications.get(tenant),complete=url.pathname.match(/^\/api\/v1\/seo\/content-distribution\/publications\/(\d+)\/complete$/);
  if(url.pathname==='/api/v1/seo/content-distribution/publications'){
    const items=list.map(v=>{const reason=!advisor?'content_edit_permission_required':v.source_version!==content.version_count?'content_version_conflict':!['manual_required','failed','preparing'].includes(v.status)?'publication_status_not_completable':!confirmed?'content_confirmation_pending':null;return {...v,allowed_actions:{complete:!reason},action_denial_reasons:{complete:reason},action_requirements:{complete:{endpoint:`/api/v1/seo/content-distribution/publications/${v.id}/complete`,method:'POST',source_version:v.source_version,page_url_required:true,meaning:'record_existing_publication_only'}}};});send(200,{items,total:items.length});return true;
  }
  if(url.pathname==='/api/v1/seo/content-distribution/publications/manual'||complete){
    if(!advisor||state.publicationDenied){send(403,{detail:'Content permission revoked'});return true;}
    if(!body.source_version||(!complete&&!body.payload_hash)){send(428,{detail:{code:'content_version_precondition_required'}});return true;}
    if(body.source_version!==content.version_count||(!complete&&body.payload_hash!==content.payload_hash)){send(409,{detail:{code:'content_version_conflict'}});return true;}
    if(!confirmed){send(409,{detail:{code:'content_confirmation_required'}});return true;}
    let row=complete?list.find(v=>v.id===Number(complete[1])):null;
    if(complete&&(!row||row.source_version!==body.source_version||!['manual_required','failed','preparing'].includes(row.status))){send(409,{detail:'Not completable'});return true;}
    if(!row){row={id:Math.max(300,...list.map(v=>v.id))+1,tenant_id:tenant,content_id:content.id,source_version:content.version_count,publish_mode:'manual',platform_name:body.platform_name};list.push(row);}
    Object.assign(row,{status:'published',page_url:body.page_url,published_at:body.published_at});content.status='published';if(state.dropPublicationResponse){state.dropPublicationResponse=false;res.writeHead(200,{'Content-Type':'application/json'});res.write('{');setImmediate(()=>res.destroy());return true;}send(200,{...row,page_verification:{state:'queued',capture_id:501,reason:null}});return true;
  }
  return false;
}
