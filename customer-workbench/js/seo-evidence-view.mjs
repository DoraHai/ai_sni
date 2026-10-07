const esc=v=>String(v??'未提供').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const json=v=>`<pre>${esc(JSON.stringify(v,null,2))}</pre>`;
export function aiRouteView(draft){
  const route=draft.generation_route;
  return `<section aria-label="模型来源"><p>领取时请求路由：供应商 ${esc(route?.provider)} · 请求模型 ${esc(route?.model)} · 地址 ${esc(route?.base_url)}</p><p>结果记录供应商：${esc(draft.provider)} · 结果记录的请求模型：${esc(draft.model)}</p><p>响应报告模型：${draft.response_model?esc(draft.response_model):'未返回，不能确认响应模型版本'}</p><p>请求路由与请求模型不代替供应商响应证据；旧记录缺失的来源保持未知。</p></section>`;
}
export function completionEvidenceView(evidence){
  if(!evidence)return '<p>未提供，不标为有证据的完成。</p>';
  const scoped=evidence.completion_basis==='target_object_evidence'&&evidence.scope&&typeof evidence.scope==='object'&&!Array.isArray(evidence.scope);
  if(!scoped)return `<p>其他或历史完成证据，按原字段展示；不推断新的对象口径。</p>${json(evidence)}`;
  const {effect_context,...target}=evidence;
  const labels={task_id:'任务',tenant_id:'客户',site_id:'站点',content_id:'稿件',publication_id:'发布记录',source_version:'稿件版本',page_id:'页面'};
  const scope=Object.entries(labels).filter(([key])=>evidence.scope[key]!=null).map(([key,label])=>`${label} ${esc(evidence.scope[key])}`).join(' · ');
  return `<section aria-label="目标对象完成证据"><h5>本任务目标对象的完成证据</h5><p>${scope||'范围字段未提供，请核对原始证据'}</p><p>${esc(evidence.metric_definition??evidence.meaning)} · 对象观察 ${esc(evidence.before)} → ${esc(evidence.after)} · 变化 ${esc(evidence.change_abs)}</p><p>0→1表示获得本任务对象的新证据，不表示全站数量净增长，也不证明搜索效果提升。站点总量或旧基线不参与此处重新判定完成。</p><details><summary>目标证据原始字段</summary>${json(target)}</details></section><section aria-label="全站效果背景"><h5>全站效果背景（独立于任务完成）</h5>${effect_context?json(effect_context):'<p>未提供；不以0补齐。</p>'}<p>背景允许持平、下降或历史基线未知，不将对象观察计数累加为站点统计。</p></section>`;
}
