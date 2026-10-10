import {visiblePlatformAlerts} from './platform-alert-archive.mjs';

export function renderUsagePanel({snapshot,history,esc,card,table,tenant,time,providerLabel}){
  const option=(v,label,selected)=>`<option value="${esc(v)}" ${String(v)===String(selected)?'selected':''}>${esc(label)}</option>`;
  const select=(name,label,options)=>`<label>${label}<select name="${name}">${option('','全部',history.filters[name])}${options.map(([v,l])=>option(v,l,history.filters[name])).join('')}</select></label>`;
  const rows=history.data?.rows||[],f=history.filters;
  const filters=`<form id="pc-usage-query" class="pc-ops-form"><label>开始日期<input name="from" type="date" value="${esc(f.from)}" required></label><label>结束日期<input name="to" type="date" value="${esc(f.to)}" required></label>
    ${select('tenant_id','客户',[[0,'未归属客户'],...(snapshot.sources.tenants?.rows||[]).map(r=>[r.id,r.name])])}
    ${select('user_id','账号',[[0,'后台任务 / 无登录账号'],...(snapshot.sources.users?.rows||[]).map(r=>[r.id,r.username])])}
    ${select('module','模块',[['sem','SEM'],['seo','SEO'],['geo','GEO']])}
    ${select('provider','服务商',[...new Set((snapshot.api_costs?.provider_totals||[]).map(r=>r.provider))].map(p=>[p,providerLabel(p)]))}
    ${select('state','调用状态',[['requested','等待结果'],['succeeded','成功'],['error','失败'],['unknown','结果未知']])}
    ${select('unpriced','定价状态',[['true','费用未知'],['false','已计价']])}
    <label>具体接口<input name="endpoint" maxlength="200" value="${esc(f.endpoint||'')}" placeholder="完整接口路径，可留空"></label>
    <label>模型<input name="model" maxlength="120" value="${esc(f.model||'')}" placeholder="模型名称，可留空"></label>
    <div class="pc-ops-actions"><button ${history.busy?'disabled':''}>${history.busy?'正在查询…':'查询明细'}</button><button type="button" data-pc="usage-export" ${history.busy?'disabled':''}>导出 CSV</button></div></form>`;
  let results=history.error?`<p role="alert" class="pc-note">${esc(history.error)}</p>`:history.data?history.data.state!=='available'?'<p class="pc-note">调用台账尚未启用。</p>':
    `<p class="pc-note">匹配 ${history.data.total} 条 · 未定价 ${history.data.unpriced} 条 · 已计价部分 ¥${esc(history.data.known_amount)} · 查询截至 ${esc(time(history.data.as_of))}</p>`+
    table(['时间 / 请求编号','客户 / 账号','模块 / 服务商','接口 / 模型','状态 / 耗时','Token 输入 / 输出','估算费用'],rows.map(r=>[
      `${esc(time(r.started_at))}<small class="pc-cell-note">${esc(r.provider_request_id||r.id)}</small>`,`${esc(tenant(r.tenant_id))}<small class="pc-cell-note">${esc((snapshot.sources.users?.rows||[]).find(u=>u.id===r.user_id)?.username||r.job_ref||'系统任务')}</small>`,
      `${esc(r.module?.toUpperCase())}<small class="pc-cell-note">${esc(providerLabel(r.provider))}</small>`,`${esc(r.endpoint)}<small class="pc-cell-note">${esc(r.model||'按次接口')}</small>`,
      `${esc({requested:'等待结果',succeeded:'成功',error:'失败',unknown:'结果未知'}[r.state]||r.state)}<small class="pc-cell-note">${r.latency_ms==null?'耗时未知':esc(r.latency_ms)+' ms'}</small>`,
      `${r.prompt_tokens??'未知'} / ${r.completion_tokens??'未知'}`,r.estimated_amount==null?'待定价':`${esc(r.currency)} ${esc(r.estimated_amount)}`]))+
    `<div class="pc-ops-actions"><button data-pc="usage-prev" ${history.busy||!history.cursors.length?'disabled':''}>上一页</button><span>第 ${history.cursors.length+1} 页</span><button data-pc="usage-next" ${history.busy||!history.data.next_cursor?'disabled':''}>下一页</button></div>`:
    '<p class="pc-note">选择条件后查询完整台账；此处可查看最近 50 条以外的记录。</p>';
  return card('完整调用明细与导出',filters+results,'按北京时间筛选；空费用表示未知。CSV 每次最多 50000 条，超出会提示缩小范围，不截断导出。');
}

export function renderAlertsPanel({snapshot,selected,esc,card,table,tenant,time,users}){
  const enabled=snapshot.operations?.state==='enabled',alerts=visiblePlatformAlerts(snapshot);
  const label={open:'待处理',in_progress:'处理中',resolved:'已标记处理'};
  const current=alerts.find(a=>a.id===selected)||alerts[0];
  const content=table(['客户','告警','处理状态','处理人','处理说明'],alerts.map(a=>[
    esc(tenant(a.tenant_id)),esc(a.message),esc(label[a.handling?.status]||'待处理'),
    esc(users.find(u=>u.id===a.handling?.owner_id)?.username||'未认领'),esc(a.handling?.note||'未填写')]));
  const form=current?`<form id="pc-alert-operation" class="pc-ops-form"><label>选择告警<select name="alert_id">${alerts.filter(a=>a.id).map(a=>`<option value="${esc(a.id)}" ${a===current?'selected':''}>${esc(a.message)}</option>`).join('')}</select></label>
    <label>操作<select name="action"><option value="claim">认领</option><option value="resolve">标记已处理</option><option value="reopen">重新打开</option></select></label>
    <label class="pc-ops-wide">处理说明<textarea name="note" maxlength="500" placeholder="记录处理结果；不要填写密钥或密码"></textarea></label><button ${enabled?'':'disabled'}>保存处理记录</button></form>`:'';
  return card('告警与处理',content+form,enabled?'标记已处理仅记录处理结果；相同来源出现新异常时重新提醒。':'告警仍可查看，处理记录等待数据库审核启用。')+
    card('服务商近期运行',table(['模块','服务商','24 小时调用','异常','最后异常'],(snapshot.operations?.provider_health||[]).map(r=>[
      esc(r.module?.toUpperCase()),esc(r.provider),r.calls,r.failed,esc(time(r.last_failure))])),
      '来自真实调用结果；24 小时异常至少 3 次且占比达到 20% 时提醒。不额外发起付费探测。外部通知渠道待接入。');
}

export function renderSuppliersPanel({snapshot,selected,esc,card,table,time}){
  const records=snapshot.operations?.suppliers||[],hosts=[...new Set((snapshot.controls?.bindings||[]).map(r=>r.host).filter(Boolean))].sort();
  const host=hosts.includes(selected)?selected:hosts[0],row=records.find(r=>r.host===host)||{};
  const input=(name,label,type='number')=>`<label>${label}<input name="${name}" type="${type}" ${type==='number'?'min="0" step="any"':''} value="${esc(row[name]??'')}"></label>`;
  const form=host?`<form id="pc-supplier-operation" class="pc-ops-form"><label>服务商接口域名<select name="host">${hosts.map(h=>`<option value="${esc(h)}" ${h===host?'selected':''}>${esc(h)}</option>`).join('')}</select></label>
    <label>币种<select name="currency"><option value="CNY" ${row.currency==='USD'?'':'selected'}>CNY</option><option value="USD" ${row.currency==='USD'?'selected':''}>USD</option></select></label>
    ${input('balance','当前余额')}${input('warning_balance','余额提醒阈值')}${input('remaining_calls','剩余套餐次数')}${input('warning_calls','次数提醒阈值')}${input('expires_on','套餐到期日','date')}
    <button ${snapshot.operations?.state==='enabled'?'':'disabled'}>保存额度登记</button></form>`:'<p class="pc-note">接口管理启用并登记服务商后，可维护余额与套餐余量。</p>';
  return card('服务商余额与套餐登记',table(['服务商','人工登记余额','剩余次数','到期日','最近登记'],records.map(r=>[
    esc(r.host),r.balance==null?'未登记':`${esc(r.currency)} ${esc(r.balance)}`,r.remaining_calls??'未登记',esc(r.expires_on||'未登记'),esc(time(r.updated_at))]))+form,
    '此处为人工登记，标明更新时间；尚未自动同步服务商余额。留空表示未知，币种分别记录，不能直接合计。');
}

export function renderBackupPanel({snapshot,esc,card,table,time}){
  const backup=snapshot.operations?.backup;
  return card('数据库备份与恢复记录',table(['完成时间','范围','备份结果','归档校验','恢复验证'],(backup?.records||[]).map(r=>[
    esc(time(r.completed_at)),'公共业务库',r.state==='succeeded'?'备份成功':'备份失败',r.archive_verified?'已通过':'未验证',r.restore_verified?'已验证':'待恢复演练'])),backup?.note||'尚未收到数据库备份结果。');
}
