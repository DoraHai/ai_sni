import {escapeText as esc} from './customer-display.mjs';
const phases={draft:'待制定方案',review:'待人工审核',implementation:'待网站实施',recheck:'待系统复检',acceptance:'待人工验收',done:'已验收',cancelled:'已取消'};
const labels={title:'Title',description:'Description',meta_keywords:'Keywords',keyword:'关键词部署',internal_link:'内链',robots:'robots 文件',sitemap:'网站地图',canonical:'SEO 架构与规范地址',structured_content:'官网结构化内容',knowledge:'知识库',faq:'FAQ',schema:'Schema 标记',llms:'llms.txt'};
const actions={save_proposal:'保存方案并提交审核',approve:'审核当前方案',implement:'记录网站实施',recheck:'抓取页面复检',accept:'人工验收',cancel:'取消任务'};
const nextSteps={draft:'顾问制定方案，核对本轮重点与资料',review:'顾问核实方案并审核准确版本',implementation:'网站维护人员实施已批准的修改',recheck:'顾问发起真实页面复检',acceptance:'顾问核对复检证据并人工验收',done:'交付已验收，效果按后续观测评价',cancelled:'任务已取消，后续安排由顾问确认'};
const aiStates={running:'AI 正在起草方案，请刷新查看结果',ready:'AI 提案已保存，审核以当前方案版本为准',failed:'AI 生成失败，需要顾问核查',unknown:'AI 调用结果未知，需要顾问核查后决定下一步',stale:'AI 结果已过期，以当前任务版本为准'};
export function onsiteTaskStatus(task){
  const w=task?.workflow||{};
  return {phase:phases[w.phase]||'状态待核对',next:nextSteps[w.phase]||'请顾问核对任务状态',
    ai:aiStates[w.ai_run?.state]||(task?.capabilities?.ai_planning?.enabled===true?'AI 规划已接通，由顾问明确发起':'AI 规划尚未接入，当前由顾问制定方案')};
}
function aiProposalView(w){
  const p=w.ai_proposal;if(!p)return '';
  const refs=values=>(Array.isArray(values)?values:[]).map(v=>typeof v==='string'||typeof v==='number'?String(v):v?.label||v?.id||'已授权资料').join('、');
  return `<details><summary>AI 提案理由与待补资料</summary>${p.summary?`<p>${esc(p.summary)}</p>`:''}${(p.items||[]).map(i=>`<p>清单 ${esc(i.id)}：${esc(i.reason||'请顾问核对依据')}${i.source_refs?.length?` · 来源：${esc(refs(i.source_refs))}`:''}${i.missing_information?.length?` · 待补：${esc(refs(i.missing_information))}`:''}</p>`).join('')}${p.missing_information?.length?`<p>本轮待补资料：${esc(refs(p.missing_information))}</p>`:''}</details>`;
}
const button=(text,action,disabled=false,extra='')=>`<button data-action="onsite-${action}" ${disabled?'disabled':''} ${extra}>${esc(text)}</button>`;
export function onsiteView(data,selected,busy,module='seo'){
  const title=module==='seo'?'SEO 站内优化':'GEO 官网与知识建设';
  const w=selected?.workflow,canEdit=w&&selected.allowed_actions.includes('save_proposal')&&!busy;
  return `<h2>${title}</h2><p>顾问确认本月重点与方案，系统保存版本并复检真实页面；网站维护人员实施，顾问最终验收。</p><p>官网自动修改暂未接入，按批准方案人工实施。交付复检与搜索收录、排名和 AI 引用效果分别记录。</p>
    <div>${button('刷新任务','refresh',busy)}${data?.next_before_id?button('读取下一页','next',busy,`data-before="${data.next_before_id}"`):''}${button('回到最新任务','latest',busy)}</div>
    ${data?data.items.map(t=>{const s=onsiteTaskStatus(t);return `<article class="phase-row"><b>${esc(t.title)} #${t.id}</b><p>${esc(s.phase)} · ${esc(t.workflow.month||({startup:'启动建设',monthly:'月度优化',remediation:'专项整改'}[t.workflow.work_type]))} · 实施负责人：${esc(t.workflow.owner_name)}</p><p>下一步：${esc(s.next)}</p><p>${esc(s.ai)}</p>${button('方案与验收','select',busy,`data-id="${t.id}"`)}</article>`;}).join('')||'<p>当前没有站内任务。</p>':'<p>正在核验任务范围…</p>'}
    ${data?.can_create?`<details><summary>建立站内任务</summary><label>工作类型<select id="onsite-type"><option value="startup">项目启动基础建设</option><option value="monthly">每月重点优化</option><option value="remediation">专项整改</option></select></label><label>服务月份<input id="onsite-month" type="month"></label><label>网站实施负责人<input id="onsite-owner" maxlength="100" placeholder="填写实际实施人员"></label>${module==='seo'?`<label>重点关键词编号（可留空，采用 P0/P1，最多 3 个）<input id="onsite-keywords" placeholder="如：12,18"></label><label>页面编号（可留空，月度任务采用关键词部署页面，最多 3 个）<input id="onsite-pages" placeholder="如：5,8"></label>`:''}${button('建立任务','create',busy)}</details>`:'<p>客户可查看任务。创建、方案审核、实施回填与验收需要当前网站或项目的顾问资格。</p>'}
    ${w?`<section class="onsite-detail"><h3>${esc(selected.title)} #${selected.id} · v${w.revision}</h3><p>${esc(phases[w.phase])} · 服务月份 ${esc(w.month||'不适用')} · 创建顾问 #${esc(w.advisor_user_id)}</p>
      <p>下一步：${esc(onsiteTaskStatus(selected).next)}</p><p>${esc(onsiteTaskStatus(selected).ai)}</p>
      ${selected.allowed_actions.includes('save_proposal')?`<p>${esc(selected.capabilities?.ai_planning?.reason||'AI 规划能力尚未接入，当前可由顾问编辑方案。')}</p>${selected.capabilities?.ai_planning?.enabled===true&&selected.capabilities.ai_planning.can_generate===true&&!['running','unknown'].includes(w.ai_run?.state)?button(w.recheck?.passed===false?'AI 提出修订方案':'AI 起草站内方案','ai-proposal',busy,`data-id="${selected.id}"`):''}`:''}
      ${aiProposalView(w)}
      <label>网站实施负责人<input id="onsite-task-owner" value="${esc(w.owner_name)}" maxlength="100" ${canEdit?'':'disabled'}></label>
      ${w.items.map(i=>`<article class="phase-row" data-onsite-item="${esc(i.id)}"><h4>${esc(labels[i.kind])}</h4><p>${esc(i.instruction)}</p><label>目标页面或文件<input id="onsite-url-${esc(i.id)}" data-onsite-field="target_url" value="${esc(i.target_url)}" maxlength="2048" ${canEdit?'':'disabled'}></label><label>经核实的预期内容${i.kind==='schema'?'（JSON）':''}<textarea id="onsite-expected-${esc(i.id)}" data-onsite-field="expected" maxlength="12000" ${canEdit?'':'disabled'}>${esc(i.expected)}</textarea></label></article>`).join('')}
      ${selected.allowed_actions.length?`<label>本次说明与依据<textarea id="onsite-note" maxlength="4000" placeholder="审核：事实与适用条件；实施：实际修改位置；验收：质量核对结论。" ${busy?'disabled':''}></textarea></label><div>${selected.allowed_actions.map(a=>button(actions[a],a,busy,`data-id="${selected.id}"`)).join('')}</div>`:''}
      ${w.approval?`<p>方案审核：用户 #${esc(w.approval.actor)} · ${esc(w.approval.at)} · ${esc(w.approval.note)}</p>`:''}
      ${w.implementation?`<p>实施记录：${esc(w.implementation.note)}</p>`:''}
      ${w.recheck?`<h4>实际页面复检</h4><p>${w.recheck.passed?'本次检查均匹配，等待人工核对质量':'仍有检查未通过，请修改网站后再次复检'} · ${esc(w.recheck.at)}</p>${w.recheck.results.map(r=>`<p>${r.passed?'通过':'未通过'} · ${esc(r.id)} · ${esc(r.target_url)} · ${esc(r.reason||r.observed_excerpt||'')} </p>`).join('')}`:''}
      ${w.acceptance?`<p>人工验收：用户 #${esc(w.acceptance.actor)} · ${esc(w.acceptance.note)}</p>`:''}
      <details><summary>任务记录与范围依据</summary><p>当前网站：${esc(w.domain)} · 顾问：#${esc(w.advisor_user_id)}</p>${module==='seo'?`<p>重点关键词：${esc((w.source?.keywords||[]).map(k=>`${k.keyword} #${k.id}`).join('、')||'无')}</p>`:''}<ol>${w.history.map(h=>`<li>${esc(h.at)} · ${esc(actions[h.action]||({ai_proposal:'AI 起草方案',ai_start:'AI 开始起草',ai_failed:'AI 起草失败'}[h.action])||'任务记录')} · 用户 #${esc(h.actor)} · ${esc(h.note||'')}</li>`).join('')}</ol></details></section>`:''}`;
}
export function onsiteCreateInput(root,module='seo'){
  const ids=id=>{const value=root.querySelector(id)?.value.trim();if(!value)return [];const values=value.split(/[,，]/).map(v=>Number(v.trim()));if(values.length>3||values.some(n=>!Number.isSafeInteger(n)||n<=0))throw Error('编号请填写最多 3 个正整数，用逗号分隔');return values;};
  return {work_type:root.querySelector('#onsite-type').value,month:root.querySelector('#onsite-month').value||null,owner_name:root.querySelector('#onsite-owner').value.trim(),...(module==='seo'?{keyword_ids:ids('#onsite-keywords'),page_ids:ids('#onsite-pages')}:{})};
}
export function onsiteActionInput(root,selected,action){
  const note=root.querySelector('#onsite-note')?.value.trim()||'';
  if(action!=='save_proposal'){
    if(action!=='cancel'&&selected.allowed_actions.includes('save_proposal')){const draft=onsiteActionInput(root,selected,'save_proposal');if(JSON.stringify(draft.items)!==JSON.stringify(selected.workflow.items)||draft.owner_name!==selected.workflow.owner_name)throw Error('方案有未保存修改，请先保存方案后再处理审核或验收');}
    return {note};
  }
  const items=selected.workflow.items.map(i=>{const el=[...root.querySelectorAll('[data-onsite-item]')].find(e=>e.dataset.onsiteItem===i.id);return {...i,target_url:el.querySelector('[data-onsite-field=target_url]').value.trim(),expected:el.querySelector('[data-onsite-field=expected]').value.trim()};});
  return {items,note,owner_name:root.querySelector('#onsite-task-owner').value.trim()};
}

