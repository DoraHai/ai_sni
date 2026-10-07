import {escapeText as esc, formatMetric, formatTime, statusLabel} from './customer-display.mjs';

// Presentation only: callers must fetch an authorized tenant/site scope and handle HTTP failures.
const positiveId = value => Number.isSafeInteger(value) && value > 0;
const number = value => typeof value === 'number' && Number.isFinite(value);
const rank = value => number(value) && value > 0 ? `${esc(formatMetric(value))} 名` : '未返回名次';
const detail = (action, id) => positiveId(id) ? `<button data-action="${action}" data-id="${id}">查看详情</button>` : '<span>详情暂不可用</span>';
const time = value => esc(formatTime(value));
const text = (value, fallback) => esc(value == null || value === '' ? fallback : value);

export function dataLink(value, label = '打开页面') {
  try {
    const url = new URL(value);
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) throw new Error('unsupported');
    return `<a href="${esc(url.href)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>`;
  } catch { return '<span>暂无可打开的地址</span>'; }
}

function table(payload, title, headers, renderRow, empty, note) {
  if (payload == null) return `<section class="data-list"><h3>${title}</h3><p>尚未读取。</p></section>`;
  if (!Array.isArray(payload.items) || payload.items.some(v => !v || typeof v !== 'object' || Array.isArray(v))) {
    return `<section class="data-list"><h3>${title}</h3><p role="alert">读取结果不完整，请重新读取。暂不显示为空列表。</p></section>`;
  }
  const count = payload.items.length;
  const total = Number.isSafeInteger(payload.total) && payload.total >= 0 ? formatMetric(payload.total) : '未提供';
  const page = positiveId(payload.page) ? `第 ${payload.page} 页 · ` : '';
  return `<section class="data-list"><h3>${title}</h3><p class="data-scope">${page}本页 ${count} 条 · 当前筛选共 ${esc(total)} 条</p>${count ? `<div class="data-table-scroll" tabindex="0" aria-label="${title}明细"><table><thead><tr>${headers.map(h => `<th scope="col">${h}</th>`).join('')}</tr></thead><tbody>${payload.items.map(renderRow).join('')}</tbody></table></div>` : `<p>${empty}</p>`}<p class="meaning-note">${note}</p></section>`;
}

export function rankingListView(payload) {
  const names = {baidu:'百度', google:'Google', bing:'必应', '360':'360搜索', sogou:'搜狗'};
  const engine = payload && Object.hasOwn(names, payload.engine) ? names[payload.engine] : '当前搜索引擎';
  return table(payload, `${engine}关键词排名`, ['关键词', '当前排名', '相比上次', '数据时间', '操作'], row => {
    const stale = row.rank_is_stale === true;
    const current = stale ? '需要更新' : rank(row.latest_rank);
    const historical = stale && number(row.last_observed_rank) && row.last_observed_rank > 0 ? `<small>上次记录：${rank(row.last_observed_rank)}</small>` : '';
    const delta = !stale && number(row.latest_rank) && row.latest_rank > 0 && number(row.rank_delta) ? row.rank_delta === 0 ? '持平' : `${row.rank_delta > 0 ? '上升' : '下降'} ${esc(formatMetric(Math.abs(row.rank_delta)))} 名` : '—';
    return `<tr><th scope="row">${text(row.keyword, '未命名关键词')}<small>${text(row.cluster, '未分组')}</small></th><td>${current}${historical}</td><td>${delta}</td><td>${time(row.rank_checked_at)}</td><td>${detail('data-keyword-detail',row.id)}</td></tr>`;
  }, '当前筛选下没有关键词记录。', '排名按所选引擎和设备读取；过期记录仅作历史参考。未返回名次不等于第 0 名，也不代表搜索点击。');
}

export function pageListView(payload) {
  const states={pending:'尚未检查',healthy:'检查正常',needs_fix:'需要修改',proposed:'修改建议已备好',approved:'修改建议已确认',implemented:'已修改，待复查',verified:'已复查',failed:'检查失败'};
  return table(payload, '网站页面检查', ['页面', '检查结果', '允许索引', '检查时间', '操作'], row => {
    const state = row.last_error ? '检查未成功' : Object.hasOwn(states,row.status) ? states[row.status] : '状态待核对';
    const index = row.indexable === true ? '允许' : row.indexable === false ? '不允许' : '未确认';
    const score = row.audit_score == null ? '' : `<small>检查评分 ${esc(formatMetric(row.audit_score))}</small>`;
    return `<tr><th scope="row">${text(row.title,'未命名页面')}<small>${dataLink(row.url)}</small></th><td>${state}${score}</td><td>${index}</td><td>${time(row.last_checked_at)}</td><td>${detail('data-page-detail',row.id)}</td></tr>`;
  }, '当前筛选下没有页面记录。', '允许索引只表示页面具备一项收录条件，不表示搜索引擎已经收录。检查结果不等于真人访问量。');
}

export function publicationListView(payload) {
  const associations={publication_url_missing:'尚未登记发布地址',no_match:'尚未关联站内页面',page_inventory_incomplete:'页面关联范围不完整',multiple_matches:'有多个候选页面，待顾问核对',exact_unique:'已关联页面'};
  const coverage={not_applicable:'暂无页面检查依据',no_data:'尚无页面检查记录',stale:'检查早于发布，待复查',failed:'页面检查失败',available:'已有页面检查记录'};
  const note = `发布记录与页面检查分别展示；有检查记录不等于全部检查通过，更不代表搜索效果提升。${payload?.coverage?.partial === true ? '本次页面关联范围不完整，请顾问核对。' : ''}`;
  return table(payload, '发布与交付记录', ['稿件 / 平台', '发布情况', '页面检查', '发布时间', '操作'], row => {
    const publication=row.publication??{},content=row.content??{},check=row.page_check??{},association=row.page_association??{};
    const associationText=Object.hasOwn(associations,association.association_status)?associations[association.association_status]:'关联状态待核对';
    const checkText=Object.hasOwn(coverage,check.coverage)?coverage[check.coverage]:'页面检查状态待核对';
    return `<tr><th scope="row">${text(content.title,'未命名稿件')}<small>${text(publication.platform_name||publication.platform_code,'平台未提供')}</small></th><td>${esc(statusLabel(publication.status,'publication'))}<small>${dataLink(publication.public_url,'查看发布页面')}</small></td><td>${checkText}<small>${associationText}</small><small>${check.fetched_at?time(check.fetched_at):'检查时间未提供'}</small></td><td>${time(publication.published_at)}</td><td>${detail('data-publication-detail',publication.id)}</td></tr>`;
  }, '当前范围尚无发布记录。', note);
}
