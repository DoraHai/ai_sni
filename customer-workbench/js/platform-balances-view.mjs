import {escapeText as esc} from './customer-display.mjs';
export const balanceRoute='/api/v1/admin/console/balances';
const labels={available:'已查询',not_configured:'未配置余额查询凭据',unsupported:'当前接入点不支持',permission_denied:'查询授权不足',rate_limited:'供应商限流',error:'查询失败',timeout:'查询超时',unavailable:'未接入'};
const money=(value,currency)=>typeof value==='string'&&/^-?\d+(\.\d+)?$/.test(value)&&['CNY','USD','JPY'].includes(currency)?esc(currency+' '+value):'未知';
export function renderBalances({state,card,table,time}){
  const rows=state.data?.rows||[];
  return card('实时余额与预警',`<div class="pc-shortcuts"><button data-pc="balance-refresh" ${state.busy?'disabled':''}>${state.busy?'正在查询余额…':'实时查询余额'}</button></div><p role="status">${esc(state.error||'进入本页自动读取；页面可见时每 5 分钟刷新。手动查询读取供应商最新余额，连续点击 5 秒内复用最近结果。')}</p>`+
    table(['供应商 / 账户','可用余额','现金 / 充值余额','状态与来源','预警','查询时间'],rows.map(r=>[
      `<b>${esc(r.name)}</b><small class="pc-cell-note">${esc(r.tenant_name||'共享平台账户')}</small>`,
      r.state==='available'?r.balances.map(b=>money(b.available,b.currency)).join('<br>'):'未知',
      r.state==='available'?r.balances.map(b=>money(b.cash,b.currency)).join('<br>'):'未知',
      `${esc(labels[r.state]||'未知')}<small class="pc-cell-note">${esc(r.note||'')} · ${r.state==='available'?(r.cached?'最近查询结果':'供应商查询'):'未取得余额'}</small>`,
      `${r.warning==='low'?'<span class="pc-tag pc-tag-warning">余额不足预警</span>':r.warning==='normal'?'未触及预警阈值':'无法判断'}${r.balances.map(b=>b.warning_threshold!=null?`<small class="pc-cell-note">提醒阈值 ${money(b.warning_threshold,b.currency)}</small>`:'').join('')}`,
      esc(time(r.queried_at))
    ]))+
    (state.data?.next_after_id?`<button data-pc="balance-next" ${state.busy?'disabled':''}>查看下一批推广账户</button>`:'')+
    (state.cursors.length?`<button data-pc="balance-first" ${state.busy?'disabled':''}>返回首批账户</button>`:''),
    '阿里云余额覆盖同一云账户全部服务；DeepSeek 官方账户与百炼上的 DeepSeek 模型分开。余额查询不进行充值或修改预算。页面关闭后停止自动刷新，查询失败显示未知。');
}
