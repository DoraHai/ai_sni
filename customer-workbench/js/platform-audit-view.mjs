import {escapeText as esc} from './customer-display.mjs';
export const auditRoute='/api/v1/admin/console/audit';
const fields=new Set(['from','to','actor_id','action','cursor','page_size']);
export function auditPath(filters={},exporting=false){
  if(!filters||typeof filters!=='object'||Array.isArray(filters)||Object.keys(filters).some(k=>!fields.has(k)))
    throw Object.assign(Error('CONSOLE_INVALID_QUERY'),{code:'CONSOLE_INVALID_QUERY'});
  const query=new URLSearchParams(Object.entries(filters).filter(([,v])=>v!==''&&v!=null).map(([k,v])=>[k,String(v)]));
  return auditRoute+(exporting?'/export':'')+(query.size?'?'+query:'');
}
export function renderAudit({state,card,table,time}){
  const filters=state.filters,rows=state.data?.rows||[];
  return card('完整管理审计',`<form id="pc-audit-query" class="pc-ops-form">
    <label>开始日期<input name="from" type="date" value="${esc(filters.from)}" required></label>
    <label>结束日期<input name="to" type="date" value="${esc(filters.to)}" required></label>
    <label>管理员ID<input name="actor_id" type="number" min="1" step="1" value="${esc(filters.actor_id||'')}"></label>
    <label>操作<select name="action"><option value="">全部</option>${['budget.update','provider.update','rate.update','credential.update','connection.update','user.create','user.update','user.password','role.create','role.update','role.delete','alert.claim','alert.resolve','alert.reopen','supplier.update','usage.review'].map(action=>`<option ${filters.action===action?'selected':''}>${action}</option>`).join('')}</select></label>
    <button ${state.busy?'disabled':''}>查询审计</button><button data-pc="audit-export" type="button" ${state.busy?'disabled':''}>导出 CSV</button></form>
    <p role="status">${esc(state.error||(state.busy?'正在读取…':state.data?.state==='schema_pending'?'管理审计结构尚未就绪。':state.data?'查询截至 '+time(state.data.as_of):'选择条件后读取完整记录。'))}</p>`+
    table(['时间','管理员ID','操作','资源类型','记录字段','审计ID'],rows.map(r=>[
      esc(time(r.created_at)),esc(r.actor_id),esc(r.action),esc(r.resource_kind),esc((r.recorded_fields||[]).join('、')),esc(r.id)]))+
    `<div class="pc-ops-actions"><button data-pc="audit-first" ${state.busy?'disabled':''}>返回首批</button><button data-pc="audit-next" ${state.busy||!state.data?.next_cursor?'disabled':''}>下一批</button></div>`,
    '覆盖已接入管理审计的操作，每页最多100条，CSV最多5000条，超出须缩小筛选范围。仅导出时间、操作者、动作和字段名，原始值、凭据及正文不导出。详细变更前后值仍在原有安全运维页面核查。');
}
