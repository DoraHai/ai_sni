import {escapeText as esc} from './customer-display.mjs';
import {automationTargetKey} from './advisor-automation-contract.mjs';
import {automationOperations,automationObjects} from './advisor-automation-labels.mjs';

export function advisorAutomationConfigView({key,project,draft,actorId,availableTasks=[],basis=null,basisOperation=null,disabled=false}){
  const config=draft||project.config||{},typed=config.contractVersion===2||project.availableOperations&&!project.availableOperations.includes('onsite_ai'),targets=config.targets||[];
  const operation=config.selectedOperation||basisOperation||project.availableOperations?.[0]||'onsite_ai';
  const options=(project.availableOperations||['onsite_ai']).map(value=>`<option value="${esc(value)}" ${value===operation?'selected':''}>${esc(automationOperations[value]||value)}</option>`).join('');
  const button=(action,label,extra='')=>`<button type="button" data-automation-action="${action}" data-automation-key="${key}" ${extra} ${disabled?'disabled':''}>${label}</button>`;
  return `<details ${draft?'open':''}><summary>运行范围与调用上限配置</summary><form class="advisor-automation-config" data-automation-key="${key}" data-contract-version="${typed?2:1}">
    <div class="advisor-wide"><label>后台已接入的能力<select name="operation">${options}</select></label>${button('basis','读取本能力的可选目标与资料版本')}
      <p>可选目标由后端核验当前分配、服务计划及资料版本。读取不启动运行，也不调用 AI。</p></div>
    ${typed?`<div class="advisor-wide"><p>已选择 ${targets.length} 个目标（最多 20 个）：</p><ol>${targets.map(target=>`<li>${esc(automationOperations[target.operation]||target.operation)} · ${esc(automationObjects[target.object_type]||target.object_type)} #${target.object_id}${target.variant?' · '+esc(target.variant):''} · 资料版本 ${target.source_revision}${button('remove-target','移除',`data-automation-target="${esc(automationTargetKey(target))}"`)}</li>`).join('')||'<li>尚未选择目标。</li>'}</ol>
      <p>服务计划版本：${config.servicePlan?.revision??'尚未读取'}。范围绑定 ${config.sourceBindings?.length||0} 项；资料发生变化时需要重新选择。</p></div>`:
      `${availableTasks.length?`<div class="advisor-wide"><p>从当前页已获分配的待制定任务中选择：</p>${availableTasks.map(task=>button('choose-task',`加入 #${task.id} · ${esc(task.title||'站内任务')}`,`data-automation-task="${task.id}"`)).join('')}</div>`:'<p class="advisor-wide">当前任务页没有本项目可选择的待制定任务；可在上方原模块任务列表中翻页或核对任务编号。</p>'}
      <label class="advisor-wide">已选本站内任务编号<input name="task_ids" value="${esc(config.taskIds||'')}" maxlength="350" placeholder="已有任务，如 123,124" required></label>`}
    ${basis?`<div class="advisor-wide"><p>当前页可选目标：</p>${basis.state==='ready'?basis.targets.map(target=>button('choose-target',`${esc(target.label||automationObjects[target.object_type]||target.object_type)} #${target.object_id}${target.variant?' · '+esc(target.variant):''} · 版本 ${target.source_revision}`,`data-automation-target="${esc(automationTargetKey(target))}"`)).join('')||'<p>当前页没有符合条件的目标。</p>':'<p>项目扩展结构或执行权限等待启用，不能选择目标。</p>'}
      ${basis.next_before_object_id?button('next-basis','下一页目标'):''}</div>`:''}
    <label>本次步骤派发上限<input name="max_dispatches" type="number" min="1" max="20" value="${esc(config.maxDispatches||1)}" required></label>
    ${typed?`<label>本次外部请求上限<input name="max_external_calls" type="number" min="1" max="100" value="${esc(config.maxExternalCalls||1)}" required></label>`:''}
    <label>运行方式<select name="cycle_mode"><option value="once" ${!config.cycleMode||config.cycleMode==='once'?'selected':''}>仅本次运行</option><option value="daily" ${config.cycleMode==='daily'?'selected':''}>每日周期</option><option value="monthly" ${config.cycleMode==='monthly'?'selected':''}>每月周期</option></select></label>
    <label class="advisor-wide"><input name="cycle_enabled" type="checkbox" ${config.cycleEnabled===true?'checked':''}>明确启用后续周期（仅每日或每月模式）</label>
    <p class="advisor-wide">本轮产出后等待顾问处理；结束本次运行后，才按每日或每月方式安排下一轮。系统不会自动通过审核或验收。</p>
    ${typed?'<p class="advisor-wide">已保存接管的操作需保留，可替换其执行目标；本批不能通过删除操作交回旧调度器。停止整个项目请使用“结束项目”，该操作关闭后续运行并保留接管记录。</p>':''}
    <p class="advisor-wide">负责人为当前实名顾问 #${esc(actorId)}。自动产出采集记录、分析或待审草稿；阻塞或需要人工时停止推进。已有待审草稿不会自动重做。</p>
    <p class="advisor-wide">保存配置不会开启运行。步骤和请求次数限制不代替金额预算；审批、官网实施和最终验收由人工完成。此控制仅作用于项目明确列出的能力。</p>
    <button ${disabled?'disabled':''}>保存运行配置</button></form></details>`;
}
