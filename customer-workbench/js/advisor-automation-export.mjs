import {automationScope,validateAutomationEvents,validateAutomationExport} from './advisor-automation-contract.mjs';

const cell=value=>{
  const text=value==null?'':String(value);
  // Spreadsheet applications may interpret a quoted cell as a formula.
  const safe=/^[\s\uFEFF]*[=+\-@]/u.test(text)?"'"+text:text;
  return '"'+safe.replaceAll('"','""')+'"';
};

export function automationEventsCsv(page,scope,runId=null,{afterId=0,limit=50}={}){
  automationScope(scope);
  const checked=validateAutomationEvents(page,scope,runId,{afterId,limit});
  const rows=[
    ['导出范围','当前授权项目的本页记录','模块',scope.module,'客户',scope.tenantId,'项目',scope.scopeId],
    ['后续记录',checked.next_after_id===null?'本页没有后续游标':'仍有后续记录，请继续分页查看'],
    ['事件序号','时间','模块','客户编号','项目编号','运行编号','步骤','主体','操作者编号','动作码','请求编号','费用状态','证据引用','安全变更前后'],
    ...checked.items.map(row=>[row.id,row.created_at,row.module,row.tenant_id,row.scope_id,row.run_id,row.step_key,
      row.actor_kind,row.actor_user_id,row.code,row.request_id,row.fee_state,row.evidence_refs.join(' | '),row.safe_changes?.length?JSON.stringify(row.safe_changes):'']),
  ];
  return {contents:'\uFEFF'+rows.map(row=>row.map(cell).join(',')).join('\r\n')+'\r\n',
    filename:`automation-${scope.module}-${scope.tenantId}-${scope.scopeId}-events-after-${afterId}.csv`};
}

export function downloadAutomationEvents(exported,browser){
  const url=browser.URL.createObjectURL(new browser.Blob([exported.contents],{type:'text/csv;charset=utf-8'}));
  const link=browser.document.createElement('a');
  try{link.href=url;link.download=exported.filename;browser.document.body.append(link);link.click();}
  finally{link.remove();browser.setTimeout(()=>browser.URL.revokeObjectURL(url),1000);}
}

export function automationWindowCsv(page,scope,{afterId=0,throughId=null,limit=500}={}){
  const checked=validateAutomationExport(page,scope,{afterId,throughId,limit});
  const exported=automationEventsCsv(checked,scope,null,{afterId,limit});
  return {...exported,contents:exported.contents.replace('当前授权项目的本页记录','当前授权项目历史窗口的本批记录')+
    ['窗口上界',checked.snapshot_upper_id,'本批起始游标',afterId,'本批条数',checked.items.length,'更多记录',checked.next_after_id??'无'].map(cell).join(',')+'\r\n',
    filename:`automation-${scope.module}-${scope.tenantId}-${scope.scopeId}-window-${checked.snapshot_upper_id}-after-${afterId}.csv`};
}
