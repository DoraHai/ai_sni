import {createHash} from 'node:crypto';
export function executionFixture(){
  const rows=new Map(),html='<html><body><h1>冻结HTML月报</h1><p>统计缺失，不补零。</p></body></html>';
  for(const tenant of [1,2])for(const [index,action] of ['content_delivery','site_diagnosis','ranking_followup','monthly_report'].entries()){
    const id=tenant*100+index+1,phase=['awaiting_confirmation','awaiting_site_implementation','awaiting_ranking_observations','awaiting_advisor_explanation'][index];
    const params={kind:['content','website','monitoring','report'][index],phase,waiting_for:index===0?'customer_or_advisor':index===2?'system':'advisor',blocker:index===1?'remediation_requires_real_recheck':null,plan_revision:2,trigger:'scheduled',triggered_by_user_id:null,phase_since:'2026-10-07T08:00:00Z',attention_due_at:'2026-10-09T08:00:00Z',attention_overdue:false,notification_sent:false,history:[{phase,blocker:null,at:'2026-10-07T08:00:00Z',actor:'system'}],history_truncated:true};
    if(index===0)params.content_id=tenant===1?88:188;
    if(index===1){params.pages={'10':{state:'failed',error:'fixture_timeout',snapshot_id:null,run_id:null}};params.child_task_ids=[500];}
    if(index===2){params.keyword_count=1;params.issues=[{keyword_id:12,reason:'rank_drop',observed_id:42,recovery_rank:3}];}
    if(index===3)params.report={format:'html',month:'2026-09',generated_at:'2026-10-07T08:00:00Z',sha256:createHash('sha256').update(html).digest('hex'),publication_ids:[91],analytics_row_ids:[],missing:['site_analytics_missing'],pdf_generated:false,notification_sent:false};
    rows.set(id,{tenant,html,task:{id,module:'seo',action_type:action,title:`客户${tenant}执行任务${id}`,status:'in_progress',params,created_by:'cockpit',assignee_role:'seo_advisor',completion_evidence:null,created_at:'2026-10-07T08:00:00Z',updated_at:'2026-10-07T08:01:00Z'}});
  }
  return rows;
}
export function handleExecutionFixture({url,req,res,send,body,state,tenant,site,advisor}){
  const base='/api/v1/seo/workbench/executions',match=url.pathname.match(/^\/api\/v1\/seo\/workbench\/(executions|content-workflows)\/(\d+)(?:\/(report|advance))?$/);
  if(url.pathname==='/api/v1/seo/workbench/notifications/read'){
    const row=state.executions.get(body.task_id),event=row?.task.notifications?.find(e=>e.id===body.event_id);
    if(!row||row.tenant!==tenant||!event){send(409,{detail:'Notification changed'});return true;}
    event.read=true;send(200,{event_id:event.id,read:true});return true;
  }
  if(url.pathname!==base&&!match)return false;
  const plan=state.plans.get(tenant),paused=plan.status==='paused',authorized=advisor&&!state.executionDenied;
  const project=row=>{const t=structuredClone(row.task),active=!['done','cancelled'].includes(t.status),may=authorized&&active,stem=`${base}/${t.id}`;return {...t,effective_pause:paused,read_only:true,allowed_actions:{advance:may&&!paused,cancel:may,retry_page_ids:may&&!paused?Object.entries(t.params.pages??{}).filter(([,v])=>v.state==='failed').map(([id])=>Number(id)):[],explain_report:may&&!paused&&!!t.params.report,retry_analytics_sources:may&&!paused&&!t.params.report?(t.retrySources??[]):[],prepare_incomplete_report:may&&!paused&&t.params.blocker==='analytics_source_requires_advisor'&&!t.params.report},links:{detail:`${stem}?tenant_id=${tenant}&site_id=${site}`,advance:t.action_type==='content_delivery'?`/api/v1/seo/workbench/content-workflows/${t.id}/advance`:`${stem}/advance`,cancel:stem,report:t.params.report?`${stem}/report?tenant_id=${tenant}&site_id=${site}`:null}};};
  if(url.pathname===base){const page=Number(url.searchParams.get('page')),size=Number(url.searchParams.get('page_size'));const rows=[...state.executions.values()].filter(row=>row.tenant===tenant&&(state.keywordLevel!=='none'||row.task.action_type!=='ranking_followup')).sort((a,b)=>b.task.id-a.task.id);send(200,{items:rows.slice((page-1)*size,page*size).map(project),total:rows.length,page,page_size:size,cycles:{website:{sequence:1,task_id:tenant*100+2,last_checked_at:'2026-10-07T08:00:00Z',next_due_at:'2026-10-14T08:00:00Z',blocker:null},monitoring:{blocker:'keyword_inventory_required'},report:{month:'2026-09',task_id:tenant*100+4}},read_only:true,as_of:'2026-10-07T08:02:00Z'});return true;}
  const row=state.executions.get(Number(match[2]));if(!row||row.tenant!==tenant){send(404,{detail:'Execution not found'});return true;}
  if(match[3]==='report'){
    if(!row.task.params.report){send(404,{detail:'Report not generated'});return true;}
    res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'private, no-store','Content-Disposition':`attachment; filename="seo-report-${row.task.id}.html"`,'Content-Security-Policy':"sandbox; default-src 'none'",ETag:`"${row.task.params.report.sha256}"`});res.end(row.html);return true;
  }
  if(req.method==='GET'){send(200,project(row));return true;}
  if(!authorized){send(403,{detail:'Advisor assignment revoked'});return true;}
  if(['done','cancelled'].includes(row.task.status)){send(409,{detail:{code:'execution_terminal'}});return true;}
  if(req.method==='DELETE'){row.task.status='cancelled';row.task.params.cancelled_by=7;send(200,{...project(row),read_only:false});return true;}
  if(paused){send(409,{detail:{code:'service_plan_paused'}});return true;}
  if(body?.explanation){
    if(body.report_sha256!==row.task.params.report?.sha256){send(409,{detail:{code:'report_version_conflict'}});return true;}
    row.task.params.explanation={text:body.explanation,actor_user_id:7,at:'2026-10-07T09:00:00Z'};row.task.status='done';row.task.params.phase='completed_with_evidence';row.task.completion_evidence={metric_key:'seo.reports.prepared_count',before:0,after:1,change_abs:1,as_of:'2026-10-07T09:00:00Z',source:{sha256:body.report_sha256},seo_effect:'not_evaluated'};
  }else if(body?.retry_analytics_source){
    row.task.retrySources=[];row.task.params.phase='awaiting_analytics_collection';
  }else if(body?.allow_incomplete_analytics){
    row.task.params.analytics_incomplete_ack={actor_user_id:7};row.task.params.phase='awaiting_advisor_explanation';
    row.task.params.report={format:'html',month:'2026-09',sha256:createHash('sha256').update(row.html).digest('hex'),pdf_generated:false,missing:['site_analytics_missing']};
  }else if(body?.retry_page_id){
    const p=row.task.params.pages?.[body.retry_page_id];if(p?.state!=='failed'){send(409,{detail:{code:'page_retry_not_available'}});return true;}p.state='observed';p.snapshot_id=105;p.run_id=104;
  }else if(row.task.action_type==='content_delivery'){row.task.params.phase='awaiting_publication';row.task.params.publication_id=body?.publication_id??null;}
  send(200,match[1]==='content-workflows'?row.task:{...project(row),read_only:false});return true;
}
