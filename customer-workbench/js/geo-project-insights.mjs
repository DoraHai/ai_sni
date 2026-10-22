import {escapeText as esc} from './customer-display.mjs';
import {geoPeriod, geoOpenWeekProgress, geoQuestionOpenWeek} from './geo-project-display.mjs';

export const geoEngines = [
  ['doubao', '豆包'], ['deepseek', 'DeepSeek'], ['qwen', '千问'],
  ['hunyuan', '元宝'], ['wenxin', '文心'], ['kimi', 'Kimi'],
];
export const geoEngineName = (key) => geoEngines.find(([k]) => k === key)?.[1] || key || '未知引擎';
export const geoModelNote = '<p class="geo-footnote">模型 API 观测。元宝数据取自腾讯混元模型接口</p>';
const integer = (n) => Number.isSafeInteger(n) && n >= 0 ? String(n) : '暂无';
const number = (n) => typeof n === 'number' && Number.isFinite(n) ? n.toFixed(1).replace(/\.0$/, '') : '暂无';
const percent = (n) => typeof n === 'number' && Number.isFinite(n) && n >= 0 && n <= 100 ? number(n) + '%' : '暂无';
const states = {not_tested: '未检测', not_configured: '未配置', failed: '检测失败', tested_excluded: '已检测，未计入',
  no_publications: '暂无发布文章', insufficient_evidence: '引用证据不足'};
const state = (key) => states[key] || '暂无';
const read = (name, resource, params = {}) => `<button data-geo="read" data-resource="${esc(resource)}" data-params="${esc(JSON.stringify(params))}">${esc(name)}</button>`;
const notes = (rows) => (Array.isArray(rows) ? rows : []).map((text) => `<p class="geo-footnote">${esc(text)}</p>`).join('');
const excludedReasons = {
  engine_source_untrusted: '平台来源未核实', analysis_incomplete: '回答判读未完成',
  unsupported_sampling_method: '采样方式不符合正式口径', simulated_sample: '模拟样本',
  manual_sample: '人工登记样本', unknown_source: '来源未知', missing_server_evidence: '缺少巡检记录',
  snapshot_patrol_mismatch: '回答与巡检记录不一致', patrol_not_completed: '巡检未完成',
  capture_outside_patrol: '采样时间不在巡检内', brand_probe: '品牌点名题', citation_inaccurate: '引用不准确',
  unknown_capture_time: '采样时间未知', snapshot_unavailable: '回答记录不可读',
};
export const geoExcludedReason = (code) => Object.hasOwn(excludedReasons, code)
  ? excludedReasons[code] : '不符合正式统计条件';
export function geoMatrix(question, time) {
  return `${geoQuestionOpenWeek(question.open_week_detected_count)}<div class="geo-matrix" aria-label="六家模型提及率">${geoEngines.map(([key, name]) => {
    const cell = question.by_engine?.find((row) => row.engine_key === key);
    const valid = cell && ['observed', 'small_sample'].includes(cell.status) &&
      Number.isSafeInteger(cell.total) && cell.total > 0 && Number.isSafeInteger(cell.mentioned) &&
      cell.mentioned >= 0 && cell.mentioned <= cell.total;
    const reasons = cell?.status === 'tested_excluded'
      ? `<p class="geo-footnote">${esc((Array.isArray(cell.excluded_reason_codes) && cell.excluded_reason_codes.length
        ? cell.excluded_reason_codes : ['unknown']).map(geoExcludedReason).join('；'))}</p>` : '';
    return `<section><b>${name}</b><p>${valid ? `${cell.mentioned}/${cell.total} · ${percent(cell.percentage)}` : state(cell?.status)}</p>${reasons}<small>样本时间：${esc(cell?.last_sample_at ? time(cell.last_sample_at) : '暂无')}</small>${valid && (cell.small_sample || cell.total < 3) ? '<p class="geo-footnote">小样本，结果仅供参考</p>' : ''}${read('回答依据', 'answers', {question_id: question.id, engine_key: key})}</section>`;
  }).join('')}</div>${geoModelNote}`;
}
export function geoQuestionFilters(data, params = {}) {
  const filters = {...data.filters, ...params};
  const option = (row, selected, name) => `<option value="${esc(row.id)}" ${String(selected) === String(row.id) ? 'selected' : ''}>${esc(name)}</option>`;
  return `<form data-geo-questions><label>业务 <select name="business_id"><option value="">全部业务</option>${(data.options?.businesses || []).map((b) => option(b, filters.business_id, b.name)).join('')}</select></label><label>关键词 <select name="unit_id"><option value="">全部关键词</option>${(data.options?.units || []).map((u) => option(u, filters.unit_id, u.display_name || u.keyword || u.name)).join('')}</select></label><label>问题文字 <input name="q" maxlength="200" value="${esc(filters.q || '')}" placeholder="搜索全部问题"></label><button>筛选全部问题</button><button type="button" data-geo="clear-filters">清除筛选</button></form>`;
}
function cards(metrics, ready) {
  const m = metrics || {}, sample = integer(m.sample_count);
  return `<div class="geo-metrics geo-summary">${[
    ['品牌提及率', ready && m.sample_count > 0 ? percent(m.brand_mention_rate) : '暂无', `合格回答 ${sample} 条`],
    ['品牌提及回答数', ready && m.sample_count > 0 ? integer(m.brand_mention_answer_count) : '暂无', `合格回答 ${sample} 条；每条回答计一次`],
    ['平均推荐位置', ready && m.valid_position_count > 0 ? number(m.average_recommendation_position) : '暂无', `有效位置 ${integer(m.valid_position_count)} 条；首选=1、备选=2、顺带=3`],
    ['品牌正向评价率', ready && m.annotated_mention_count > 0 ? percent(m.brand_positive_rate) : '暂无', `已标注 ${integer(m.annotated_mention_count)} / 提及 ${integer(m.mention_count)} 条`],
  ].map(([name, value, basis]) => `<article><h3>${name}</h3><strong>${value}</strong><p>${basis}</p></article>`).join('')}</div><p>推荐位置分布：首选 ${integer(m.position_distribution?.first)} / 备选 ${integer(m.position_distribution?.alternative)} / 顺带 ${integer(m.position_distribution?.mentioned)}。</p>`;
}
export function geoInsightResource(resource, value, {time, link, basis}) {
  const d = value.data;
  if (resource === 'summary') {
    const ready = d.sample_status === 'ready';
    return `<h2>品牌表现汇总</h2>${geoOpenWeekProgress(d.open_week_progress)}<p>${esc(geoPeriod(d.period || value.basis?.period))}</p><p>同一项目、同一完整周的合格回答。${ready ? '' : '合格样本不足，四项指标暂无。'}样本 ${integer(d.qualified_counts.samples)} / 问题 ${integer(d.qualified_counts.questions)} / 引擎 ${integer(d.qualified_counts.engines)}；最低要求 ${integer(d.minimum_counts.samples)} 条回答、${integer(d.minimum_counts.questions)} 题、${integer(d.minimum_counts.engines)} 个引擎。</p>${cards(d.metrics, ready)}<details><summary>分平台汇总与样本</summary>${geoEngines.map(([key, name]) => `<h3>${name}</h3>${cards(d.by_engine.find((e) => e.engine_key === key)?.metrics, ready)}`).join('')}</details>${geoModelNote}${notes(d.footnotes)}${basis(value)}`;
  }
  if (resource === 'article-citations') {
    const c = d.coverage;
    return `<h2>已发布文章引用</h2><p>已保存回答中可解析 URL 的引用观测。</p><p>被引文章 H/U：${c.status === 'observed' ? `${integer(c.cited_articles)}/${integer(c.published_articles)} · ${c.published_articles > 0 ? percent(c.percentage) : '暂无'}` : `${state(c.status)}；已发布文章 ${integer(c.published_articles)} 篇`}</p>${d.items.map((row) => `<article class="geo-row"><h3>${esc(row.title)}</h3><p>${link(row.url, '查看已发布文章')}；发布时间 ${esc(time(row.published_at))}</p><p>本篇被引回答 x/y：${row.status === 'observed' && row.total > 0 ? `${integer(row.mentioned)}/${integer(row.total)} · ${percent(row.percentage)}` : state(row.status)}</p>${read('查看稿件', 'content/' + row.task_id)}<ul>${row.evidence.map((e) => `<li>${esc(geoEngineName(e.engine_key))} · ${esc(time(e.captured_at))} ${read('依据回答', 'answers/' + e.answer_id)}</li>`).join('') || '<li>暂无引用依据回答</li>'}</ul></article>`).join('') || '<p>暂无文章引用数据。</p>'}${geoModelNote}${notes(d.footnotes)}${pagination(d)}${basis(value)}`;
  }
  if (resource === 'recommendations')
    return `<h2>站内 GEO 建议</h2><p>来自当前项目已有站内任务。结构扫描归属尚未核实，暂无结构扫描报告。</p>${d.items.map((row) => `<article class="geo-row"><h3>${esc(row.title)}</h3><p>检查时间：${esc(row.checked_at ? time(row.checked_at) : '暂无')}；完成情况：${esc(completion(row.status || row.phase))}</p>${row.recommendations.map((r) => `<section><h4>${esc(r.title)}</h4><p>建议与依据：${esc(r.description || '暂无依据说明')}</p><p>优先级：${esc(priority(r.priority))}；完成情况：${esc(completion(r.status))}</p></section>`).join('') || '<p>暂无已保存建议。</p>'}<p>下一步：${esc(row.next_action || '暂无')}</p></article>`).join('') || '<p>暂无站内 GEO 建议。</p>'}${pagination(d)}${basis(value)}`;
  return null;
}
const completion = (s) => ({done: '已完成', completed: '已完成', doing: '进行中', in_progress: '进行中', open: '待处理', pending: '待处理', paused: '暂停', cancelled: '已取消'})[s] || '暂无完成记录';
const priority = (s) => ({high: '高', medium: '中', low: '低', P0: 'P0', P1: 'P1', P2: 'P2'})[s] || s || '暂无';
function pagination(d) {
  return `<p>当前已加载 ${d.items.length} 条 / 本次查询范围共 ${integer(d.pagination.total_count)} 条。</p>${d.pagination.has_more ? '<p>仅展示已加载部分，继续加载。</p><button data-geo="more">继续加载</button>' : ''}`;
}
