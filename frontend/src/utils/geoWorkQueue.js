// Recommendations are derived from observed evidence, not persisted task assignments.
export function filterWorkTickets(tickets, { status = 'open', owner = '', deadline = '', query = '', today = shanghaiToday() } = {}) {
  const q = query.trim().toLowerCase()
  return tickets.filter((t) => {
    if (status === 'open' ? t.status === 'done' : status && t.status !== status) return false
    if (owner === '__unassigned__' ? !!t.owner_name : owner && t.owner_name !== owner) return false
    if (deadline === 'overdue' && !ticketOverdue(t, today)) return false
    if (deadline === 'today' && (t.status === 'done' || t.due_date !== today)) return false
    if (deadline === 'unset' && t.due_date) return false
    return !q || [t.id, t.title, t.action, t.owner_name].some((value) => String(value || '').toLowerCase().includes(q))
  }).sort((a, b) => Number(a.status === 'done') - Number(b.status === 'done')
    || Number(ticketOverdue(b, today)) - Number(ticketOverdue(a, today))
    || (a.due_date || '9999-12-31').localeCompare(b.due_date || '9999-12-31')
    || Number(b.id) - Number(a.id))
}

export function mergeAssignmentDrafts(previous, next, drafts) {
  const saved = new Map(previous.map((t) => [t.id, t]))
  return Object.fromEntries(next.map((t) => {
    const value = {}
    for (const field of ['owner_name', 'due_date']) {
      const local = drafts[t.id]?.[field]
      value[field] = local !== undefined && local !== (saved.get(t.id)?.[field] || '') ? local : (t[field] || '')
    }
    return [t.id, value]
  }))
}

export function shanghaiToday(now = new Date()) {
  const parts = new Intl.DateTimeFormat('en', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(now)
  const value = (type) => parts.find((p) => p.type === type).value
  return `${value('year')}-${value('month')}-${value('day')}`
}
export function ticketOverdue(ticket, today = shanghaiToday()) {
  return ticket.status !== 'done' && !!ticket.due_date && ticket.due_date < today
}

export function workTicketPayload(item, period) {
  return {
    title: `${item.kind} · ${item.title}`.slice(0, 300),
    advice_code: `workqueue:v1:${item.id}`,
    priority: 'medium', acceptance_type: 'manual',
    action: `观察期：${period}\n为什么做：${item.reason}\n具体动作：${item.action}`
      + (item.promptId ? `\n目标问题 ID：${item.promptId}` : '')
      + (item.opportunity?.sample_ids?.length ? `\n依据快照 ID：${item.opportunity.sample_ids.join('、')}\n证据版本：${item.opportunity.evidence_version || '未提供'}` : ''),
    acceptance_desc: item.acceptance,
  }
}

export function evidenceWorkItems(insights) {
  const source = insights?.source_opportunities
  if (!source || !Array.isArray(source.items)) return []
  const work = source.items.map((item) => ({
    id: `prompt-${item.prompt_id}`, promptId: item.prompt_id, title: item.question,
    kind: item.priority === '优先核对' ? '核对内容机会' : '补充采样',
    reason: item.reason,
    action: item.priority === '优先核对' ? item.next_action : '围绕同一问题补充不同引擎的回答，核对引用和品牌判读后，再决定是否补充内容。',
    acceptance: item.priority === '优先核对'
      ? '记录引用核验结果，列出需要补充的品牌事实；内容更新后，用同一问题复测并记录变化。'
      : '保留原始回答与引用，完成判读；刷新机会列表，重新判断线索是否重复出现。',
    opportunity: item.priority === '优先核对' ? item : null,
  }))
  const excluded = source.excluded_samples || {}
  const reviewCount = Number(excluded.needs_review || 0) + Number(excluded.inaccurate_citation || 0)
  if (reviewCount > 0) work.unshift({
    id: 'review', kind: '核验数据', title: '核验待复核回答与错误引用',
    reason: `${reviewCount} 条样本因待复核或引用不准确被排除。`,
    action: '打开采样记录，对照原始回答与来源页面核对判读；保留不准确标记，直到有依据纠正。',
    acceptance: '每条待核验记录有明确结论；未经核验的数据不用于安排内容生产。',
  })
  if (!source.eligible_samples && !work.length) work.push({
    id: 'collect', kind: '补充采样', title: '为重点业务问题建立可用样本',
    reason: '当前观察期没有满足机会分析条件的样本，暂时无法判断内容缺口。',
    action: '确认重点业务问题，采集真实 API 回答并完成判读，再回到这里刷新。',
    acceptance: '原始回答、目标问题与引用可以追溯，样本已完成判读且不是模拟数据。',
  })
  return work
}

export function taskNextWork(task) {
  if (['archived', 'cancelled'].includes(task.status)) return { action: '已结束', acceptance: '如需继续，重新确认目标和证据。' }
  if (task.status === 'published') return { action: '核对发布记录并同题复测', acceptance: '核对发布页面；记录复测回答、引用及变化。发布状态本身不代表效果提升。', retest: !!task.prompt_id }
  if (task.status === 'ready') return { action: '核对成稿并完成发布', acceptance: '审核品牌事实与出处，保留实际发布页面和记录。' }
  if (['failed', 'needs_fix'].includes(task.status)) return { action: '处理失败原因或修改意见', acceptance: '修复具体问题后重新检查，再推进任务。' }
  return { action: '核对创作要求与事实，推进内容制作', acceptance: '明确目标问题、可核验事实及出处；完成当前步骤后按编辑器检查结果继续。' }
}
