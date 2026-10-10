import {escapeText as esc} from './customer-display.mjs';

const phases = {
  draft: ['待制定方案', '等待顾问制定方案'],
  review: ['待人工审核', '等待顾问审核当前方案'],
  implementation: ['待网站实施', '等待网站实施负责人按批准方案实施'],
  recheck: ['待系统复检', '等待复检实际页面'],
  acceptance: ['待人工验收', '等待顾问核对质量并验收'],
  done: ['交付已验收', '另行查看效果观测'],
  cancelled: ['已取消', '请顾问核对后续安排'],
};
const workTypes = {startup: '启动建设', monthly: '月度维护', remediation: '专项整改'};
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const id = value => Number.isSafeInteger(value) && value > 0;
const text = value => typeof value === 'string' ? value.trim() : '';
const validMonth = value => typeof value === 'string' && /^[1-9]\d{3}-(0[1-9]|1[0-2])$/.test(value);
const label = (map, key, fallback) => Object.hasOwn(map, key) ? map[key] : fallback;

function currentMonth() {
  const parts = new Intl.DateTimeFormat('en', {timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit'})
    .formatToParts(new Date());
  return `${parts.find(p => p.type === 'year').value}-${parts.find(p => p.type === 'month').value}`;
}

// These checks protect display consistency, not authorization. The parent must bind
// the response to its current authenticated context and discard late responses.
function matchesScope(value, data, module) {
  const field = module === 'geo' ? 'project_id' : 'site_id';
  const foreign = module === 'geo' ? 'site_id' : 'project_id';
  return value.module === module && value.tenant_id === data.tenant_id && value.scope_id === data.scope_id &&
    (value[field] == null || value[field] === data.scope_id) && value[foreign] == null;
}

function validList(data, module) {
  return object(data) && id(data.tenant_id) && id(data.scope_id) && matchesScope(data, data, module) &&
    Array.isArray(data.items) && typeof data.can_create === 'boolean' &&
    (data.next_before_id == null || id(data.next_before_id)) &&
    data.items.every(row => object(row) && id(row.id) && matchesScope(row, data, module) &&
      object(row.workflow) && row.workflow.module === module);
}

function taskLink(data, row, module) {
  const query = new URLSearchParams({module, tenant_id: data.tenant_id,
    [module === 'geo' ? 'project_id' : 'site_id']: data.scope_id, onsite_task_id: row.id});
  return `/customer-workbench/?${query}`;
}

function missingInformation(workflow) {
  const proposal = workflow.ai_proposal;
  const entries = [proposal?.missing_information,
    ...(Array.isArray(proposal?.items) ? proposal.items.map(item => item?.missing_information) : [])];
  return [...new Set(entries.flatMap(value => Array.isArray(value) ? value : [value]).map(text).filter(Boolean))];
}

function taskCard(row, data, module) {
  const w = row.workflow;
  const title = text(row.title) || '任务名称未提供';
  const keywords = module === 'seo' && Array.isArray(w.source?.keywords)
    ? w.source.keywords.map(word => text(word?.keyword)).filter(Boolean) : [];
  const focus = keywords.length ? keywords.join('、') : title;
  const [phase, next] = label(phases, w.phase, ['阶段待核对', '请顾问核对任务当前阶段']);
  const missing = missingInformation(w);
  const month = validMonth(w.month) ? w.month : w.work_type === 'startup' && w.month == null
    ? '启动建设（未按月归属）' : '月份待核对';
  return `<article class="phase-row customer-onsite-task">
    <h4>${esc(title)}</h4>
    <p>${esc(label(workTypes, w.work_type, '任务类型待核对'))} · 服务月份：${esc(month)}</p>
    <p>${module === 'seo' ? '重点词 / 任务' : '重点问题 / 任务'}：${esc(focus)}</p>
    <p>真实阶段：${esc(phase)} · 网站实施负责人：${esc(text(w.owner_name) || '尚未提供')}</p>
    <p>下一步：${esc(next)}</p>
    <p>待补资料：${esc(missing.length ? missing.join('；') : '未提供待补资料清单，请顾问核对')}</p>
    <p>交付：${w.phase === 'done' ? '已通过人工验收' : w.phase === 'cancelled' ? '任务已取消，未据此认定交付完成' : '尚未确认交付完成'}；效果观测：${module === 'seo' ? '收录与排名' : 'AI 引用'}需另行查看，本列表未提供效果结论。</p>
    <a href="${esc(taskLink(data, row, module))}">查看任务 #${row.id}</a>
  </article>`;
}

/**
 * Render only a scoped onsite list response; performs no I/O or business actions.
 * null/undefined = unread; Error or {error:true} = failed (never echo raw errors).
 * month = YYYY-MM, defaults to the current Asia/Shanghai service month.
 * Returns HTML. Parent owns fetching, scope authorization, and task-link handling.
 */
export function customerOnsiteSummary(data, {module = 'seo', month = currentMonth()} = {}) {
  const section = body => `<section class="customer-onsite-summary"><h2>本月站内计划与进度</h2>${body}</section>`;
  if (!['seo', 'geo'].includes(module)) return section('<p>当前模块暂不支持站内计划摘要。</p>');
  if (!validMonth(month)) return section('<p>服务月份待核对，暂不展示计划。</p>');
  const heading = `<p>服务月份：${esc(month)}</p>`;
  if (data == null) return section(`${heading}<p>尚未读取站内计划。</p>`);
  if (data instanceof Error || data?.error === true) return section(`${heading}<p role="status">站内计划读取失败，请稍后重新读取。</p>`);
  if (!validList(data, module)) return section(`${heading}<p role="status">读取结果不完整或数据范围不匹配，暂不展示任务。</p>`);

  const monthly = data.items.filter(row => row.workflow.month === month);
  const startup = data.items.filter(row => row.workflow.work_type === 'startup' && row.workflow.month == null);
  const undated = data.items.filter(row => !validMonth(row.workflow.month) && !startup.includes(row));
  const otherMonths = data.items.length - monthly.length - startup.length - undated.length;
  const group = (title, rows) => rows.length ? `<h3>${title}</h3>${rows.map(row => taskCard(row, data, module)).join('')}` : '';
  const coverage = `<p>仅展示已读取分页范围；已读取 ${data.items.length} 条，其中本月 ${monthly.length} 条。此数量不是全站或项目任务总数。${data.next_before_id != null ? '还有更多任务未读取，本月计划可能不完整。' : '当前响应未提示后续页，不据此推断历史分页已全部读取。'}</p>`;
  return section(`${heading}${coverage}
    ${!data.items.length ? '<p>已读取的列表为空，当前范围暂无站内任务。</p>' : !monthly.length ? '<p>已读取范围内暂无本月任务。</p>' : ''}
    ${group('本月计划', monthly)}
    ${group('启动建设（不计入本月任务）', startup)}
    ${group('月份待核对（不计入本月任务）', undated)}
    ${otherMonths ? `<p>已读取范围另有 ${otherMonths} 条其他月份任务，未列入本月计划。</p>` : ''}`);
}
