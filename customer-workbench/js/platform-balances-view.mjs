import {pendingBadge} from './pending-label.mjs';
import {escapeText as esc} from './customer-display.mjs';
export const balanceRoute='/api/v1/admin/console/balances';
const labels={available:'已查询',not_configured:'未配置余额查询凭据',unsupported:'当前接入点不支持',permission_denied:'查询授权不足',account_mismatch:'账务账号不一致',rate_limited:'供应商限流',error:'查询失败',timeout:'查询超时',unavailable:'未接入'};
const money=(value,currency)=>typeof value==='string'&&/^-?\d+(\.\d+)?$/.test(value)&&['CNY','USD','JPY'].includes(currency)?esc(currency+' '+value):'未知';
const strategies={direct:'可查官方余额',billing_authorization:'需账务授权',account:'按推广账户查询',package:'剩余次数 / 到期日',quota:'调用配额',pending:'余额接口待接入'};
const configLabel=r=>r.enabled===false?'已停用':r.configured===true?'已配置':r.configured===false?'未配置':'配置待核对';
const breakdown=b=>[['cash','现金 / 充值'],['grant','赠额 / 代金券'],['income','收益转入'],['credit','信用额度'],['available_credit','含信用额度可用金额'],['frozen','冻结'],['arrears','欠费']].filter(([field])=>b[field]!=null).map(([field,label])=>`<small class="pc-cell-note">${label} ${money(b[field],b.currency)}</small>`).join('')||'未返回明细';
export function renderObservations({observations,card,table}){
  if(!observations||observations.schema!==1||observations.state!=='available')return card('人工核验与套餐余量','<p>人工核验记录尚未读取。</p>','实时查询只更新供应商接口结果。');
  const o=observations,verified=esc(o.verified_on||'日期未知');
  const packages=Array.isArray(o.packages)?o.packages:[],reported=Array.isArray(o.reported_balances)?o.reported_balances:[],services=Array.isArray(o.services)?o.services:[];
  const quotaLabel={exhausted:'核验时已耗尽',low:'核验时余量低',normal:'核验时余量正常'};
  const expiryLabel={expired:'已到期',expiring:'30 天内到期',normal:'尚未到期'};
  const count=value=>Number.isSafeInteger(value)&&value>=0?String(value):'未知';
  const account=o.package_account;
  return card('授权测试记录（历史核验）',`<p>用户核验日期 ${verified} · ${o.freshness==='needs_recheck'?'需重新核对':'当日核验记录'}</p>`+
    table(['供应商 / 账户','核验金额','查询口径'],reported.map(r=>[esc(r.name),money(r.amount,r.currency),esc(r.basis)])),
    '以下是用户提供的测试结果，不代表当前接口已配置、已查询成功，也不参与实时余额预警。')+
    card('站长之家账户与套餐余量',`<p>后台人工核验于 ${verified} · ${o.freshness==='needs_recheck'?'余量需重新核对':'余量为核验时数值'}</p>`+
    (account?`<p>${esc(account.account_id)} · 核验账户余额 ${money(account.balance,account.currency)}<small class="pc-cell-note">账户余额与已购套餐余量分别展示。</small></p>`:'')+
    table(['接口 / 套餐','核验剩余次数','已用 / 总次数','核验开通状态','到期日','核验余量提醒'],packages.map(r=>[
      esc(r.name),count(r.remaining),`${count(r.used)} / ${count(r.total)}`,r.enabled===true?'已开通':r.enabled===false?'已关闭':'未知',
      `${esc(r.expires_on)}<small class="pc-cell-note">${esc(expiryLabel[r.expiry_warning]||'未知')}</small>`,
      `<span class="pc-tag ${['exhausted','low'].includes(r.quota_warning)?'pc-tag-warning':''}">${esc(quotaLabel[r.quota_warning]||'无法判断')}</span>`])),
    '人工核验数据；实时查询按钮不会更新这些余量。核验记录不从本地调用次数推算当前余量。')+
    card('开通与查询范围',table(['服务','核验状态','说明'],services.map(r=>[esc(r.name),r.state==='not_opened'?'核验账号未开通':'待核对',esc(r.note)])),
    `用户核验日期 ${verified}；产品开通状态与模型或搜索 Key 是否配置分别核对。`);
}
export function renderCoverage({coverage,rows,card,table,time}){
  if(!coverage)return card('API 接入与余额覆盖','<p>当前接口尚未提供全部服务覆盖清单。</p>','已接入服务的余额查询正在逐项接通。');
  const items=coverage.rows||[],results=new Map(rows.map(r=>[r.id,r]));
  const known=items.filter(r=>typeof r.configured==='boolean').length;
  const content=['sem','seo','geo'].map(module=>{
    const list=items.filter(r=>r.module===module);
    return list.length?`<details open class="pc-balance-coverage"><summary><b>${module.toUpperCase()} · ${list.length} 个接口 / 套餐项</b></summary>`+table(['服务 / 套餐','接入配置','查询口径','余额查询状态','说明与下一步'],list.map(r=>{
      const live=results.get(r.balance_row_id);
      const name=r.capability==='pending'?`<b>${esc(r.name)}</b> ${pendingBadge()}<small class="pc-cell-note">余额查询接口尚未接入，余额与预警保持未知。</small>`:esc(r.name);
      return [name,`${esc(configLabel(r))}<small class="pc-cell-note">${r.configuration_source==='sem_runtime'?'本服务运行配置':r.configuration_source==='service_registry'?`最近服务登记 · ${esc(time(r.configuration_seen_at))}`:'独立服务配置尚未取得'}</small>`,esc(strategies[r.capability]||'待核对'),live?`${esc(labels[live.state]||'未知')}<small class="pc-cell-note">${live.state==='available'?live.balances.map(b=>money(b.available,b.currency)).join('<br>'):'余额未知'}</small>`:r.enabled===false?'已停用，未查询':r.capability==='direct'?'查询凭据待接入':r.capability==='billing_authorization'?'账务授权待接入':r.capability==='account'?'见推广账户余额':'未知',esc(r.note||'')];
    }))+'</details>':'';
  }).join('');
  return card('API 接入与余额覆盖',`<p>${items.length} 个接口 / 套餐项 · ${known} 项配置已取得 · ${items.length-known} 项配置待核对</p>`+content,
    '清单包含系统支持的服务；配置待核对不表示未接入。模型 Key、查询凭据和账务账户各有范围，多个接口可能共享余额，金额不汇总相加。');
}
export function renderBalances({state,card,table,time}){
  const rows=state.data?.rows||[];
  return card('实时余额与预警',`<div class="pc-shortcuts"><button data-pc="balance-refresh" ${state.busy?'disabled':''}>${state.busy?'正在查询余额…':'实时查询余额'}</button></div><p role="status">${esc(state.error||'进入超管即读取首批余额；页面可见时每5分钟刷新全局余额预警。进入本页读取当前批次，手动查询读取供应商最新余额，连续点击5秒内复用最近结果。')}</p>`+
    table(['供应商 / 账户','余额（按查询口径）','金额明细（接口返回）','状态与来源','预警','查询时间'],rows.map(r=>[
      `<b>${esc(r.name)}</b><small class="pc-cell-note">${esc(r.tenant_name||'共享平台账户')}${r.billing_account_id?` · 账务账号 ${esc(r.billing_account_id)}`:''}</small>`,
      r.state==='available'?r.balances.map(b=>money(b.available,b.currency)+(b.balance_kind==='cash'?'<small class="pc-cell-note">现金账户余额</small>':'')).join('<br>'):'未知',
      r.state==='available'?r.balances.map(breakdown).join('<br>'):'未知',
      `${esc(labels[r.state]||'未知')}<small class="pc-cell-note">${esc(r.note||'')} · ${r.state==='available'?(r.cached?'最近查询结果':'供应商查询'):'未取得余额'}</small>`,
      `${r.warning==='low'?'<span class="pc-tag pc-tag-warning">余额不足预警</span>':r.warning==='normal'?'未触及预警阈值':'无法判断'}${r.balances.map(b=>b.warning_threshold!=null?`<small class="pc-cell-note">提醒阈值 ${money(b.warning_threshold,b.currency)}</small>`:'').join('')}`,
      esc(time(r.queried_at))
    ]))+
    (state.data?.next_after_id?`<button data-pc="balance-next" ${state.busy?'disabled':''}>查看下一批推广账户</button>`:'')+
    (state.cursors.length?`<button data-pc="balance-first" ${state.busy?'disabled':''}>返回首批账户</button>`:''),
    '阿里云余额覆盖同一云账户全部服务；DeepSeek 官方账户与百炼上的 DeepSeek 模型分开。余额查询不进行充值或修改预算。页面关闭后停止自动刷新，查询失败显示未知。')+
    (!state.error&&state.data?renderObservations({observations:state.data.observations,card,table})+renderCoverage({coverage:state.data.coverage,rows,card,table,time}):'');
}
