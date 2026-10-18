import {pendingFeature,pendingBadge} from './pending-label.mjs';
import {createAdvisorAutomationClient} from './advisor-automation-client.mjs';
import {advisorRunView} from './advisor-run-view.mjs';
import {automationEventsCsv,automationWindowCsv,downloadAutomationEvents} from './advisor-automation-export.mjs';
import {escapeText as esc} from './customer-display.mjs';
import {automationTargetKey,validateAutomationConfiguration} from './advisor-automation-contract.mjs';
import {automationOperations,automationObjects} from './advisor-automation-labels.mjs';
import {projectAutomationAvailable} from './project-automation-availability.mjs';
const labels={visibility_patrol:'AI 引用巡检',periodic_project_workflow:'GEO 项目周期',manual_onsite_ai:'人工单独发起的 AI',content_cycle:'内容生产周期',service_diagnosis_cycle:'诊断周期',monitoring_cycle:'监测周期',monthly_report_cycle:'月报周期',qa_batches:'问答批次',image_verification:'图片核验',page_capture:'页面截图',ai_patrol:'AI 引用巡检',distribution:'内容分发',patrol_collection:'AI 引用巡检',configured_onsite_ai:'已配置站内 AI 草稿',ranking_collection:'排名采集',competitor_collection:'竞品采集',backlink_collection:'外链采集',platform_publication:'渠道发布',website_mutation:'官网修改',approval:'方案审批',acceptance:'业务验收'};
const aiOperations=new Set(['onsite_ai','content_draft','content_master_draft']);
const fees={not_called:'尚未发起调用',recorded:'已记录调用计量',unknown_charge:'供应商扣费结果待核实',unverified:'费用尚未核实'};
const projectBlockers={automation_schema_pending:'项目控制结构或执行权限尚未启用。',automation_owner_mismatch:'当前运行属于另一位负责人，请先核对顾问交接。'};
const eventLabels={project_configure:'顾问保存运行配置',project_start:'顾问开启本次运行',project_pause:'顾问请求暂停',project_resume:'顾问恢复运行',project_takeover:'顾问请求人工接管',project_end:'顾问结束本次运行',project_disable_cycle:'顾问停用后续周期',run_queued:'本次运行已排队',run_paused:'暂停收尾已完成',run_taken_over:'人工接管已完成',run_ended:'本次运行已结束',step_claimed:'系统领取待执行步骤',dispatch_admitted:'外部调用已登记',dispatch_limit:'已达到本次派发上限',step_succeeded:'自动步骤已产出，等待人工核验',project_end_project:'顾问结束项目及后续周期',external_call_admitted:'外部请求已登记准入',external_call_succeeded:'外部请求成功回执',external_call_failed:'外部请求失败回执',external_call_unknown:'外部请求结果待核实',external_call_stale:'外部请求已收尾，旧结果不采用',external_call_cancelled:'外部请求已取消',step_failed:'步骤执行失败',step_unknown:'执行结果待核实',step_stale:'结果依据已变化，未应用旧结果',step_cancelled:'步骤已取消',step_blocked:'步骤已阻塞'};
const errors={AUTOMATION_INVALID_WRITE:'配置不符合当前项目允许的能力或范围，请重新核对。',AUTOMATION_NOT_INTEGRATED:'项目控制尚未接入或等待启用。',AUTOMATION_CONFLICT:'项目版本或允许动作已变化，请重新核对。',AUTOMATION_WRITE_UNKNOWN:'写入结果尚未确认，请重新核对项目；不会自动重发。',AUTOMATION_CONTRACT_MISMATCH:'项目范围、版本或记录未通过核验，已停止展示。',PERMISSION_DENIED:'权限已变化，记录已清除。',AUTH_EXPIRED:'登录已失效，记录已清除。',CONTEXT_CHANGED:'账号范围已变化，旧结果未采用。'};
const scope=row=>({module:row.module,tenantId:row.tenant_id,scopeId:row.scope_id});
const projectKey=row=>[row.module,row.tenant_id,row.scope_id].join(':');
const normalizeProject=row=>({module:row.module,tenantId:row.tenant_id,scopeId:row.scope_id,name:row.scope_name||'项目 #'+row.scope_id,tenantName:row.tenant_name||'客户 #'+row.tenant_id,revision:row.version,state:row.state,endedAt:row.ended_at||null,projectControl:row.configuration?.contract_version===2||row.capabilities.available_operations.some(value=>value!=='onsite_ai'),blocker:projectBlockers[row.blocker]||row.blocker,cycleEnabled:row.cycle_enabled,nextRunAt:row.next_due_at,runId:row.current_run_id,available:row.capabilities.schema_state==='ready',availableOperations:row.capabilities.available_operations,allowedActions:row.allowed_actions,coverage:row.coverage.controlled.map(value=>labels[value]||automationOperations[value]||value),uncovered:row.coverage.not_controlled.map(value=>labels[value]||automationOperations[value]||value),config:row.configuration?{contractVersion:row.configuration.contract_version||1,ownerId:row.configuration.owner_user_id,taskIds:row.configuration.task_ids?.join(',')||'',targets:row.configuration.targets||[],servicePlan:row.configuration.service_plan||null,sourceBindings:row.configuration.source_bindings||[],maxDispatches:row.configuration.limits.max_dispatches_per_run,maxExternalCalls:row.configuration.limits.max_external_calls_per_run||1,cycleMode:row.configuration.cycle.mode,cycleEnabled:row.cycle_enabled}:null});
const normalizeRun=run=>({id:run.id,state:run.state,startedAt:run.started_at,finishedAt:run.finished_at,progress:run.progress,dispatchCount:run.dispatch_count,externalCount:run.steps.reduce((sum,step)=>sum+(step.calls?.length||0),0),currentStep:run.steps.find(step=>step.status==='running')?.step_key||'暂无正在执行的步骤',waitingFor:['waiting_human','waiting_input','taken_over'].includes(run.state)?'advisor':null,steps:run.steps.map(step=>({key:step.step_key,label:step.target?(automationOperations[step.kind]||step.kind)+' · '+(automationObjects[step.target.object_type]||step.target.object_type)+' #'+step.target.object_id+(step.target.variant?' · '+step.target.variant:''):'任务 #'+step.task_id+' · AI 起草',kind:step.kind,status:step.status,actor:aiOperations.has(step.kind)?'ai':'system',startedAt:step.started_at,finishedAt:step.finished_at,waitingFor:step.waiting_for,blocker:step.blocker,errorCode:step.error_code,taskId:step.task_id,feeLabel:fees[step.fee_state],evidenceRefs:step.evidence_refs,calls:(step.calls||[]).map(call=>({...call,feeLabel:fees[call.fee_state]}))}))});
const normalizeEvents=page=>({items:page.items.map(event=>({seq:event.id,at:event.created_at,actor:event.actor_kind,actorId:event.actor_user_id,action:eventLabels[event.code]||'执行事件',code:event.code,stepKey:event.step_key,requestId:event.request_id,runId:event.run_id,evidenceRefs:event.evidence_refs,feeLabel:fees[event.fee_state],safeChanges:event.safe_changes||[]})),nextAfterId:page.next_after_id,projectWide:page.run_id==null});
export function createAdvisorAutomationPanel({session,subscribeSession,fetchImpl,onChange,onDenied,tasksForProject=()=>[],browser=window}){
  const client=createAdvisorAutomationClient({session,subscribeSession,fetchImpl});
  let identity=null,modules=[],pages={},records={},epoch=0,disposed=false,pollTimer=null,visibleFilter='all';
  const visibleRecord=key=>modules.filter(module=>visibleFilter==='all'||visibleFilter===module).some(module=>pages[module]?.page?.items.some(row=>projectKey(row)===key));
  function changed(){if(!disposed)onChange();}
  function clear(){epoch++;identity=null;modules=[];pages={};records={};if(pollTimer)browser.clearTimeout(pollTimer);pollTimer=null;}
  const stop=client.subscribe(reason=>{if(['context_changed','expired','forbidden'].includes(reason)){clear();onDenied(reason);changed();}});
  function schedule(){
    if(pollTimer)browser.clearTimeout(pollTimer);pollTimer=null;
    if(disposed||Object.values(records).some(record=>record.draft||record.busy||record.blocked))return;
    const active=Object.entries(records).find(([key,record])=>visibleRecord(key)&&record.selected&&!record.historical&&!record.pollingStopped&&['active','pausing','taking_over','ending'].includes(record.project.state)&&!['waiting_input','waiting_human','taken_over','ended','failed'].includes(record.run?.state));
    if(!active)return;
    pollTimer=browser.setTimeout(()=>{pollTimer=null;if(browser.document?.hidden||!visibleRecord(active[0])){schedule();return;}void read(active[0],true,0,null,true);},15000);
  }
  async function list(module,beforeScopeId=null){
    const stamp=epoch;pages[module]={busy:true};changed();
    try{
      const page=await client.list(module,{beforeScopeId});if(disposed||stamp!==epoch)return;
      pages[module]={page};for(const row of page.items){const key=projectKey(row),previous=records[key];records[key]={...previous,project:row,busy:false,message:previous?.message||''};}changed();
    }catch(error){if(!disposed&&stamp===epoch){pages[module]={message:errors[error.code]||'项目读取未完成，请重试。'};changed();}}
  }
  async function read(key,detail=false,afterId=0,selectedRunId=null,automatic=false){
    const record=records[key];if(!record||record.busy)return;const stamp=epoch;let controlRead=false;record.busy=true;changed();
    if(!automatic){record.readFailures=0;record.pollingStopped=false;}
    try{
      const project=await client.readControl(scope(record.project));if(disposed||stamp!==epoch||records[key]!==record)return;
      record.project=project;controlRead=true;record.blocked=false;record.message='已读取当前项目状态。';
      const runId=selectedRunId||project.current_run_id||record.viewRunId;
      if(detail&&runId){const response=await client.run(scope(project),runId);if(disposed||stamp!==epoch||records[key]!==record)return;
        const events=await client.events(scope(project),runId,{afterId});if(disposed||stamp!==epoch||records[key]!==record)return;
        record.viewRunId=runId;record.run=response.run;record.events=events;record.eventsAfterId=afterId;record.selected=true;record.historical=runId!==project.current_run_id;}
      record.readFailures=0;
    }catch(error){if(!disposed&&stamp===epoch&&records[key]===record){record.message=errors[error.code]||'读取尚未完成，请重试。';record.blocked=!controlRead||error.code==='AUTOMATION_CONTRACT_MISMATCH';record.run=null;record.events=null;record.readFailures=(record.readFailures||0)+1;if(record.readFailures>=3){record.pollingStopped=true;record.message+=' 连续读取失败，已停止自动刷新，请重新核对。';}}}
    finally{if(!disposed&&stamp===epoch&&records[key]===record){record.busy=false;changed();schedule();}}
  }
  async function readHistory(key,beforeRunId=null){
    const record=records[key];if(!record||record.busy)return;const stamp=epoch;record.busy=true;changed();
    try{const history=await client.history(scope(record.project),{beforeRunId});if(disposed||stamp!==epoch||records[key]!==record)return;record.history=history;record.message='已读取当前项目的历史运行。';}
    catch(error){if(!disposed&&stamp===epoch&&records[key]===record){record.history=null;record.message=errors[error.code]||'历史读取未完成，请重试。';}}
    finally{if(!disposed&&stamp===epoch&&records[key]===record){record.busy=false;changed();schedule();}}
  }
  async function readProjectEvents(key,afterId=0){
    const record=records[key];if(!record||record.busy)return;const stamp=epoch;record.busy=true;changed();
    try{const events=await client.projectEvents(scope(record.project),{afterId});if(disposed||stamp!==epoch||records[key]!==record)return;record.events={...events,run_id:null};record.eventsAfterId=afterId;record.selected=false;record.message='已读取本项目的操作日志。';}
    catch(error){if(!disposed&&stamp===epoch&&records[key]===record){record.events=null;record.message=errors[error.code]||'日志读取未完成，请重试。';}}
    finally{if(!disposed&&stamp===epoch&&records[key]===record){record.busy=false;changed();schedule();}}
  }
  async function exportEvents(key){
    const record=records[key];if(!record||record.busy||!record.events)return;
    const stamp=epoch,currentScope=scope(record.project),runId=record.events.run_id||null,afterId=record.eventsAfterId||0;
    record.busy=true;record.message='正在重新核验本页日志的访问权限…';changed();
    try{
      // Re-read through the module's current authorization instead of exporting stale UI data.
      const page=runId?await client.events(currentScope,runId,{afterId}):await client.projectEvents(currentScope,{afterId});
      if(disposed||stamp!==epoch||records[key]!==record)return;
      const exported=automationEventsCsv(page,currentScope,runId,{afterId});
      downloadAutomationEvents(exported,browser);
      record.events={...page,run_id:runId};record.message='已导出重新核验后的本页日志；更多记录请继续分页，不代表全部历史。';
    }catch(error){if(!disposed&&stamp===epoch&&records[key]===record)record.message=errors[error.code]||'日志导出未完成，请重新核对。';}
    finally{if(!disposed&&stamp===epoch&&records[key]===record){record.busy=false;changed();schedule();}}
  }
  async function exportWindow(key,next=false){
    const record=records[key];if(!record||record.busy||next&&!record.exportWindow?.next_after_id)return;
    const stamp=epoch,afterId=next?record.exportWindow.next_after_id:0,throughId=next?record.exportWindow.snapshot_upper_id:null;
    record.busy=true;record.message='正在核验并读取历史窗口的一批日志（最多 500 条）…';changed();
    try{
      const page=await client.exportWindow(scope(record.project),{afterId,throughId});
      if(disposed||stamp!==epoch||records[key]!==record)return;
      downloadAutomationEvents(automationWindowCsv(page,scope(record.project),{afterId,throughId}),browser);
      record.exportWindow=page;record.message=page.next_after_id===null?'历史窗口已读取至上界；每个文件仅含本批记录。':'本批已导出；点击下一批继续读取同一窗口。';
    }catch(error){if(!disposed&&stamp===epoch&&records[key]===record){record.exportWindow=null;record.message=errors[error.code]||'历史窗口导出未完成，请重新核对。';}}
    finally{if(!disposed&&stamp===epoch&&records[key]===record){record.busy=false;changed();schedule();}}
  }
  async function write(key,action,configuration=null){
    const record=records[key];if(!record||record.busy||record.blocked)return;
    if(record.historical||!configuration&&!record.project.allowed_actions.includes(action))return;
    const stamp=epoch,project=structuredClone(record.project);let succeeded=false;record.busy=true;record.message='正在保存并核对操作…';changed();
    try{
      const requestId=browser.crypto.randomUUID();
      const result=configuration?await client.saveConfiguration(scope(project),project,configuration,requestId):await client.act(scope(project),project,action,requestId);
      if(disposed||stamp!==epoch||records[key]!==record)return;
      record.project=result;record.draft=null;record.basis=null;record.basisOperation=null;record.viewRunId=result.current_run_id||record.viewRunId;record.run=null;record.events=null;record.history=null;record.historical=false;record.message=configuration?'运行配置已保存，尚未开启运行。':'操作已记录，执行状态以当前记录为准。';record.blocked=false;succeeded=true;
    }catch(error){if(!disposed&&stamp===epoch&&records[key]===record){record.message=errors[error.code]||'操作未确认，请重新核对项目。';record.blocked=true;}}
    finally{if(!disposed&&stamp===epoch&&records[key]===record){record.busy=false;changed();if(succeeded&&!configuration&&record.project.current_run_id)void read(key,true);else schedule();}}
  }
  function formDraft(form,record){
    const previous=record?.draft||normalizeProject(record.project).config||{};
    return {...structuredClone(previous),contractVersion:Number(form.dataset.contractVersion)||1,
      selectedOperation:form.elements.operation?.value,taskIds:form.elements.task_ids?.value||'',maxDispatches:form.elements.max_dispatches.value,
      maxExternalCalls:form.elements.max_external_calls?.value||previous.maxExternalCalls||1,
      cycleMode:form.elements.cycle_mode.value,cycleEnabled:form.elements.cycle_enabled.checked};
  }
  function mergeBindings(first,second){
    const merged=new Map(first.map(row=>[JSON.stringify([row.kind,row.object_id]),row]));
    for(const row of second){const key=JSON.stringify([row.kind,row.object_id]),old=merged.get(key);
      if(old&&(old.revision!==row.revision||old.sha256!==row.sha256))return null;merged.set(key,row);}
    return merged.size<=8?[...merged.values()]:null;
  }
  function targetBindings(draft,targets=draft.targets||[]){
    let result=[];
    for(const operation of new Set(targets.map(target=>target.operation))){
      result=mergeBindings(result,draft.operationBindings?.[operation]||draft.sourceBindings||[]);
      if(!result)return null;
    }
    return result;
  }
  async function readBasis(key,operation,beforeObjectId=null){
    const record=records[key];if(!record||record.busy||!record.project.capabilities.can_configure||!record.project.capabilities.available_operations.includes(operation))return;
    const stamp=epoch;record.busy=true;record.message='正在核验可选目标与当前资料版本…';changed();
    try{
      const basis=await client.basis(scope(record.project),{operation,beforeObjectId});
      if(disposed||stamp!==epoch||records[key]!==record)return;
      const draft=record.draft||normalizeProject(record.project).config;
      if(draft?.contractVersion===2&&basis.state==='ready'&&
        (draft.servicePlan?.revision!==basis.service_plan.revision||draft.servicePlan?.sha256!==basis.service_plan.sha256||!mergeBindings(draft.sourceBindings||[],basis.source_bindings)||
          (draft.targets||[]).some(target=>basis.targets.some(row=>automationTargetKey(row)===automationTargetKey(target)&&(row.source_revision!==target.source_revision||row.source_hash!==target.source_hash))))){
        record.draft={...draft,targets:[],servicePlan:basis.service_plan,sourceBindings:basis.source_bindings,operationBindings:{[operation]:basis.source_bindings}};
        record.message='服务计划、范围资料或目标版本已变化，已清除旧目标；请重新选择后保存。';
      }else{
        if(draft?.contractVersion===2&&basis.state==='ready'){
          const updated={...draft,operationBindings:{...draft.operationBindings,[operation]:basis.source_bindings}};
          record.draft={...updated,sourceBindings:targetBindings(updated)||updated.sourceBindings};
        }
        record.message=basis.state==='ready'?'已读取当前资料版本的可选目标；尚未保存或开启运行。':'项目扩展结构等待启用，不能选择目标。';
      }
      record.basis=basis;record.basisOperation=operation;
    }catch(error){if(!disposed&&stamp===epoch&&records[key]===record){record.basis=null;record.message=errors[error.code]||'可选目标读取未完成，请重新核对。';}}
    finally{if(!disposed&&stamp===epoch&&records[key]===record){record.busy=false;changed();schedule();}}
  }
  function chooseTarget(record,form,key){
    if(!form||record.busy||record.blocked||record.basis?.state!=='ready')return;
    const row=record.basis.targets.find(target=>automationTargetKey(target)===key);if(!row)return;
    const {label,...target}=row,draft=formDraft(form,record);
    const bindings=mergeBindings(draft.contractVersion===2?draft.sourceBindings||[]:[],record.basis.source_bindings);
    if(!bindings){record.message='范围资料版本不一致，请重新读取并选择目标。';changed();return;}
    const targets=draft.contractVersion===2?[...(draft.targets||[])]:[];
    if(!targets.some(value=>automationTargetKey(value)===key)){if(targets.length>=20){record.message='每次最多选择 20 个执行目标。';changed();return;}targets.push(target);}
    const updated={...draft,contractVersion:2,targets,servicePlan:record.basis.service_plan,sourceBindings:bindings,
      operationBindings:{...draft.operationBindings,[target.operation]:record.basis.source_bindings}};
    record.draft={...updated,sourceBindings:targetBindings(updated)||bindings};
    record.message='已选择执行目标；保存配置后仍需明确开启运行。';changed();
  }
  return {
    assignedScopes(){return Object.values(pages).flatMap(value=>value.page?.items||[]).map(row=>({
      module:row.module,tenant_id:row.tenant_id,scope_id:row.scope_id,tenant_name:row.tenant_name,scope_name:row.scope_name}));},
    async initialize(availableModules){clear();const stamp=epoch;changed();try{identity=await client.initialize();if(disposed||stamp!==epoch)return;modules=availableModules.filter(module=>identity.modules.includes(module));changed();if(!projectAutomationAvailable)return;await Promise.all(modules.map(module=>list(module)));}catch(error){if(!disposed&&stamp===epoch){for(const module of modules)pages[module]={message:errors[error.code]||'项目身份核验未完成。'};changed();}}},
    html(filter='all'){
      visibleFilter=filter;
      if(!modules.length)return '';
      if(!projectAutomationAvailable)return modules.some(module=>filter==='all'||filter===module)?'<section class="advisor-automation-section"><h2>项目运行与记录</h2><p role="status">项目自动运行功能还没上线，目前不需要你操作。站内任务请看上面的「我的站内交付任务」。</p></section>':'';
      return `<section class="advisor-automation-section"><h2>项目运行与记录</h2><p>仅控制每个项目明确列出的能力。进入页面、读取状态和日志不会开启 AI；保存配置后还需明确开启。</p>${modules.filter(module=>filter==='all'||filter===module).map(module=>{const state=pages[module];return `<section class="advisor-automation-module" data-automation-module="${module}"><h3>${module.toUpperCase()} 项目 · 当前页${state?.message===errors.AUTOMATION_NOT_INTEGRATED?' '+pendingBadge():''}</h3>${state?.busy?'<p role="status">正在读取项目…</p>':''}${state?.message?`<p role="status">${esc(state.message)}</p>`:''}${(state?.page?.items||[]).map(row=>{const record=records[projectKey(row)];return advisorRunView({project:normalizeProject(record.project),run:record.run?normalizeRun(record.run):null,events:record.events?normalizeEvents(record.events):null,history:record.history,historical:record.historical,busy:record.busy,blocked:record.blocked,message:record.message,canConfigure:record.project.capabilities.can_configure,draft:record.draft,actorId:identity?.user.id,availableTasks:tasksForProject(record.project),basis:record.basis,basisOperation:record.basisOperation,exportWindow:record.exportWindow});}).join('')}${state?.page&&!state.page.items.length?'<p>当前页没有分配给你的项目。</p>':''}<div class="advisor-tools"><button data-automation-list="${module}" ${state?.busy?'disabled':''}>返回第一页并刷新项目</button>${state?.page?.next_before_scope_id?`<button data-automation-next="${module}" ${state?.busy?'disabled':''}>下一页项目</button>`:''}</div></section>`;}).join('')}</section>`;
    },
    click(event){if(!projectAutomationAvailable)return;const button=event.target.closest('button');if(!button||button.disabled)return;
      if(button.dataset.automationList)void list(button.dataset.automationList);
      if(button.dataset.automationNext){const module=button.dataset.automationNext;void list(module,pages[module]?.page?.next_before_scope_id);}
      const key=button.dataset.automationKey,action=button.dataset.automationAction,record=records[key];if(!record)return;
      if(action==='choose-task'){const form=button.closest('form'),id=Number(button.dataset.automationTask);if(!form||!tasksForProject(record.project).some(task=>task.id===id))return;const ids=form.elements.task_ids.value.split(/[,，\s]+/).filter(Boolean);if(!ids.includes(String(id)))ids.push(String(id));form.elements.task_ids.value=ids.join(',');record.draft=formDraft(form,record);changed();return;}
      if(action==='basis'){const form=button.closest('form');if(form)void readBasis(key,form.elements.operation.value);}
      else if(action==='next-basis')void readBasis(key,record.basisOperation,record.basis?.next_before_object_id);
      else if(action==='choose-target')chooseTarget(record,button.closest('form'),button.dataset.automationTarget);
      else if(action==='remove-target'){const form=button.closest('form');if(form){record.draft=formDraft(form,record);record.draft.targets=(record.draft.targets||[]).filter(target=>automationTargetKey(target)!==button.dataset.automationTarget);record.draft.sourceBindings=targetBindings(record.draft)||record.draft.sourceBindings;changed();}}
      else if(action==='read')void read(key,record.selected===true);
      else if(action==='logs'||action==='current-run')void read(key,true);
      else if(action==='next-logs'){if(record.events?.run_id==null)void readProjectEvents(key,record.events?.next_after_id||0);else void read(key,true,record.events?.next_after_id||0,record.viewRunId);}
      else if(action==='project-logs')void readProjectEvents(key);
      else if(action==='export-events')void exportEvents(key);
      else if(action==='export-window')void exportWindow(key);
      else if(action==='next-export-window')void exportWindow(key,true);
      else if(action==='history')void readHistory(key);
      else if(action==='older-runs')void readHistory(key,record.history?.next_before_run_id);
      else if(action==='open-run')void read(key,true,0,button.dataset.automationRun);
      else if(['start','pause','resume','takeover','end','end_project','disable_cycle'].includes(action))void write(key,action);
    },
    input(event){const form=event.target.closest('.advisor-automation-config');if(!form)return;const record=records[form.dataset.automationKey];if(record){record.draft=formDraft(form,record);if(pollTimer)browser.clearTimeout(pollTimer);pollTimer=null;}},
    submit(event){const form=event.target;if(!form.matches('.advisor-automation-config'))return;event.preventDefault();const record=records[form.dataset.automationKey];if(!record||!identity)return;
      const draft=formDraft(form,record);let configuration;
      try{
        if(draft.contractVersion===2){
          const targets=draft.targets||[];
          configuration={contract_version:2,operations:[...new Set(targets.map(target=>target.operation))],targets,
            service_plan:draft.servicePlan,source_bindings:draft.sourceBindings||[],
            cycle:{mode:draft.cycleMode,enabled:draft.cycleEnabled},
            limits:{max_dispatches_per_run:Number(draft.maxDispatches),max_external_calls_per_run:Number(draft.maxExternalCalls)},
            stop_condition:'drafts_ready_or_blocked',owner_user_id:identity.user.id};
        }else{
          const ids=draft.taskIds.split(/[,，\s]+/).filter(Boolean);
          if(ids.some(id=>!/^[1-9]\d*$/.test(id)))throw Error('invalid task id');
          configuration={task_ids:ids.map(Number),operations:['onsite_ai'],cycle:{mode:draft.cycleMode,enabled:draft.cycleEnabled},
            limits:{max_dispatches_per_run:Number(draft.maxDispatches)},stop_condition:'drafts_ready_or_blocked',owner_user_id:identity.user.id};
        }
        validateAutomationConfiguration(configuration);
      }catch{record.message='请选择 1–20 个不同的有效目标，步骤上限为 1–20，外部请求上限为 1–100；仅本次模式不能启用后续周期。';changed();return;}
      void write(form.dataset.automationKey,'configure',configuration);
    },
    invalidate(){clear();client.invalidate('parent_cleared');},
    dispose(){disposed=true;clear();stop();client.dispose();},
  };
}
