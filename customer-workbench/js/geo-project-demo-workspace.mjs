import {escapeText as esc} from './customer-display.mjs';
import {demoProjection, demoEngines, geoDemoArea} from './geo-project-demo.mjs';
import {geoQuestionFilters} from './geo-project-insights.mjs';

// Display the existing saved batch in the target customer's full workspace.
// This never changes API qualification, snapshot flags, or business records.
export function demoWorkspaceQuestions(value, questionData = {}, filters = {}, questionId = null) {
  const d = demoProjection(value);
  if (!d || d.status !== 'available') return geoDemoArea(value);
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
    return `<div class="geo-question-scroll" role="region" aria-label="${title}八模型模拟检测表" tabindex="0"><table class="geo-question-table"><caption>${title} · ${d.period.start_date} 至 ${d.period.end_date}（北京时间） · 提及回答数 / 模拟样本数</caption><thead><tr><th scope="col">业务</th><th scope="col">关键词</th><th scope="col">问题</th>${demoEngines.map(([, name]) => `<th scope="col">${name}</th>`).join('')}</tr></thead><tbody>${questions.map((q) => {
      const {unit, business} = metadata(q);
      return `<tr><td>${esc(business?.name || '暂无关联业务')}</td><td>${esc(unit?.display_name || unit?.keyword || unit?.name || '暂无关联关键词')}</td><th scope="row">${esc(q.question)}<small>#${q.id}${q.is_brand_probe ? ' · 品牌点名题' : ''}</small><button data-geo="read" data-resource="questions/${q.id}">查看问题</button></th>${q.by_engine.map((c) => `<td data-demo-engine="${c.engine_key}"><strong>${c.mentioned_count}/${c.sample_count} · ${c.sample_count ? c.mention_rate.toFixed(1) + '%' : '无数据'}</strong><details><summary>模拟样本依据（${c.sample_count} 条）</summary><p>${d.period.start_date} 至 ${d.period.end_date}（北京时间） · 未判定 ${c.unknown_mention_count} 条计入分母。</p><ul>${c.samples.map((s) => `<li>#${s.snapshot_id} · ${esc(new Date(s.captured_at).toLocaleString('zh-CN', {timeZone: 'Asia/Shanghai', hour12: false}))} · ${s.mentioned === null ? '提及未判定' : s.mentioned ? '模拟提及' : '模拟未提及'}</li>`).join('')}</ul></details></td>`).join('')}</tr>`;
    }).join('') || '<tr><td colspan="11">当前筛选无匹配的模拟问题。</td></tr>'}</tbody></table></div>`;
  }).join('');
  return `<section class="geo-demo geo-demo-work" aria-label="模拟问题与模型检测"><h2>${questionId ? '问题详情 · 模拟检测' : 'GEO 工作 · 模拟检测'}</h2><p class="geo-demo-warning"><strong>演示数据，不代表真实引擎检测或实际效果</strong></p><p>统计日期：${d.period.start_date} 至 ${d.period.end_date}（北京时间）；概览与本表均使用相同的八个模型类别和已保存批次。筛选仅缩小本表，概览为全批次。</p>${questionId ? '' : geoQuestionFilters(questionData, filters)}${tables}<p>混元模型接口类别，不代表元宝产品端实际检测。其他为演示类别。品牌点名题不计入普通问题概览。</p></section>`;
}
