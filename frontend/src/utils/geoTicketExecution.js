export function snapshotIds(text) {
  const values = String(text || '').trim().split(/[\s,，、]+/).filter(Boolean)
  if (values.some((v) => !/^[1-9]\d*$/.test(v) || !Number.isSafeInteger(Number(v)))) throw new Error('快照编号必须为正整数，以逗号分隔')
  const ids = [...new Set(values.map(Number))]
  if (ids.length > 100) throw new Error('每组最多关联 100 条样本')
  return ids
}

export function executionDraft(ticket) {
  return {
    taskId: ticket.content_task_id || '',
    before: (ticket.baseline_snapshot?.samples || []).map((s) => s.id).join(', '),
    after: (ticket.progress?.samples || []).map((s) => s.id).join(', '),
    note: ticket.progress?.change_note || '',
  }
}
