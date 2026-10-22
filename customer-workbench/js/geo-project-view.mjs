import {geoMatrix, geoQuestionFilters, geoInsightResource, geoEngineName, geoModelNote} from './geo-project-insights.mjs';
import {escapeText as esc} from './customer-display.mjs';
export const geoTabs = [
  ['home', '首页'],
  ['content', '内容'],
  ['work', 'GEO工作'],
  ['progress', '进度'],
  ['onsite', '站内优化'],
  ['data', '数据'],
  ['plan', '服务计划'],
  ['deliveries', '交付记录'],
];
const labels = {
  active: '启用',
  inactive: '暂停',
  archived: '已归档',
  unknown: '状态未知',
  none: '尚未提交客户确认',
  pending: '待客户确认',
  approved: '已确认，发布状态请查看交付记录',
  rejected: '客户要求修改',
  draft: '草稿',
  facts_bound: '已关联事实',
  needs_fix: '待修改',
  adapting: '渠道适配中',
  exported: '已导出',
  published: '已登记发布',
  failed: '失败',
  ready: '已备好',
  editing: '编辑中',
  generating: '制作中',
  cancelled: '已取消',
  open: '待处理',
  doing: '进行中',
  in_progress: '进行中',
  done: '已完成',
  paused: '暂停',
  healthy: '已有健康状态记录',
  unverified: '尚未核验',
  unhealthy: '页面需核对',
  real: '真实',
  manual: '人工',
  simulated: '模拟',
  completed: '判读完成',
  needs_review: '待判读',
  sending: '投递处理中',
  succeeded: '已有投递成功回执，发布登记与页面核验请分别查看',
  included: '计入正式指标',
  excluded: '未计入正式指标',
  unavailable: '正式指标暂不可用',
};
const reasons = {
  insufficient_samples: '合格回答少于 8 条',
  insufficient_questions: '覆盖问题少于 3 个',
  insufficient_engines: '覆盖引擎少于 2 个',
  missing_own_domain: '缺少本项目认可的自有域',
  simulated_sample: '模拟样本',
  manual_sample: '人工样本',
  unknown_source: '来源未知',
  unsupported_sampling_method: '采样方法不符合正式口径',
  analysis_incomplete: '判读未完成',
  citation_inaccurate: '引用不准确',
  brand_probe: '品牌点名问题',
  missing_server_evidence: '缺少服务端证据',
  patrol_not_completed: '巡检尚未完成',
  capture_outside_patrol: '采样超出巡检时间',
  snapshot_patrol_mismatch: '回答与巡检证据不匹配',
  outside_selected_week: '不在所选完整周内',
  unknown_capture_time: '采样时间未知',
  current_week_insufficient: '本期检测数据还不够',
  previous_week_insufficient: '上期检测数据还不够',
  cohort_changed: '问题或引擎范围变化',
  question_changed: '历史提问变化',
  model_metadata_missing: '缺少历史模型信息',
  model_distribution_changed: '模型分布变化',
  sample_distribution_changed: '样本分布变化',
  no_real_observations: '尚无可判读的真实观测',
  not_mentioned_in_some_observations: '部分真实观测未提及',
  monitor_not_healthy: '页面状态需核对',
  fingerprint_missing_or_mismatch: '正文匹配证据不足',
  article_version_mismatch: '母稿版本不匹配',
  checked_at_missing_or_invalid: '缺少有效核验时间',
  historical_article: '历史母稿版本',
  article_reference_invalid: '关联母稿不可用',
  unrecognized_receipt_state: '投递状态未知',
  timeout: '投递超时',
  authorization_failed: '投递授权失败',
  quota_exceeded: '投递额度不足',
  execution_failed: '投递未完成',
};
export const geoReason = (c) => reasons[c] || '其他未计入或待核对原因';
const reasonText = (rows) => (rows || []).map(geoReason).join('；') || '无';
const label = (value) => labels[value] || '状态未知';
const count = (n) => (Number.isSafeInteger(n) && n >= 0 ? String(n) : '未知');
const channel = (c) =>
  ({
    website: '官网',
    docs: '文档',
    zhihu: '知乎',
    baijiahao: '百家号',
    toutiao: '头条',
    sohu: '搜狐',
    wechat: '微信公众号',
  })[c] || '其他渠道';
export function geoTime(value) {
  if (!value || !Number.isFinite(Date.parse(value))) return '未知';
  return (
    new Intl.DateTimeFormat('zh-CN', {
      timeZone: 'Asia/Shanghai',
      dateStyle: 'medium',
      timeStyle: 'short',
      hour12: false,
    }).format(new Date(value)) + '（上海时间）'
  );
}
const sensitiveQuery = /(?:^|[^a-z0-9])(?:token|access_token|accesstoken|key|apikey|api_key|secret|password|passwd|pwd|sig|signature|auth|authorization|session|sessionid|session_id|code|credential|credentials|jwt)(?:$|[^a-z0-9])/i;
const trackingQuery = new Set(['gclid', 'dclid', 'fbclid', 'msclkid', 'spm', 'yclid', '_ga', '_gl']);
const publicDomain = (value) => {
  if (typeof value !== 'string') return '';
  const h = value.toLowerCase().replace(/\.+$/, '');
  if (h.length > 253 || !h.includes('.') || /^(?:[0-9]+|0x[0-9a-f]+)$/.test(h.split('.').at(-1)) ||
      /(?:^|\.)(?:localhost|local|internal|test|invalid|lan|home|localdomain|intranet|corp|private|onion)$/.test(h)) return '';
  return h.split('.').every((label) => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label)) ? h : '';
};
const domainOnly = (value, title) => esc(publicDomain(value) || title) + '（链接未开放）';
export function geoSafeLink(value, title = '查看公开链接') {
  try {
    if (typeof value !== 'string' || !/^https?:\/\//i.test(value) || /[\x00-\x20\x7f\\]/.test(value)) return domainOnly('', title);
    const authority = value.match(/^https?:\/\/([^/?#]+)/i)?.[1];
    if (!authority || authority.includes('%')) return domainOnly('', title);
    const u = new URL(value);
    const h = publicDomain(u.hostname);
    if (!['http:', 'https:'].includes(u.protocol)) return domainOnly('', title);
    if (u.username || u.password || authority.includes('@') || !h || (u.port && !['80', '443'].includes(u.port)) ||
        [...u.searchParams.keys()].some((key) => sensitiveQuery.test(key))) return domainOnly(h, title);
    for (const key of [...u.searchParams.keys()])
      if (key.toLowerCase().startsWith('utm_') || trackingQuery.has(key.toLowerCase())) u.searchParams.delete(key);
    u.hostname = h;
    u.hash = '';
    return `<a href="${esc(u.href)}" target="_blank" rel="noopener noreferrer">${esc(title)}</a>`;
  } catch {
    return domainOnly('', title);
  }
}
const button = (text, resource, params = {}) =>
  `<button data-geo="read" data-resource="${esc(resource)}" data-params="${esc(JSON.stringify(params))}">${esc(text)}</button>`;
export const geoStatus = (slot) =>
  slot?.loading
    ? '正在读取…'
    : {
        GEO_NOT_OPEN: '暂无数据（接口暂未开放）',
        GEO_SCOPE_CHANGED: '项目范围已变化，请重新读取。',
        GEO_CURSOR_INVALID: '分页已失效，请重新读取。',
        GEO_INVALID_WEEK: '请选择上海时区已结束完整周的周一。',
        GEO_RESPONSE_INVALID: '数据范围或格式无法核验，请重新读取。',
        GEO_READ_UNAVAILABLE: '数据量较大或读取暂不可用，请稍后再试。',
        GEO_ACTION_INVALID: '操作参数无法读取，请重新读取页面后再试。',
      }[slot?.error] || '暂无数据，读取失败，请重新读取。';
export function geoBasis(value) {
  if (!value?.basis) return '';
  const {basis: b, scope: s} = value,
    p = b.period,
    c = b.source_counts;
  return `<details class="geo-basis"><summary>数据范围与依据</summary><p>客户 ${esc(value.tenant_id)} / 项目 ${esc(value.project_id)}；按当前项目归属读取历史。${s.binding_state === 'unbound' ? '当前项目尚未关联业务。' : ''}当前归属问题 ${count(s.question_count)} 个。</p><p>${p ? `上海时区已结束完整周：${esc(p.start)} 至 ${esc(p.end)}（右端不含）` : '当前归属下已保存的内容与交付历史，不按周筛除'}</p><p>查询时间：${esc(geoTime(value.evaluated_at))}；数据时间：${esc(geoTime(b.last_data_at))}。</p>${c ? `<p>保存来源：真实 ${count(c.real)} / 人工 ${count(c.manual)} / 模拟 ${count(c.simulated)} / 未知 ${count(c.unknown)}。时间未知 ${count(b.unknown_time_count)} 条（${b.unknown_time_scope === 'single_answer' ? '本条回答' : '当前项目历史，随问题/引擎/来源筛选缩小'}，不计周分母）。</p>` : ''}<p>摘要${b.aggregation_complete === true ? '按完整查询范围统计' : '完整性尚未确认'}；已加载列表不代表完整总体。</p><p>未计入原因（同条可多原因，不能相加）：${esc((b.exclusion_counts || []).map((r) => geoReason(r.code) + ' ' + count(r.count)).join('；') || '无')}</p></details>`;
}
export function geoObservation(o) {
  return o?.status === 'observed'
    ? `观测中提及 ${count(o.mentioned)}/${count(o.total)} 次`
    : '尚无可判读的真实观测';
}
const metricNames = {
  'geo.visibility.ai_mention_count_7d': 'AI 提及回答数',
  'geo.visibility.ai_mention_rate_7d': 'AI 提及率',
  'geo.visibility.ai_visibility_score': 'AI 可见度概况',
};
export function geoWeekly(w, comparable = true) {
  if (!w) return '<p>检测数据还不够</p>';
  return `<p>AI 指标：上海时区已结束完整周；${esc(w.period?.start)} 至 ${esc(w.period?.end)}（右端不含）。</p>${w.sample_status === 'insufficient' ? '<p>检测数据还不够</p>' : ''}<div class="geo-metrics">${Object.entries(
    metricNames,
  )
    .map(([key, name]) => {
      const m = w.metrics?.find((row) => row.key === key),
        available = m?.status === 'available' && Number.isFinite(m.value);
      return `<article><h3>${name}</h3><strong>${available ? esc(m.value) + (m.unit === 'percent' ? '%' : '') : m?.status === 'insufficient' ? '检测数据还不够' : '暂不可用'}</strong><p>${esc(reasonText(m?.reason_codes))}</p>${available && comparable && m.trend_7d ? `<p>较上周${{up: '增加', down: '减少', flat: '持平'}[m.trend_7d.direction] || '变化'} ${esc(m.trend_7d.change_abs)}${m.unit === 'percent' ? ' 个百分点' : ''}</p>` : ''}</article>`;
    })
    .join(
      '',
    )}</div><p>合格覆盖：${count(w.qualified_counts?.samples)} 条回答 / ${count(w.qualified_counts?.questions)} 个问题 / ${count(w.qualified_counts?.engines)} 个引擎；最低要求 8 / 3 / 2。可见度分数不表示排名、流量或成交。</p>`;
}
export function geoServiceLine(ex) {
  if (!ex) return '项目服务进度读取失败';
  if (ex.effective_pause === true) return '项目服务当前暂停';
  if (ex.service_plan?.enabled !== true) return '服务计划尚未启用';
  return `最近已加载 ${ex.items.length} 项服务任务，已加载任务中 ${ex.items.filter((r) => r.status === 'done').length} 项完成${ex.truncated ? '（仅最近20项）' : ''}`;
}
export function geoHome(slots) {
  const a = slots.overview?.value,
    v = a?.data,
    x = slots.executions?.value,
    b = slots.visibility?.value;
  const weeklyCard = b
    ? geoWeekly(b.data.current, b.data.comparison?.comparable === true) + geoBasis(b)
    : v?.weekly
      ? geoWeekly(v.weekly)
      : '<p>AI 指标：' + geoStatus(slots.visibility) + '</p>';
  const pending = v
    ? `当前待确认：${v.content.pending_review_count > 0 ? '有 ' + count(v.content.pending_review_count) + ' 项稿件待客户确认' : '当前无待确认稿件'}`
    : '待确认稿件' + (slots.overview?.error === 'GEO_NOT_OPEN' ? '暂未开放' : '读取失败');
  const monitor = v
    ? `${v.weekly?.period?.start || ''} 至 ${v.weekly?.period?.end || ''}：${v.monitoring.active_nonbrand_question_count === 0 ? '当前项目尚无归属监测问题' : v.monitoring.attention_question_count > 0 ? '本周正式统计窗口内有 ' + count(v.monitoring.attention_question_count) + ' 个问题建议查看观测证据' : '该周无上述规则命中的关注问题'}${v.weekly?.sample_status === 'insufficient' ? '；检测数据还不够' : ''}`
    : '监测关注项' + (slots.overview?.error === 'GEO_NOT_OPEN' ? '暂未开放' : '读取失败');
  return `<h2>本期要点</h2><ul class="geo-highlights"><li>${esc(pending)} ${button('查看', 'content', {review_status: 'pending'})} ${button('问这项工作', 'content', {review_status: 'pending'})}</li><li>${esc(x ? geoServiceLine(x) : geoStatus(slots.executions))} <button data-geo="tab" data-tab="progress">查看</button> <button data-geo="tab" data-tab="plan">问这项工作</button></li><li>${esc(monitor)} ${button('查看', 'questions', {attention: 'needs_attention'})} ${button('问这项工作', 'questions', {attention: 'needs_attention'})}</li></ul><p>“问这项工作”定位到已保存证据与说明。客户确认后仍需安排发布。</p><h2>GEO 优化概览</h2>${v ? `${a.scope.binding_state === 'unbound' ? '<p>当前项目尚未关联业务</p>' : ''}<p>当前内容库存：${count(v.content.active_task_count)} 项任务，${count(v.content.task_count_with_master)} 项已有母稿，${count(v.content.variant_count)} 份渠道稿，${count(v.content.native_published_record_count)} 条原生发布登记。</p>` : `<p>${geoStatus(slots.overview)}</p>`}${geoBasis(a)}${weeklyCard}${slots.visibility?.error ? `<p role="status">AI 指标：${geoStatus(slots.visibility)}</p>` : ''}${button('查看 AI 数据', 'visibility')}<p>站内任务：月度计划，与 AI 正式周指标周期不同。</p>`;
}
export function geoExecutions(value, plan = false) {
  if (plan) {
    const s = value.service_plan;
    return `<h2>服务计划</h2><p>${esc(geoServiceLine(value))}</p><p>计划${s?.enabled === true ? '已启用' : '尚未启用'}；保存状态：${esc(label(s?.status))}；间隔：${count(s?.interval_days)} 天。此处只读现有计划，不代表承诺每日自动检测。</p>${value.blocker ? '<p>项目有待处理事项</p>' : ''}`;
  }
  return `<h2>项目进度</h2><p>${esc(geoServiceLine(value))}</p><p>最近已加载 ${value.items.length} 项${value.truncated ? '；仅最近 20 项，非完整项目总量' : ''}。</p>${value.items.map((item) => `<article class="geo-row"><h3>${esc(item.title)}</h3><p>${esc(label(item.status))}</p>${Array.isArray(item.execution?.steps) ? `<ul>${item.execution.steps.map((s) => `<li>${esc(s.title)}：${s.done === true ? '已完成' : '待处理'}</li>`).join('')}</ul>` : ''}${item.execution?.next_step ? '<p>下一步：请查看任务说明并核对现有证据。</p>' : ''}${item.execution?.truncated ? '<p>单项证据仅为已加载预览，不能作为正式指标。</p>' : ''}</article>`).join('') || '<p>暂无已保存服务任务。</p>'}<h3>项目问题预览</h3>${value.prompts_truncated ? '<p>仅最多 200 个问题，更多问题未加载。</p>' : ''}<ul>${value.prompts.map((p) => `<li>${esc(p.question)} ${button('观测证据', 'questions/' + p.id)}</li>`).join('')}</ul>`;
}
const review = (r) =>
  r?.status === 'approved'
    ? r.covers_current_master === true
      ? '已确认，发布状态请查看交付记录'
      : '历史版本已确认，当前版本尚无有效确认记录'
    : label(r?.status);
const article = (a) =>
  a
    ? `<h3>${esc(a.title)} · 母稿版本 ${count(a.version_no)}</h3><p>保存于 ${esc(geoTime(a.created_at))}</p><pre class="geo-prose">${esc(a.body_markdown)}</pre>`
    : '<p>尚无已保存母稿。</p>';
function answerRow(r) {
  return `${r.engine?.key === 'hunyuan' ? geoModelNote : ''}` + `<h3>${esc(r.question?.historical_text || r.question?.current_text)}</h3><p>${esc(geoEngineName(r.engine?.key))} / ${esc(r.engine?.provider || '供应商未知')} / ${esc(r.engine?.model || '模型未知')}；精确模型版本未知</p><p>${esc(geoTime(r.captured_at))}；${esc(label(r.source?.kind))}；${esc(label(r.source?.analysis_status))}；品牌提及：${r.mentions_brand === true ? '是' : r.mentions_brand === false ? '否' : '未知'}</p><p>单条资格：${r.sample_eligibility?.eligible === true ? '符合来源与证据要求' : '未通过'}；${esc(reasonText(r.sample_eligibility?.reason_codes))}。${r.week_membership?.within_window === true ? '在所选周内' : '不在所选周内'}；${esc(reasonText(r.week_membership?.reason_codes))}。</p><ul>${(
    r.metric_adoption || []
  )
    .filter((m) => metricNames[m.key])
    .map(
      (m) =>
        `<li>${metricNames[m.key]}：${esc(label(m.status))}；${esc(reasonText(m.reason_codes))}</li>`,
    )
    .join('')}</ul>`;
}
function delivery(r) {
  const task = button('查看稿件', 'content/' + r.task_id),
    variant = button('渠道稿', 'content/' + r.task_id + '/variants/' + r.variant_id);
  if (r.record_type === 'receipt')
    return `<h3>原生投递回执 · ${esc(r.title)}</h3><p>渠道：${channel(r.channel)}</p><p>${esc(label(r.state))}；${esc(geoTime(r.updated_at))}</p><p>${r.reason_code ? esc(geoReason(r.reason_code)) : ''} 回执不等于原生发布登记或页面核验。</p>${task}${variant}`;
  return `<h3>原生发布登记 · ${esc(r.title)}</h3><p>渠道：${channel(r.channel)}</p><p>${esc(label(r.stored_status))}；${esc(geoTime(r.published_at))}；${r.is_current_master ? '当前母稿' : '历史母稿'}</p><p>${r.url_state === 'available' ? geoSafeLink(r.published_url) : domainOnly(r.domain, '发布链接')}</p><p>存量页面核验：${r.verification?.evidence_valid === true ? '已有保存的匹配证据' : '尚无有效匹配证据'}；${esc(r.verification?.state === 'pending' ? '待页面核验' : label(r.verification?.state))}；保存核验时间 ${esc(geoTime(r.verification?.checked_at))}；${esc(reasonText(r.verification?.reason_codes))}。不代表正式客户验收。</p>${task}${variant}${button('关联母稿', 'content/' + r.task_id + '/articles/' + r.article_id)}`;
}
export function geoResource(resource, value) {
  const d = value.data;
  const insight = geoInsightResource(resource, value, {time: geoTime, link: geoSafeLink, basis: geoBasis});
  if (insight !== null) return insight;
  if (resource === 'visibility')
    return `<h2>AI 可见度</h2>${geoWeekly(d.current, d.comparison?.comparable === true)}<p>两周${d.comparison?.comparable === true ? '满足可比较条件' : '不可比较，不展示增长趋势'}：${esc(reasonText(d.comparison?.reason_codes))}</p><details><summary>指标说明</summary>${[
      'mention_count',
      'mention_rate',
      'visibility_score',
      'qualification',
      'ownership_basis',
    ]
      .map((k) => d.definitions?.[k] || '')
      .map((t) => `<p>${esc(t)}</p>`)
      .join(
        '',
      )}</details><h3>按引擎查看观测</h3>${(d.engines || []).map((e) => `<article class="geo-row"><b>${esc(geoEngineName(e.engine_key))}</b><p>${geoObservation(e.observation)}；合格样本 ${count(e.qualified_sample_count)} 条。</p>${button('回答证据', 'answers', {engine_key: e.engine_key})}</article>`).join('') || '<p>暂无引擎观测。</p>'}${button('问题监测', 'questions')}${geoModelNote}${geoBasis(value)}`;
  if (/^questions\//.test(resource)) {
    const q = d.question;
    return `<h2>${esc(q.question)}</h2><p>本期已存合格回答提及率，单格少于 3 条提示小样本。</p>${geoMatrix({...q, by_engine: q.by_engine || d.by_engine}, geoTime)}<p>本周已存回答 ${count(d.evidence?.answer_count)}；不合格回答 ${count(d.evidence?.excluded_answer_count)}；未知时间 ${count(d.evidence?.unknown_time_count)}（当前项目历史中的本问题）。</p>${button('查看全部回答', 'answers', {question_id: q.id})}${button('相关内容', 'content', {question_id: q.id})}${geoBasis(value)}`;
  }
  if (/^answers\//.test(resource))
    return `<h2>单条回答证据</h2>${answerRow(d.item)}<p>历史模型信息${d.comparison_metadata?.complete ? '齐备' : '不完整'}；${esc(reasonText(d.comparison_metadata?.reason_codes))}。</p><pre class="geo-prose">${esc(d.raw_text)}</pre><h3>保存引用</h3><ul>${(d.citations || []).map((c) => `<li>${c.url_state === 'available' ? geoSafeLink(c.url) : domainOnly(c.domain, '引用链接')}；${c.is_own_domain ? '项目自有域' : '非项目自有域'}</li>`).join('')}</ul>${geoBasis(value)}`;
  if (/^content\/\d+\/variants\/\d+$/.test(resource))
    return `<h2>渠道稿 · ${esc(d.variant.title)}</h2><p>渠道：${channel(d.variant.channel)}</p><p>母稿版本 ${count(d.variant.article_version_no)}；${d.variant.is_current_master ? '基于当前母稿' : '基于历史母稿'}；${esc(label(d.variant.stored_status))}</p><pre class="geo-prose">${esc(d.body_markdown)}</pre>${button('关联母稿', `content/${d.variant.task_id}/articles/${d.variant.article_id}`)}${button('交付记录', 'deliveries', {task_id: d.variant.task_id})}${geoBasis(value)}`;
  if (/^content\/\d+\/articles\//.test(resource))
    return `<h2>${d.is_current_master ? '当前母稿' : '历史母稿'}</h2>${article(d.article)}${geoBasis(value)}`;
  if (/^content\/\d+$/.test(resource))
    return `<h2>${esc(d.task.title)}</h2><p>客户确认：${esc(review(d.task.review))}；${esc(geoTime(d.task.review?.reviewed_at))}。确认不等于发布。</p>${article(d.master)}${button('渠道稿', resource + '/variants')}${button('原生交付记录', 'deliveries', {task_id: d.task.id})}<p>已保存投递回执：成功 ${count(d.receipt_summary?.succeeded)} / 处理中 ${count(d.receipt_summary?.sending)} / 失败 ${count(d.receipt_summary?.failed)} / 未知 ${count(d.receipt_summary?.unknown)} / 其他 ${count(d.receipt_summary?.other)}；不代表发布数量。</p>${geoBasis(value)}`;
  const kind =
    resource === 'questions'
      ? '问题监测'
      : resource === 'answers'
        ? '回答证据'
        : resource === 'content'
          ? '内容'
          : resource === 'deliveries'
            ? '原生交付记录'
            : '渠道稿';
  return `<h2>${kind}</h2>${resource === 'deliveries' ? `<p>发布登记、投递回执、客户确认、页面核验分别展示。原生已登记发布 ${count(d.counts?.published_records)} 条；已有存量匹配证据 ${count(d.counts?.stored_verified_publications)} 条。</p>` : ''}${resource === 'questions' ? geoQuestionFilters(d) + '<p>本期已存合格回答提及率，按服务端查询全部问题；单格少于 3 条为小样本。</p>' : ''}${(d.items || []).map((r) => `<article class="geo-row">${resource === 'questions' ? `<h3>${esc(r.question)}</h3><p>${esc(label(r.status))}${r.is_brand_probe ? ' · 品牌点名题' : ''}；${geoObservation(r.observation)}</p><p>${esc(reasonText(r.attention_reason_codes))}</p><p>业务：${esc(r.business?.name || '暂无')}；关键词：${esc(r.unit?.display_name || r.unit?.keyword || r.unit?.name || '暂无')}</p>${geoMatrix(r, geoTime)}${button('查看问题', 'questions/' + r.id)}` : resource === 'answers' ? `${answerRow(r)}<p>${esc(r.answer_excerpt)}${r.excerpt_truncated ? '（节选，查看完整原文）' : ''}</p>${button('回答原文', 'answers/' + r.id)}` : resource === 'content' ? `<h3>${esc(r.title)}</h3><p>${esc(label(r.stored_status))}；${esc(review(r.review))}；当前母稿 ${r.latest_master ? '版本 ' + count(r.latest_master.version_no) : '尚无'}；渠道稿 ${count(r.variant_count)} 份；原生发布登记 ${count(r.published_record_count)} 条。</p>${button('查看稿件', 'content/' + r.id)}` : resource === 'deliveries' ? delivery(r) : `<h3>${esc(r.title)}</h3><p>渠道：${channel(r.channel)}</p><p>母稿版本 ${count(r.article_version_no)}；${r.is_current_master ? '当前母稿' : '历史母稿'}；${esc(label(r.stored_status))}</p>${button('查看渠道稿', resource + '/' + r.id)}`}</article>`).join('') || '<p>当前范围暂无已保存记录。</p>'}<p>当前已加载 ${(d.items || []).length} 条 / 本次查询范围共 ${count(d.pagination?.total_count)} 条。</p>${d.pagination?.has_more ? '<p>仅展示已加载部分，继续加载。</p><button data-geo="more">继续加载</button>' : ''}${geoBasis(value)}`;
}
