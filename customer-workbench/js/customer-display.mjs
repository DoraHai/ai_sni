// Presentation only. Never use these labels to decide permissions or workflow completion.
const statuses = {
  content: {
    planned: '待制作', drafting: '修改中', draft: '修改中', review: '顾问审核中',
    ready: '稿件已备好', approved_waiting_publication: '已确认，待发布',
    awaiting_confirmation: '待确认稿件', awaiting_internal_review: '顾问审核中',
    awaiting_draft: '待顾问制作', confirmation_unavailable: '确认功能暂不可用',
    published: '已发布', archived: '已归档', rejected: '已退回修改',
  },
  confirmation: {
    approved: '当前版本已确认', rejected: '已退回，等待修改',
    stale: '稿件已更新，旧确认不适用于当前版本', pending: '等待确认',
    unavailable: '暂时无法确认', not_required: '无需确认',
  },
  publication: {
    preparing: '发布准备中', manual_required: '待顾问登记发布结果',
    published: '已记录发布', failed: '发布未成功', draft: '待发布',
    queued: '等待发布处理', running: '发布处理中', cancelled: '已取消',
    not_loaded: '尚未查看', unavailable: '暂不可用', no_data: '暂无记录',
    not_queued: '尚未安排检查', capture_disabled: '页面检查未开启',
    pending: '等待检查', verified: '页面已核验',
  },
  task: { open: '待处理', in_progress: '处理中', done: '已完成', cancelled: '已取消', failed: '需要处理', paused: '已暂停' },
  readiness: { ready: '资料已备齐', needs_attention: '有事项待处理', not_ready: '尚未准备好', no_data: '暂无数据' },
  phase: {
    ai_draft_in_progress: '正在制作草稿', ai_draft_needs_attention: '草稿需要顾问处理',
    awaiting_draft: '待顾问制作稿件', awaiting_internal_review: '待顾问审核',
    awaiting_confirmation: '等待稿件确认', awaiting_publication: '待顾问安排发布',
    awaiting_publication_selection: '待关联发布记录', awaiting_manual_publication: '待顾问登记发布结果',
    publication_needs_check: '发布结果需要核对', awaiting_page_evidence: '等待检查发布页面',
    page_evidence_needs_attention: '发布页面需要核对', page_evidence_ready: '页面依据已备齐，效果待核对',
    completed_with_page_evidence: '发布与页面核验已完成', diagnosis_queued: '等待网站检查',
    awaiting_site_implementation: '待修改网站并复查', awaiting_ranking_observations: '等待新的排名数据',
    report_queued: '等待准备报告', awaiting_advisor_explanation: '待顾问补充说明',
    report_needs_attention: '报告需要处理', completed_with_evidence: '已完成并留存依据',
    no_actionable_issues: '本次未发现需处理的问题', needs_attention: '需要顾问处理', paused: '已暂停',
  },
};

const reasons = {
  brand_profile_missing: '客户基础资料待完善', pages_waiting_for_check: '还有页面等待检查',
  crawl_run_missing: '尚无网站检查记录', ranking_observations_missing: '尚未取得排名数据',
  ranking_run_missing: '尚无排名检查记录', metric_observations_missing: '尚未取得统计数据',
  confirmation_pending: '等待客户确认，或由已分配顾问代确认',
  confirmation_stale: '稿件已修改，需要重新确认', confirmation_rejected: '稿件已退回，需要修改',
  capture_disabled: '页面检查未开启，请顾问处理', page_evidence_missing: '尚未取得发布页面的检查结果',
  publication_missing: '尚未关联发布记录', manual_publication_required: '需要顾问登记实际发布结果',
  content_version_conflict: '稿件已更新，请先查看最新版本',
  service_plan_version_conflict: '服务计划已更新，请先查看最新内容',
  active_site_advisor_assignment_required: '当前账号未分配为本站顾问',
  content_and_site_edit_permissions_required: '此项由本站顾问管理',
  authenticated_user_required: '请先登录', advisor_assignment_schema_unavailable: '顾问分配功能暂不可用',
  ai_draft_deepseek_not_configured: 'AI 草稿服务尚未配置',
  ai_draft_needs_attention: '草稿制作需要顾问处理',
  ai_draft_disabled: '自动草稿尚未开启', missing: '尚无记录', stale: '数据需要更新',
  rank_drop: '排名下降', paused: '服务已暂停', no_data: '暂无数据', not_loaded: '尚未查看',
  not_generated: '尚未生成', unavailable: '暂不可用',
};

const fields = {
  content_count: '稿件数', content_total: '稿件总数', total: '总数',
  planned_count: '待制作', drafting_count: '修改中', review_count: '待审核', ready_count: '稿件已备好',
  published_count: '已发布', publication_count: '发布记录',
  page_count: '页面数', pages_count: '页面数', checked_page_count: '已检查页面',
  keyword_count: '关键词数', active_keyword_count: '启用关键词',
  fact_count: '资料条数', active_fact_count: '可用资料',
  clicks: '搜索点击', impressions: '搜索展示', ctr: '点击率', position: '平均排名',
  avg_position: '平均排名', average_position: '平均排名',
  issues_count: '待处理问题', pending_count: '待处理', failed_count: '未成功',
  site_id: '网站编号', content_id: '稿件编号', keyword_id: '关键词编号',
  page_url: '页面地址', published_at: '发布时间', updated_at: '更新时间',
  as_of: '数据时间', read_at: '读取时间', source: '数据来源',
};

const known = (dictionary, key) => typeof key === 'string' && Object.hasOwn(dictionary, key);

export function statusLabel(value, kind = 'content') {
  if (value == null || value === '') return '状态未提供';
  const dictionary = known(statuses, kind) ? statuses[kind] : {};
  return known(dictionary, value) ? dictionary[value] : '状态待核对';
}

export function reasonLabel(value) {
  if (value == null || value === '') return '未提供具体原因';
  return known(reasons, value) ? reasons[value] : '需要顾问核对具体原因';
}

export function fieldLabel(value) {
  return known(fields, value) ? fields[value] : '其他信息';
}

export function escapeText(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
}

function validCalendar(year, month, day) {
  const date = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
  return date.getUTCFullYear() === Number(year) && date.getUTCMonth() + 1 === Number(month) && date.getUTCDate() === Number(day);
}

export function formatTime(value, { dateOnly = false } = {}) {
  if (typeof value !== 'string' || !value.trim()) return '时间未提供';
  const source = value.trim();
  const date = source.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (date) return validCalendar(...date.slice(1)) ? source.replaceAll('-', '/') : '时间待核对';
  const stamp = source.match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d{1,9})?)?(Z|[+-]\d{2}:\d{2})?$/i);
  if (!stamp || !validCalendar(...stamp.slice(1, 4)) || Number(stamp[4]) > 23 || Number(stamp[5]) > 59 || Number(stamp[6] ?? 0) > 59) return '时间待核对';
  const [, year, month, day, hour, minute, seconds = '00', zone] = stamp;
  // Do not quietly reinterpret timezone-less database values using the browser's locale.
  if (!zone) return `${year}/${month}/${day}${dateOnly ? '' : ` ${hour}:${minute}`}（时区未提供）`;
  const normalized = `${year}-${month}-${day}T${hour}:${minute}:${seconds}${zone.toUpperCase()}`;
  const parsed = new Date(normalized);
  if (!Number.isFinite(parsed.getTime())) return '时间待核对';
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(parsed).map(part => [part.type, part.value]));
  return `${parts.year}/${parts.month}/${parts.day}${dateOnly ? '' : ` ${parts.hour}:${parts.minute}`}`;
}

export function formatMetric(value, { unit = '', digits = 0 } = {}) {
  if (value == null || (typeof value !== 'number' && typeof value !== 'string') || (typeof value === 'string' && !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(value.trim()))) return '—';
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  const precision = Number.isInteger(digits) ? Math.min(6, Math.max(0, digits)) : 0;
  return `${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: precision }).format(Object.is(number, -0) ? 0 : number)}${unit}`;
}
