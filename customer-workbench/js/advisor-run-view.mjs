import {escapeText as esc} from './customer-display.mjs';
import {advisorAutomationConfigView} from './advisor-automation-config-view.mjs';
import {automationChangeLabels} from './advisor-automation-labels.mjs';
import {workbenchPath,geoWorkbenchPath} from './workbench-entry.mjs';

const controls={schema_pending:'等待启用',not_started:'尚未开启',active:'自动推进中',running:'自动推进中',queued:'已排队',waiting_input:'等待有效任务或资料',waiting_human:'等待人工',blocked:'已阻塞',pausing:'暂停收尾中',paused:'已暂停',taking_over:'人工接管收尾中',taken_over:'已由人工接管',ending:'结束收尾中',ended:'本次已结束',idle:'当前无自动运行',failed:'运行失败',disabled:'未启用'};
const steps={pending:'尚未执行',queued:'已排队',running:'正在执行',waiting_human:'等待人工',blocked:'已阻塞',succeeded:'自动步骤已产出',failed:'执行失败',unknown:'结果待核实',stale:'依据或版本已变化',cancelled:'已取消',paused:'已暂停'};
const actions={start:'开启本次运行',pause:'暂停自动推进',resume:'恢复自动推进',takeover:'人工接管',end:'结束本次运行',end_project:'结束项目并停用后续周期',disable_cycle:'停用后续周期'};
const actors={human:'人工',system:'系统',ai:'AI'};
const waiting={advisor:'顾问',customer:'客户',website_maintainer:'网站维护人员',operator:'操作人员',system:'系统'};
const text=value=>value==null||value===''?'未提供':esc(String(value));
const time=value=>value==null?'未提供':Number.isFinite(Date.parse(value))?esc(new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})):'时间未通过核验';
const reason=value=>typeof value==='string'?text(value):text(value?.message||value?.code);
const references=items=>items?.length?`<p>证据引用：${items.map(text).join('、')}</p>`:'';
const callStates={admitted:'已登记准入，等待回执',succeeded:'请求回执成功',failed:'请求失败',unknown:'请求结果待核实',stale:'旧结果未采用',cancelled:'已取消'};
const changeValue=value=>value===null?'未设置':typeof value==='object'?JSON.stringify(value):String(value);
const changes=items=>items?.length?`<details class="advisor-audit-changes"><summary>查看修改前后（${items.length} 项）</summary>${items.map(row=>`<p><strong>${text(automationChangeLabels[row.path]||row.path)}</strong><br>修改前：${text(changeValue(row.before))}<br>修改后：${text(changeValue(row.after))}</p>`).join('')}</details>`:'';
const calls=items=>items?.length?`<details class="advisor-calls"><summary>外部请求回执（${items.length} 条）</summary><ol>${items.map(call=>`<li>${text(call.call_key)} · ${call.kind==='provider'?'API / 供应商请求':'网页读取'} · ${callStates[call.state]||'待核验'}<p>准入 ${time(call.admitted_at)} · 收尾 ${time(call.finished_at)}</p><p>费用状态：${text(call.feeLabel)}</p>${references(call.evidence_refs)}</li>`).join('')}</ol></details>`:'';

export function automationTaskLink(scope,id){
  if(!Number.isSafeInteger(id)||id<1||!Number.isSafeInteger(scope.tenantId)||scope.tenantId<1||!Number.isSafeInteger(scope.scopeId)||scope.scopeId<1||!['seo','geo'].includes(scope.module))return null;
  return (scope.module==='geo'?geoWorkbenchPath(scope.tenantId,scope.scopeId):workbenchPath(scope.tenantId,scope.scopeId))+'&'+new URLSearchParams({onsite_task_id:id});
}

function automationProjectLink(scope){
  return scope.module==='geo'?geoWorkbenchPath(scope.tenantId,scope.scopeId):workbenchPath(scope.tenantId,scope.scopeId);
}

export function advisorRunView({project,run=null,events=null,history=null,historical=false,busy=false,blocked=false,message='',canConfigure=false,draft=null,actorId=null,availableTasks=[],basis=null,basisOperation=null,exportWindow=null}){
  const scope={module:project.module,tenantId:project.tenantId,scopeId:project.scopeId},key=[scope.module,scope.tenantId,scope.scopeId].join(':');
  const controlsAvailable=project.available===true,disabled=busy||blocked||historical||!controlsAvailable;
  const buttons=(project.allowedActions||[]).filter(action=>Object.hasOwn(actions,action)).map(action=>`<button type="button" data-automation-action="${action}" data-automation-key="${key}" ${disabled?'disabled':''}>${actions[action]}</button>`).join('');
  const button=(action,label)=>`<button type="button" data-automation-action="${action}" data-automation-key="${key}" ${busy?'disabled':''}>${label}</button>`;
  const config=draft||project.config||{},pending=Number.isSafeInteger(project.pendingCalls)&&project.pendingCalls>=0?project.pendingCalls:null;
  const outcome=run?.outcome;
  const controlLabel=project.endedAt&&project.state==='idle'?'项目已结束':project.state==='active'&&['waiting_human','waiting_input'].includes(run?.state)?controls[run.state]+'（自动运行已开启）':controls[project.state]||'状态待核验';
  return `<article class="advisor-automation" data-automation-project="${key}">
    <h3>${text(project.name)} · ${scope.module.toUpperCase()} ${project.projectControl?'项目自动推进':'站内 AI 自动推进'}</h3>
    <p>${text(project.tenantName||'客户 #'+scope.tenantId)} · 项目 #${scope.scopeId} · 控制版本 ${text(project.revision)}</p>
    <p>运行负责人：${project.config?.ownerId?'顾问 #'+text(project.config.ownerId):'尚未保存配置'}</p>
    <p><strong>${controlLabel}</strong> · 后续周期：${project.cycleEnabled===true?'已启用':project.cycleEnabled===false?'未启用':'未提供'}</p>
    ${project.endedAt?`<p>项目结束时间：${time(project.endedAt)}。后续周期已关闭；重新开启需重新保存明确配置。</p>`:''}
    ${project.blocker?`<p>控制阻塞：${reason(project.blocker)}</p>`:''}
    <p>控制覆盖：${Array.isArray(project.coverage)&&project.coverage.length?project.coverage.map(text).join('、'):'接口尚未提供覆盖范围'}</p>
    ${project.uncovered?.length?`<p>尚未接入控制：${project.uncovered.map(text).join('、')}</p>`:''}
    ${pending!==null?`<p>已发出且未结束的请求：${pending}。暂停和结束不能撤回第三方已发生的请求。</p>`:''}
    <p>下一周期时间：${project.nextRunAt?time(project.nextRunAt):'未安排'}</p>
    <p>暂停、接管和结束会阻止新的自动步骤；已发出的外部请求仍需收尾，费用和执行结果会保留记录。</p>
    ${message?`<p role="status">${esc(message)}</p>`:''}
    ${historical?`<p>正在查看历史运行，启停按钮已禁用。请先返回当前运行再操作。</p>${button('current-run','返回当前运行')}`:''}
    ${!controlsAvailable?'<p>项目控制尚未接入或等待启用，当前页面不会开启自动运行。</p>':''}
    <div class="advisor-tools">${buttons}${button('read','重新核对项目状态')}${project.runId?button('logs','查看本次步骤与日志'):''}${button('project-logs','项目操作日志')}${button('history','历史运行')}${button('export-window','导出历史窗口首批 CSV')}${exportWindow?.next_after_id?button('next-export-window','导出同一窗口下一批 CSV'):''}</div><p>历史导出每批最多 500 条，每批重新核验权限；窗口上界固定，文件只包含本批记录。</p>
    ${canConfigure&&controlsAvailable?advisorAutomationConfigView({key,project,draft,actorId,availableTasks,basis,basisOperation,disabled}):''}
    ${run?`<section class="advisor-run"><h4>本次运行 ${text(run.id)}</h4><p>状态：${controls[run.state]||steps[run.state]||'待核验'} · 开始 ${time(run.startedAt)} · 结束 ${time(run.finishedAt)}</p>
      <p>当前步骤：${text(run.currentStep)} · 等待：${waiting[run.waitingFor]||text(run.waitingFor)}</p>
      ${run.progress?`<p>计划 ${run.progress.total_steps} 步 · 已收口 ${run.progress.terminal_steps} 步 · 执行中 ${run.progress.running_steps} 步 · 待推进 ${run.progress.waiting_steps} 步。收口包含失败或阻塞，不代表业务交付完成。</p>`:''}
      ${Number.isSafeInteger(run.dispatchCount)?`<p>本次已领取 ${run.dispatchCount} 个步骤；已记录 ${run.externalCount??0} 条外部请求准入。准入记录不代表业务成功或费用已核实。</p>`:''}
      ${run.blocker?`<p>阻塞原因：${reason(run.blocker)}</p>`:''}
      <ol class="advisor-steps">${(run.steps||[]).map(step=>`<li><strong>${text(step.label||step.kind||step.key)}</strong> · ${steps[step.status]||'状态待核验'} · 执行主体：${actors[step.actor]||'未提供'}<p>开始 ${time(step.startedAt)} · 结束 ${time(step.finishedAt)}</p>${step.waitingFor?`<p>等待 ${waiting[step.waitingFor]||text(step.waitingFor)}</p>`:''}${step.blocker?`<p>${reason(step.blocker)}</p>`:''}${step.errorCode?`<p>结果码：${text(step.errorCode)}</p>`:''}${step.feeLabel?`<p>费用状态：${text(step.feeLabel)}</p>`:''}${references(step.evidenceRefs)}${calls(step.calls)}${step.taskId&&automationTaskLink(scope,step.taskId)?`<a href="${esc(automationTaskLink(scope,step.taskId))}">查看原模块方案与成果</a>`:step.kind&&step.kind!=='onsite_ai'?`<a href="${esc(automationProjectLink(scope))}">进入所属项目核对成果与证据</a>`:''}</li>`).join('')||'<li>尚无已记录步骤，不据此推断执行完成。</li>'}</ol>
      <h4>成果与证据</h4><p>${outcome?text(outcome):'尚无成果结论。步骤完成与业务验收、排名、收录及引用效果分别记录。'}</p></section>`:''}
    ${history?`<section class="advisor-run-history"><h4>历史运行 · 当前页</h4><ol>${history.items.map(item=>`<li>${text(item.id)} · ${controls[item.state]||'待核验'} · ${time(item.started_at)}<button type="button" data-automation-action="open-run" data-automation-key="${key}" data-automation-run="${esc(item.id)}" ${busy?'disabled':''}>查看步骤与记录</button></li>`).join('')||'<li>当前页尚无历史运行。</li>'}</ol>${history.next_before_run_id?button('older-runs','更早运行'):''}</section>`:''}
    ${events?`<section class="advisor-events"><h4>${events.projectWide?'项目操作日志':'本次执行与操作记录'}</h4><ol>${events.items.map(event=>`<li>#${event.seq} · ${time(event.at)} · ${actors[event.actor]||'未提供'}${event.actorId?' #'+text(event.actorId):''} · ${text(event.action)}<p>${text(event.summary||event.code)}</p>${event.stepKey?`<p>步骤 ${text(event.stepKey)}</p>`:''}${event.requestId?`<p>请求编号 ${text(event.requestId)}</p>`:''}${events.projectWide&&event.runId?`<p>运行 ${text(event.runId)}</p>`:''}${references(event.evidenceRefs)}${changes(event.safeChanges)}${event.feeLabel?`<p>费用状态：${text(event.feeLabel)}</p>`:''}</li>`).join('')||'<li>当前页没有事件记录。</li>'}</ol>${events.nextAfterId?button('next-logs','读取后续记录'):''}${button('export-events','导出本页日志 CSV')}<p>只显示当前授权项目的脱敏记录。费用未知不能按零费用处理。</p></section>`:''}
    ${blocked?'<p>上次写入结果未确认或版本已变化，请先重新核对权威记录，系统不会自动重发。</p>':''}
  </article>`;
}
