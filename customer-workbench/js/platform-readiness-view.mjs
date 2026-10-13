import {escapeText as esc} from './customer-display.mjs';
export function balanceNotifications(data,time,now=Date.now()){
  const notes=[];
  if(data?.schema!==1||data.state!=='available')return notes;
  for(const row of data.rows||[]){const age=now-Date.parse(row.queried_at);
    if(row.state==='available'&&row.warning==='low'&&age>=0&&age<=360000)notes.push({tenant_id:row.tenant_id,severity:'warning',message:row.name+' 余额低于预警阈值，请核对充值安排（查询时间 '+time(row.queried_at)+'）。'});}
  const o=data.observations;
  if(o?.schema===1&&o.state==='available'&&o.freshness==='needs_recheck')notes.push({tenant_id:null,severity:'warning',message:'站长之家套餐余量需重新核对，人工核验日期 '+o.verified_on+'；刷新不会更新人工余量。'});
  for(const p of o?.state==='available'?o.packages||[]:[])if(p.enabled===true&&['expired','expiring'].includes(p.expiry_warning))notes.push({tenant_id:null,severity:'warning',message:p.name+' '+(p.expiry_warning==='expired'?'已到期':'30天内到期')+'，请核对套餐安排。'});
  return notes;
}
export function readinessRows({snapshot,automation,balances,balanceError=''}){
  const rows=[['余额自动查询',balanceError?'读取失败':balances?'本次已读取':'等待读取',balanceError||'进入超管自动读取首批余额，每5分钟可见页面刷新；百度推广账户按批查看。']];
  for(const row of balances?.rows||[])rows.push([row.name+' 查询',({available:'本次查询成功',not_configured:'缺查询凭据',permission_denied:'授权不足',account_mismatch:'账务账号不一致',unsupported:'供应商查询暂不支持'}[row.state]||'本次查询失败'),row.state==='available'?'核对实际账务归属；多个连接共享的金额不能相加。':'通过安全保险柜配置专用只读凭据，查询失败不使用历史金额。']);
  rows.push(['站长之家套餐',balances?.observations?.freshness==='needs_recheck'?'需要人工重核':balances?.observations?.state==='available'?'已显示日期记录':'记录待接入','供应商暂无已验证的官方余量接口；按日期核验，账户现金与套餐次数分别展示。']);
  for(const module of ['seo','geo']){const r=automation?.modules?.[module];rows.push([module.toUpperCase()+' 项目运维',r?.data?.state==='available'?'本次已读取':r?.data?.state==='schema_pending'?'结构待审核':({not_deployed:'接口未部署',invalid:'响应未核验',unavailable:'读取失败',loading:'正在读取'}[r?.state]||'尚未核验'),'当前进程心跳不代表全部服务；超管只查看，进入客户范围后处理项目。']);}
  const latest=snapshot.operations?.backup?.records?.[0];
  rows.push(['预算/接口/密钥管理',snapshot.controls?.state==='enabled'?'运行管理已启用':'等待审核启用','经结构审核和发布配置后生效，未启用不代表预算保护生效。'],['告警处理记录',snapshot.operations?.state==='enabled'?'已启用':'等待审核启用','认领与处理记录复用审计；外部通知还需渠道和收件人配置与验收。'],['完整管理审计','已提供查询与CSV入口','覆盖已登记管理动作；接口与审计表仍需服务端部署。'],['数据库备份',latest?.state==='succeeded'?'已有成功记录':'待有效运维记录','需实际备份任务和归档校验，发布回滚不等于数据库恢复。'],['数据库恢复演练',latest?.restore_verified===true?'记录显示已验证':'仍需隔离恢复演练','演练结果必须来自实际恢复，不通过页面勾选产生证明。'],['实际账单对账','待供应商账单依据','估算、人工核实与实际账单分别核对，不能用余额差额推算单次调用费。'],['SEM AI接管','本轮保持人工处理','按既定要求暂不启用SEM AI接管；官网自动修改也继续预留。']);
  return rows;
}
export function renderReadiness({snapshot,automation,balances,balanceError,card,table}){
  return card('当前接入与剩余条件',table(['能力','本次状态','完成条件'],readinessRows({snapshot,automation,balances,balanceError}).map(row=>row.map(esc))),'状态来自本次已读取的数据，不代表生产已发布；缺接口、缺凭据、待审核和缺证据分别列出。');
}
