import {escapeText as esc} from './customer-display.mjs';
import {demoProjection, demoOverview, demoEngines} from './geo-project-demo.mjs';
import {geoQuestionFilters} from './geo-project-insights.mjs';

export function demoWorkspaceMetrics(value) {
  const batch = demoOverview(value);
  if (batch?.status !== 'available') return '<p role="status">当前没有可展示的样本。</p>';

  const {ordinary, brand_probe: probe, period} = batch;
  const ordinaryAvailable = ordinary.status === 'available';
  const coverage = ordinaryAvailable ? ordinary.engines.filter((engine) => engine.mentioned_count > 0).length : null;
  const metrics = ordinaryAvailable ? [
    ['AI 提及回答数', ordinary.mentioned_count, `普通问题共 ${ordinary.sample_count} 条样本`],
    ['AI 提及率', ordinary.mention_rate.toFixed(1) + '%', '普通问题排除品牌点名题 85'],
    ['AI 可见度概况', `${coverage} / ${batch.engine_keys.length}`, '出现提及的模型类别数'],
  ] : [];
  const cards = metrics.map(([title, result, description]) =>
    `<article><h3>${title}</h3><strong>${result}</strong><p>${description}</p></article>`).join('');
  const probeLine = probe.status === 'available'
    ? `<p>品牌点名题 85 单独统计：${probe.mentioned_count} / ${probe.sample_count}（${probe.mention_rate.toFixed(1)}%）。</p>`
    : '<p>品牌点名题 85 暂无可展示的样本。</p>';

  return `<p>统计日期：${period.start_date} 至 ${period.end_date}（北京时间）。共 ${batch.saved_sample_count} 条样本。</p>` +
    (cards ? `<div class="geo-metrics">${cards}</div>` : '<p>普通问题暂无可展示的样本。</p>') +
    probeLine;
}

// Display the existing saved batch in the target customer's full workspace.
// This never changes API qualification, snapshot flags, or business records.
export function demoWorkspaceQuestions(value, questionData = {}, filters = {}, questionId = null) {
  const d = demoProjection(value);
  if (!d || d.status !== 'available') return demoWorkspaceMetrics(value);
  const units = questionData.options?.units || [];
  const businesses = questionData.options?.businesses || [];
  const query = String(filters.q || '').trim().toLocaleLowerCase();
  const metadata = (q) => {
    const row = questionData.items?.find((item) => item.id === q.id);
    const unit = units.find((u) => u.id === q.unit_id) || row?.unit;
    const business = businesses.find((b) => b.id === unit?.business_id) || row?.business;
    return {unit, business};
  };
  const groups = [['ordinary', '普通问题（排除题 85）'], ['brand_probe', '品牌点名题 85（单独统计）']];
  const tables = groups.map(([key, title]) => {
    const group = d[key];
    if (group.status !== 'available') return `<p>${title}：当前批次不可用。</p>`;
    const questions = group.questions.filter((q) => {
      const {unit, business} = metadata(q);
      return (!questionId || q.id === questionId) &&
        (!filters.unit_id || String(unit?.id) === String(filters.unit_id)) &&
        (!filters.business_id || String(business?.id) === String(filters.business_id)) &&
        (!query || `${q.id} ${q.question}`.toLocaleLowerCase().includes(query));
    });
    return `<div class="geo-question-scroll" role="region" aria-label="${title}八模型样本统计表" tabindex="0"><table class="geo-question-table"><caption>${title} · ${d.period.start_date} 至 ${d.period.end_date}（北京时间） · 提及回答数 / 样本数</caption><thead><tr><th scope="col">业务</th><th scope="col">关键词</th><th scope="col">问题</th>${demoEngines.map(([key, name]) => `<th scope="col">${key === 'other' ? '其他' : name}</th>`).join('')}</tr></thead><tbody>${questions.map((q) => {
      const {unit, business} = metadata(q);
      return `<tr><td>${esc(business?.name || '暂无关联业务')}</td><td>${esc(unit?.display_name || unit?.keyword || unit?.name || '暂无关联关键词')}</td><th scope="row">${esc(q.question)}<small>#${q.id}${q.is_brand_probe ? ' · 品牌点名题' : ''}</small><button data-geo="read" data-resource="questions/${q.id}">查看问题</button></th>${q.by_engine.map((c) => `<td data-demo-engine="${c.engine_key}"><strong>${c.mentioned_count}/${c.sample_count} · ${c.sample_count ? c.mention_rate.toFixed(1) + '%' : '无数据'}</strong><details><summary>样本依据（${c.sample_count} 条）</summary><p>${d.period.start_date} 至 ${d.period.end_date}（北京时间） · 未判定 ${c.unknown_mention_count} 条计入分母。</p><ul>${c.samples.map((s) => `<li>#${s.snapshot_id} · ${esc(new Date(s.captured_at).toLocaleString('zh-CN', {timeZone: 'Asia/Shanghai', hour12: false}))} · ${s.mentioned === null ? '提及未判定' : s.mentioned ? '提及' : '未提及'}</li>`).join('')}</ul></details></td>`).join('')}</tr>`;
    }).join('') || '<tr><td colspan="11">当前筛选无匹配的问题。</td></tr>'}</tbody></table></div>`;
  }).join('');
  return `<section class="geo-demo-work" aria-label="问题与模型统计"><h2>${questionId ? '问题详情 · 样本统计' : '项目问题'}</h2><p>统计日期：${d.period.start_date} 至 ${d.period.end_date}（北京时间）；概览与本表均使用相同的八个模型类别和已保存批次。筛选仅缩小本表，概览为全批次。</p>${questionId ? '' : geoQuestionFilters(questionData, filters)}${tables}<p>混元模型接口类别，不代表元宝产品端实际检测。「其他」为汇总类别。品牌点名题不计入普通问题概览。</p></section>`;
}
