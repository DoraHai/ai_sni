const uuid=value=>typeof value==='string'&&/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(value);
const states=['requested','unknown','succeeded','error'];
const sources=['provider_request_record','provider_billing_record','provider_support_record'];
export const usageReviewRoute='/api/v1/admin/console/usage/review';
export const canReviewUsage=snapshot=>snapshot?.usage_reviews?.schema===1&&snapshot.usage_reviews.state==='enabled'&&snapshot.usage_reviews.capabilities?.includes('usage_review_v1');
export const reviewableUsageRow=row=>uuid(row?.id)&&row.can_review!==false&&Number.isSafeInteger(row.review_version)&&row.review_version>=0&&states.includes(row.state)&&
  (row.review_version>0?row.verified_amount==null:['requested','unknown'].includes(row.state)||row.estimated_amount==null);
const providerHost=row=>/^[a-zA-Z0-9.-]+(?=\/|$)/.exec(row.endpoint||'')?.[0]?.toLowerCase();

export function usageReviewPayload({row,fields,requestId}){
  const fail=message=>{throw Error(message);};
  const allowed=['event_id','terminal_state','provider_request_id','verified_amount','source','reference','sha256','summary','observed_at','terminal_confirmed','zero_charge_confirmed'];
  if(!reviewableUsageRow(row)||fields.event_id!==row.id||!uuid(requestId)||Object.keys(fields).some(k=>!allowed.includes(k)))fail('记录或版本已变化，请重新查询调用明细。');
  if(!['succeeded','error'].includes(fields.terminal_state)||fields.terminal_confirmed!=='on')fail('必须先核实供应商终态并明确确认。');
  if(['succeeded','error'].includes(row.state)&&row.state!==fields.terminal_state)fail('已有确定终态不能改为另一终态，请核对原记录。');
  const amount=fields.verified_amount?.trim()||null;
  if(amount!==null&&!/^(?:0|[1-9]\d{0,11})(?:\.\d{1,12})?$/.test(amount))fail('费用须为非负人民币金额，最多保留 12 位小数。');
  if(amount!==null&&Number(amount)>1000000000)fail('单次核实金额不能超过十亿元，请核对记录。');
  if(!sources.includes(fields.source)||amount!==null&&fields.source==='provider_request_record')fail('核实费用需要供应商账务或客服证据，请求记录只能确认终态。');
  if(amount!==null&&Number(amount)===0&&fields.zero_charge_confirmed!=='on')fail('登记零费用必须有供应商明确的零扣款证据。');
  if(fields.zero_charge_confirmed==='on'&&(amount===null||Number(amount)!==0))fail('零扣款确认只能用于明确的零费用，不能用于未知或非零金额。');
  const clean=(name,max)=>{const value=fields[name]?.trim();if(!value||value.length>max||/[\x00-\x1f]/.test(value))fail('请完整填写证据编号、摘要、请求编号与核对时间。');return value;};
  const request=clean('provider_request_id',100),reference=clean('reference',200),summary=clean('summary',500);
  if(summary.length<10)fail('核实说明至少需要 10 个字，请说明终态与账务依据。');
  if(row.review_version>0&&row.reviewed_provider_request_id!==request)fail('供应商请求编号必须与先前核实证据一致，不能改绑其它调用。');
  const sha=clean('sha256',64).toLowerCase(),host=providerHost(row),observed=new Date(fields.observed_at);
  if(!/^[0-9a-f]{64}$/.test(sha)||!host||!Number.isFinite(observed.getTime()))fail('证据摘要、接口归属或核对时间无效。');
  return {request_id:requestId,event_id:row.id,expected_version:row.review_version,expected_state:row.state,
    terminal_state:fields.terminal_state,provider_request_id:request,verified_amount:amount,currency:amount===null?null:'CNY',
    evidence:{source:fields.source,provider_host:host,reference,sha256:sha,summary,observed_at:observed.toISOString(),terminal_confirmed:true,zero_charge_confirmed:fields.zero_charge_confirmed==='on'}};
}

export function renderUsageReview({snapshot,history,esc,card}){
  if(!canReviewUsage(snapshot))return card('调用费用人工核实','<p>核实操作尚未启用。</p>','证据、审计和数据库权限完成审核后启用。不会把未知费用归零或强制释放调用占用。');
  const rows=(history.data?.rows||[]).filter(reviewableUsageRow),listed=rows.find(r=>r.id===history.reviewEventId)||rows[0];
  if(!listed)return card('调用费用人工核实','<p>先查询调用明细，再选择精确请求进行核实。</p>');
  const fresh=history.reviewRecord?.id===listed.id,row=fresh?{...listed,...history.reviewRecord}:listed;
  const blocked=history.reviewBlocked||history.busy||history.reviewBusy||history.reviewReadBusy||!fresh||row.can_review!==true;
  const select=(name,label,options,selected=null)=>`<label>${label}<select name="${name}" required>${options.map(([value,text])=>`<option value="${esc(value)}" ${value===selected?'selected':''}>${esc(text)}</option>`).join('')}</select></label>`;
  return card('调用费用人工核实',`<form id="pc-usage-review" class="pc-ops-form">
    <label class="pc-ops-wide">具体调用<select name="event_id">${rows.map(r=>`<option value="${esc(r.id)}" ${r.id===row.id?'selected':''}>${esc(r.id+' · '+r.module+' / '+r.provider+' · '+r.state)}</option>`).join('')}</select></label>
    <p class="pc-note pc-ops-wide">接口 ${esc(row.endpoint)} · 记录版本 ${esc(row.review_version)} · 原估算 ${esc(row.estimated_amount??'未知')} · 人工核实费用 ${esc(row.verified_amount??'未知')}</p>
    ${select('terminal_state','供应商确认的终态',[['succeeded','成功结束'],['error','失败结束']],row.state)}
    <label>供应商请求编号<input name="provider_request_id" maxlength="100" value="${esc(row.reviewed_provider_request_id||row.provider_request_id||'')}" ${row.reviewed_provider_request_id||row.provider_request_id?'readonly':''} required></label>
    <label>核实费用（人民币）<input name="verified_amount" inputmode="decimal" maxlength="25" placeholder="留空表示仍未知"></label>
    ${select('source','证据来源',[['provider_request_record','供应商请求记录（仅终态）'],['provider_billing_record','供应商账务记录'],['provider_support_record','供应商客服核实记录']])}
    <label>证据编号 / 引用<input name="reference" maxlength="200" required></label>
    <label>证据文件摘要（SHA-256）<input name="sha256" pattern="[A-Fa-f0-9]{64}" minlength="64" maxlength="64" required></label>
    <label>核对时间<input name="observed_at" type="datetime-local" required></label>
    <label class="pc-ops-wide">核实说明<textarea name="summary" minlength="10" maxlength="500" required placeholder="说明已核实的终态与扣款依据；不要填写密钥或密码"></textarea></label>
    <label class="pc-ops-wide"><input name="terminal_confirmed" type="checkbox" required>我已人工核验供应商证据，确认这次调用已结束。</label>
    <label class="pc-ops-wide"><input name="zero_charge_confirmed" type="checkbox">供应商账务或客服证据明确确认本次零扣款（仅登记零费用时勾选）。</label>
    <button ${blocked?'disabled':''}>${history.reviewBusy?'正在提交核实…':history.reviewBlocked?'请先重新查询明细核对':'提交核实并记录审计'}</button></form>`,
    '核实只作用于选中的调用。金额留空不能据此放行金额预算；仅确认终态可结束并发占用。系统记录人工证据签认，不宣称已自动验证第三方票据。未知提交结果不会自动重试。');
}
