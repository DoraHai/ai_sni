export const QUEUE_STAGES = [
  { value: 'reconciliation_required', label: '待人工对账', cls: 'v-bad' },
  { value: 'pending_writeback', label: '演练待回写（未真改）', cls: 'st-pending' },
  { value: 'executed', label: '百度已执行', cls: 'st-ok' },
  { value: 'failed', label: '执行失败', cls: 'v-bad' },
]

export function queueStageMeta(stage) {
  return QUEUE_STAGES.find((item) => item.value === stage)
    || { value: 'unknown', label: '状态未知，请核查', cls: 'v-bad' }
}

export function filterQueue(items, stage) {
  return stage ? items.filter((item) => item.stage === stage) : items
}

export function queueCounts(items) {
  const counts = Object.fromEntries(QUEUE_STAGES.map((item) => [item.value, 0]))
  counts.unknown = 0
  for (const item of items) counts[queueStageMeta(item.stage).value] += 1
  return counts
}
