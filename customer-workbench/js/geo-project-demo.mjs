import {escapeText as esc} from './customer-display.mjs';

export const demoToken = 'geo-demo-t15-p3-20261118-v1';
export const demoEngines = [
  ['deepseek', 'DeepSeek'], ['doubao', '豆包'], ['qwen', '千问'], ['hunyuan', '混元'],
  ['wenxin', '文心'], ['kimi', 'Kimi'], ['perplexity', 'Perplexity'], ['other', '其他（演示类别）'],
];
export const isDemoProject = (c) => c?.tenantId === 15 && c?.projectId === 3;
const integer = (n) => Number.isSafeInteger(n) && n >= 0;
const reasons = {
  batch_missing: '未找到已核演示批次', binding_changed: '当前项目归属与已核批次不一致',
  batch_invalid: '批次标记或样本属性不符合要求', batch_incomplete_or_duplicate: '批次缺格或存在重复',
  brand_probe_conflict: '品牌点名标记冲突，该部分停止展示', batch_over_budget: '批次超过读取预算',
};
const missing = () => ({status: 'unavailable', reason_code: 'response_invalid'});

// Validate the additive projection without changing any formal response fields.
export function demoProjection(value) {
  if (value?.tenant_id !== 15 || value?.project_id !== 3 || value?.read_only !== true) return null;
  const d = value.data?.demo_batch;
  if (!d || d.batch_token !== demoToken) return missing();
  if (d.status === 'unavailable') return d;
  if (d.status !== 'available' || d.source_kind !== 'simulated' || d.sample_mode !== 'mock_persona' ||
      d.period?.start_date !== '2026-10-20' || d.period?.end_date !== '2026-11-18' ||
      d.period?.timezone !== 'Asia/Shanghai' || !integer(d.saved_sample_count) ||
      JSON.stringify(d.engine_keys) !== JSON.stringify(demoEngines.map(([key]) => key)) ||
      d.basis?.kind !== 'saved_batch_records' || d.basis?.selection !== 'note_independent_token' ||
      d.basis?.ownership !== 'current_project_binding' || d.basis?.daily_grid_complete !== true ||
      d.basis?.simulated !== true || d.basis?.sample_mode !== 'mock_persona' || d.basis?.patrol_linked !== false)
    return missing();
  const seen = new Set();
  const validCounts = (c) => integer(c?.sample_count) && integer(c?.mentioned_count) &&
    integer(c?.unknown_mention_count) && c.mentioned_count + c.unknown_mention_count <= c.sample_count &&
    (c.sample_count ? Number.isFinite(c.mention_rate) &&
      Math.abs(c.mention_rate - 100 * c.mentioned_count / c.sample_count) < 0.00011 : c.mention_rate === null);
  for (const [name, ids] of [['ordinary', [83, 84, 86, 87, 88, 89]], ['brand_probe', [85]]]) {
    const g = d[name];
    if (g?.status === 'unavailable' && g.reason_code === 'brand_probe_conflict') continue;
    if (g?.status !== 'available' || !validCounts(g) || !Array.isArray(g.questions) ||
        JSON.stringify(g.questions.map((q) => q.id)) !== JSON.stringify(ids)) return missing();
    let total = 0, mentioned = 0, unknown = 0;
    for (const q of g.questions) {
      if (q.is_brand_probe !== (name === 'brand_probe') || typeof q.question !== 'string' ||
          !Array.isArray(q.by_engine) || JSON.stringify(q.by_engine.map((c) => c.engine_key)) !== JSON.stringify(d.engine_keys))
        return missing();
      for (const c of q.by_engine) {
        if (!validCounts(c) || !Array.isArray(c.samples) || c.samples.length !== c.sample_count) return missing();
        let x = 0, u = 0;
        const days = new Set();
        for (const s of c.samples) {
          const at = Date.parse(s.captured_at);
          if (!Number.isFinite(at) || !integer(s.snapshot_id) || s.snapshot_id === 0 || seen.has(s.snapshot_id) ||
              ![true, false, null].includes(s.mentioned)) return missing();
          const local = new Date(at + 8 * 3600000).toISOString().slice(0, 10);
          if (local < d.period.start_date || local > d.period.end_date || days.has(local)) return missing();
          days.add(local); seen.add(s.snapshot_id);
          x += s.mentioned === true ? 1 : 0; u += s.mentioned === null ? 1 : 0;
        }
        const expectedDays = (Date.parse(d.period.end_date) - Date.parse(d.period.start_date)) / 86400000 + 1;
        if (days.size !== expectedDays || x !== c.mentioned_count || u !== c.unknown_mention_count) return missing();
        total += c.sample_count; mentioned += x; unknown += u;
      }
    }
    if (total !== g.sample_count || mentioned !== g.mentioned_count || unknown !== g.unknown_mention_count) return missing();
  }
  if (d.ordinary.status === 'available' && d.brand_probe.status === 'available' &&
      d.ordinary.sample_count + d.brand_probe.sample_count !== d.saved_sample_count) return missing();
  return d;
}

const counts = (c) => `${c.mentioned_count}/${c.sample_count} · ${c.mention_rate.toFixed(1)}%`;
const time = (s) => new Date(s).toLocaleString('zh-CN', {timeZone: 'Asia/Shanghai', hour12: false});
export function geoDemoArea(value, filter = {}) {
  const d = demoProjection(value);
  if (d === null) return '';
  const title = '<h2>已核模拟演示批次 · 八引擎</h2><p class="geo-demo-warning" role="note"><strong>演示数据，不代表真实引擎检测或实际效果</strong></p>';
  if (d.status !== 'available') return `<section class="geo-demo" aria-label="独立模拟演示区域">${title}<p role="status">演示批次不可用：${esc(reasons[d.reason_code] || '批次响应尚未提供或未通过校验')}。无替代数据。</p></section>`;
  const summary = (name, g) => `<article><h3>${name}</h3>${g.status === 'available'
    ? `<strong>${counts(g)}</strong><p>提及回答数 / 本批模拟样本数；未判定 ${g.unknown_mention_count} 条。</p>`
    : `<p>${esc(reasons[g.reason_code])}</p>`}</article>`;
  const groups = [['ordinary', '普通问题（排除题 85）', d.ordinary], ['brand_probe', '品牌点名题（题 85，单独汇总）', d.brand_probe]];
  const query = String(filter.q || '').trim().toLocaleLowerCase();
  const tables = groups.filter(([kind]) => !filter.kind || filter.kind === kind).map(([, name, g]) => {
    if (g.status !== 'available') return `<h3>${name}</h3><p>${esc(reasons[g.reason_code])}</p>`;
    const questions = g.questions.filter((q) => !query || `${q.id} ${q.question}`.toLocaleLowerCase().includes(query));
    return `<div class="geo-question-scroll" role="region" aria-label="${name}八引擎演示表" tabindex="0"><table class="geo-question-table"><caption>${name} · 模拟演示八引擎 · X/Y = 提及回答数/本批模拟样本数</caption><thead><tr><th scope="col">问题</th>${demoEngines.map(([, name]) => `<th scope="col">${name}</th>`).join('')}</tr></thead><tbody>${questions.map((q) => `<tr><th scope="row">#${q.id} ${esc(q.question)}</th>${q.by_engine.map((c) => `<td data-demo-engine="${c.engine_key}"><strong>${counts(c)}</strong><details><summary>模拟样本依据（${c.sample_count} 条）</summary><p>本批已保存快照；时间均为北京时间。</p><ul>${c.samples.map((s) => `<li>#${s.snapshot_id} · ${esc(time(s.captured_at))} · ${s.mentioned === null ? '提及未判定' : s.mentioned ? '标记为提及' : '标记为未提及'}</li>`).join('')}</ul></details></td>`).join('')}</tr>`).join('') || '<tr><td colspan="9">当前筛选无匹配问题。</td></tr>'}</tbody></table></div>`;
  }).join('');
  return `<section class="geo-demo" aria-label="独立模拟演示区域">${title}<p>批次 <code>${demoToken}</code>；实际保存 <strong>${d.saved_sample_count}</strong> 条模拟样本。</p><p>统计日期：${d.period.start_date} 至 ${d.period.end_date}（北京时间）；此批次日期固定，独立于正式周筛选。</p><div class="geo-metrics">${summary('普通问题模拟提及率（排除题 85）', d.ordinary)}${summary('品牌点名模拟提及率（题 85）', d.brand_probe)}</div><p>仅按已保存记录 mentions_brand=true 计提及，每条回答计一次；未判定仍计入本批模拟样本分母。混元模型接口类别；不代表元宝产品端实际检测。其他（演示类别）不对应实际供应商检测。</p><form data-geo-demo><label>演示问题类型 <select name="kind"><option value="">全部</option><option value="ordinary" ${filter.kind === 'ordinary' ? 'selected' : ''}>普通问题</option><option value="brand_probe" ${filter.kind === 'brand_probe' ? 'selected' : ''}>品牌点名</option></select></label><label>演示问题文字或编号 <input name="q" maxlength="100" value="${esc(filter.q || '')}"></label><button>筛选演示问题</button></form><p>筛选只缩小下表；上方汇总始终为整个批次。</p>${tables}<details><summary>演示批次依据</summary><p>当前项目绑定 + note 独立批次 token；逐条核验 simulated=true、sample_mode=mock_persona、无巡检关联、note 含“模拟演示”，题×引擎×北京时间日网格完整且无重复。单元格列出本批快照编号、保存时间与提及标记。</p><p>批次摘要：${esc(d.basis.fingerprint)}</p><p>演示不生成正式可见度分数或引用证据；正式六引擎表与正式指标仍通过下方 GEO工作、数据入口独立展示。</p></details></section>`;
}
