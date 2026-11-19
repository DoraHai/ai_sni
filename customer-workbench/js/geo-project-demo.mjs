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
const beijingDay = (at) => new Date(Date.parse(at) + 8 * 3600000).toISOString().slice(0, 10);
const sampleCounts = (samples) => {
  const mentioned = samples.filter((s) => s.mentioned === true).length;
  return {sample_count: samples.length, mentioned_count: mentioned,
    unknown_mention_count: samples.filter((s) => s.mentioned === null).length,
    mention_rate: samples.length ? 100 * mentioned / samples.length : null};
};

// Only consume the validated saved-sample projection. No formal cohort, vendor
// calls, inferred flags, missing-day filling or production-count constants.
export function demoOverview(value) {
  const d = demoProjection(value);
  if (!d || d.status !== 'available') return d;
  const group = (g) => {
    if (g.status !== 'available') return g;
    const samples = g.questions.flatMap((q) => q.by_engine.flatMap((c) => c.samples));
    const days = new Map();
    for (const s of samples) {
      const day = beijingDay(s.captured_at);
      if (!days.has(day)) days.set(day, []);
      days.get(day).push(s);
    }
    return {...sampleCounts(samples), status: 'available',
      daily: [...days].sort(([a], [b]) => a.localeCompare(b)).map(([date, rows]) => ({date, ...sampleCounts(rows)})),
      engines: demoEngines.map(([engine_key]) => ({engine_key,
        ...sampleCounts(g.questions.flatMap((q) => q.by_engine.find((c) => c.engine_key === engine_key).samples))}))};
  };
  return {...d, ordinary: group(d.ordinary), brand_probe: group(d.brand_probe)};
}

const rate = (c) => c.mention_rate === null ? '无样本' : `${c.mention_rate.toFixed(1)}%`;

// Independently configured example for the trend chart. Saved snapshot
// aggregations and detailed evidence continue to come from demoOverview.
const trendScenarioRates = [
  58.2, 58.8, 58.4, 59.3, 59.7, 60.5, 60.0, 59.8, 60.7, 61.1,
  61.6, 61.2, 62.0, 62.6, 62.3, 62.9, 63.4, 64.1, 63.6, 64.7,
  65.1, 65.7, 65.3, 66.1, 66.6, 67.2, 66.8, 67.8, 68.3, 68.7,
];

function demoCharts(g, selectedDay) {
  if (g.status !== 'available') return `<p role="status">普通问题统计不可用：${esc(reasons[g.reason_code])}。不生成趋势或引擎对比。</p>`;
  const days = trendScenarioRates.map((mention_rate, index) => ({
    date: new Date(Date.UTC(2026, 9, 20 + index)).toISOString().slice(0, 10),
    mention_rate,
  }));
  const selected = days.find((d) => d.date === selectedDay) || days.at(-1);
  const first = days[0], last = days.at(-1);
  const change = (last.mention_rate - first.mention_rate).toFixed(1);
  const ticks = [55, 60, 65, 70, 75];
  const x = (i) => 46 + i * 564 / (days.length - 1);
  const y = (value) => 146 - (value - ticks[0]) * 6;
  const describe = (d) => `${d.date}：${rate(d)}（方案）`;
  const trend = `<figure aria-label="普通问题每日提及率">
    <figcaption>每日提及率 <small>独立方案 · 首末日 +${change} 个百分点 · 北京时间</small><small>纵轴 55%–75%（局部视图）。汇总卡和模型对比使用已保存样本。</small></figcaption>
    <svg viewBox="0 0 640 174" role="img" aria-label="独立方案的每日提及率局部视图，纵轴 55%–75%，从 ${rate(first)} 升至 ${rate(last)}">
      <title>每日提及率，首末日相差 ${change} 个百分点</title>
      ${ticks.map((n) => `<line x1="46" x2="610" y1="${y(n)}" y2="${y(n)}" stroke="#dce5e3"/><text x="38" y="${y(n) + 4}" text-anchor="end">${n}%</text>`).join('')}
      <polyline points="${days.map((d, i) => `${x(i)},${y(d.mention_rate)}`).join(' ')}" fill="none" stroke="#16766b" stroke-width="2.5" stroke-linejoin="round"/>
      ${days.map((d, i) => `<circle cx="${x(i)}" cy="${y(d.mention_rate)}" r="${d === selected ? 5 : d === first || d === last ? 4 : 2.5}" fill="#16766b"><title>${esc(describe(d))}</title></circle>`).join('')}
      <text class="geo-demo-trend-endpoint" x="46" y="${y(first.mention_rate) - 10}">${rate(first)}</text>
      <text class="geo-demo-trend-endpoint" x="610" y="${y(last.mention_rate) - 10}" text-anchor="end">${rate(last)}</text>
      <text x="46" y="170">${first.date.slice(5)}</text><text x="610" y="170" text-anchor="end">${last.date.slice(5)}</text>
    </svg>
    <label class="geo-demo-day">查看日期 <select data-geo-demo-day aria-label="查看趋势日期">${days.map((d) => `<option value="${d.date}" ${d === selected ? 'selected' : ''}>${d.date}</option>`).join('')}</select></label>
    <p class="geo-demo-day-value" aria-live="polite">${esc(describe(selected))}</p>
  </figure>`;
  return `<div class="geo-demo-charts">${trend}<figure aria-label="普通问题每引擎提及率"><figcaption>模型接口类别对比 <small>普通问题 · 提及 / 已保存样本</small></figcaption><div class="geo-demo-engine-bars">${g.engines.map((c, i) => `<div data-demo-comparison="${c.engine_key}"><span>${demoEngines[i][1]}</span><span class="geo-demo-track" aria-hidden="true"><i style="width:${c.mention_rate}%"></i></span><strong>${rate(c)}</strong><small>${c.mentioned_count}/${c.sample_count} · 未判定 ${c.unknown_mention_count}</small></div>`).join('')}</div></figure></div>`;
}
const time = (s) => new Date(s).toLocaleString('zh-CN', {timeZone: 'Asia/Shanghai', hour12: false});
export function geoDemoArea(value, filter = {}, {expanded = false, selectedDay = null} = {}) {
  const d = demoProjection(value);
  if (d === null) return '';
  const title = '<h2>GEO 演示概览</h2>';
  if (d.status !== 'available') return `<section class="geo-demo" aria-label="独立演示区域">${title}<p role="status">演示批次不可用：${esc(reasons[d.reason_code] || '批次响应尚未提供或未通过校验')}。无替代数据。</p></section>`;
  const overview = demoOverview(value), ordinary = overview.ordinary, probe = overview.brand_probe;
  const ordinaryMetrics = ordinary.status === 'available'
    ? `<article><h3>普通问题 · 提及回答</h3><strong>${ordinary.mentioned_count}<small> / ${ordinary.sample_count}</small></strong><p>提及回答 / 已保存样本</p></article><article><h3>普通问题 · 提及率</h3><strong>${rate(ordinary)}</strong><p>排除题 85；未判定 ${ordinary.unknown_mention_count} 条仍计分母</p></article>`
    : `<article><h3>普通问题统计</h3><p>${esc(reasons[ordinary.reason_code])}</p></article>`;
  const coveredEngines = ordinary.status === 'available' ? ordinary.engines.filter((c) => c.mentioned_count > 0).length : null;
  const visibilityMetric = `<article><h3>AI 可见度概况（演示）</h3><strong>${coveredEngines === null ? '无数据' : `${coveredEngines} / ${demoEngines.length}`}</strong><p>至少一次提及的模型类别 / 全部模型类别；排除题 85。</p></article>`;
  const probeMetric = `<article class="geo-demo-probe"><h3>品牌点名题 85 · 独立统计</h3>${probe.status === 'available' ? `<strong>${rate(probe)}</strong><p>${probe.mentioned_count}/${probe.sample_count}；未判定 ${probe.unknown_mention_count} 条</p>` : `<p>${esc(reasons[probe.reason_code])}</p>`}<small>不参与普通问题概览、趋势与对比</small></article>`;
  const groups = [['ordinary', '普通问题（排除题 85）', d.ordinary], ['brand_probe', '品牌点名题（题 85，单独汇总）', d.brand_probe]];
  const query = String(filter.q || '').trim().toLocaleLowerCase();
  const tables = groups.filter(([kind]) => !filter.kind || filter.kind === kind).map(([, name, g]) => {
    if (g.status !== 'available') return `<h3>${name}</h3><p>${esc(reasons[g.reason_code])}</p>`;
    const questions = g.questions.filter((q) => !query || `${q.id} ${q.question}`.toLocaleLowerCase().includes(query));
    return `<div class="geo-question-scroll" role="region" aria-label="${name}八引擎演示表" tabindex="0"><table class="geo-question-table"><caption>${name} · 演示八引擎 · X/Y = 提及回答数/本批样本数</caption><thead><tr><th scope="col">问题</th>${demoEngines.map(([, name]) => `<th scope="col">${name}</th>`).join('')}</tr></thead><tbody>${questions.map((q) => `<tr><th scope="row">#${q.id} ${esc(q.question)}</th>${q.by_engine.map((c) => `<td data-demo-engine="${c.engine_key}"><strong>${counts(c)}</strong><details><summary>样本依据（${c.sample_count} 条）</summary><p>本批已保存快照；时间均为北京时间。</p><ul>${c.samples.map((s) => `<li>#${s.snapshot_id} · ${esc(time(s.captured_at))} · ${s.mentioned === null ? '提及未判定' : s.mentioned ? '标记为提及' : '标记为未提及'}</li>`).join('')}</ul></details></td>`).join('')}</tr>`).join('') || '<tr><td colspan="9">当前筛选无匹配问题。</td></tr>'}</tbody></table></div>`;
  }).join('');
  return `<section class="geo-demo" aria-label="独立演示区域">${title}<div class="geo-demo-meta"><p class="geo-demo-period">统计日期：${d.period.start_date} 至 ${d.period.end_date}（北京时间） · 已保存 ${d.saved_sample_count} 条样本</p></div><div class="geo-demo-stats">${ordinaryMetrics}${visibilityMetric}${probeMetric}</div>${demoCharts(ordinary, selectedDay)}<p class="geo-demo-method">每条已保存回答计一次，mentions_brand=true 计提及；未判定仍计分母。${value.data?.project?.canonical_domain ? '本视图仅展示样本统计，不计算正式可见度。' : '项目尚未配置自有域名；本视图只展示样本统计，不计算正式可见度。'}</p><p class="geo-demo-model-note">混元模型接口类别；不代表元宝产品端实际检测。其他（演示类别）不对应实际供应商检测。</p><details data-geo-demo-details ${expanded ? 'open' : ''}><summary data-geo="demo-details">问题与样本依据 · 展开查看八引擎网格、筛选与批次校验</summary><p>批次 <code>${demoToken}</code>；实际保存 <strong>${d.saved_sample_count}</strong> 条样本。统计日期独立于正式周筛选；上方“详细模式”保留工作台导航，同样使用本批数据。</p><form data-geo-demo><label>演示问题类型 <select name="kind"><option value="">全部</option><option value="ordinary" ${filter.kind === 'ordinary' ? 'selected' : ''}>普通问题</option><option value="brand_probe" ${filter.kind === 'brand_probe' ? 'selected' : ''}>品牌点名</option></select></label><label>演示问题文字或编号 <input name="q" maxlength="100" value="${esc(filter.q || '')}"></label><button>筛选演示问题</button></form><p>筛选只缩小下表；上方汇总始终为整个批次。</p>${tables}<details><summary>演示批次依据</summary><p>当前项目绑定 + note 独立批次 token；逐条核验 simulated=true、sample_mode=mock_persona、无巡检关联、已核对来源标记，题×引擎×北京时间日网格完整且无重复。单元格列出本批快照编号、保存时间与提及标记。</p><p>批次摘要：${esc(d.basis.fingerprint)}</p><p>演示不生成正式可见度分数或引用证据；本演示项目的两种页面模式均使用本批数据，其他客户的统计口径不变。</p></details></details></section>`;
}
