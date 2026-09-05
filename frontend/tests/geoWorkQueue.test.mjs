import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const code = readFileSync(new URL('../src/utils/geoWorkQueue.js', import.meta.url), 'utf8')
const { evidenceWorkItems, taskNextWork, workTicketPayload, shanghaiToday, ticketOverdue, filterWorkTickets, mergeAssignmentDrafts } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)
test('work filters combine owner, status, deadline and search without changing totals', () => {
  const tickets = [
    { id: 1, title: '引用核验', owner_name: '张三', status: 'doing', due_date: '2026-09-04' },
    { id: 2, title: '采样', owner_name: '李四', status: 'todo', due_date: '2026-09-05' },
    { id: 3, title: '旧任务', owner_name: '张三', status: 'done', due_date: '2026-09-03' },
    { id: 4, status: 'todo' },
  ]
  const options = { today: '2026-09-05' }
  assert.deepEqual(filterWorkTickets(tickets, options).map((t) => t.id), [1, 2, 4])
  assert.deepEqual(filterWorkTickets(tickets, { ...options, owner: '张三', deadline: 'overdue', query: '引用' }).map((t) => t.id), [1])
  assert.deepEqual(filterWorkTickets(tickets, { ...options, deadline: 'today' }).map((t) => t.id), [2])
  assert.deepEqual(filterWorkTickets(tickets, { ...options, owner: '__unassigned__', deadline: 'unset' }).map((t) => t.id), [4])
  assert.deepEqual(filterWorkTickets(tickets, { ...options, status: 'done' }).map((t) => t.id), [3])
  assert.equal(filterWorkTickets(tickets, { ...options, query: '不存在' }).length, 0)
  assert.deepEqual(tickets.map((t) => t.id), [1, 2, 3, 4])
})
test('refresh keeps edited fields while updating clean fields and dropping removed tickets', () => {
  const old = [{ id: 1, owner_name: '旧负责人', due_date: '2026-09-05' }, { id: 2 }]
  const next = [{ id: 1, owner_name: '服务端负责人', due_date: '2026-09-06' }, { id: 3, owner_name: '新负责人' }]
  const merged = mergeAssignmentDrafts(old, next, { 1: { owner_name: '未保存姓名', due_date: '2026-09-05' }, 2: { owner_name: '旧草稿' } })
  assert.deepEqual(merged[1], { owner_name: '未保存姓名', due_date: '2026-09-06' })
  assert.equal(merged[2], undefined)
  assert.equal(merged[3].owner_name, '新负责人')
})
test('deadline uses Shanghai date and excludes completed tickets', () => {
  const today = shanghaiToday(new Date('2026-09-05T16:01:00Z'))
  assert.equal(today, '2026-09-06')
  assert.equal(ticketOverdue({ status: 'doing', due_date: '2026-09-05' }, today), true)
  assert.equal(ticketOverdue({ status: 'doing', due_date: today }, today), false)
  assert.equal(ticketOverdue({ status: 'done', due_date: '2026-09-05' }, today), false)
  assert.equal(ticketOverdue({ status: 'todo' }, today), false)
})
test('accepted suggestion retains its period, cause and acceptance instructions', () => {
  const payload = workTicketPayload({ id: 'collect', kind: '补充采样', title: '问题', reason: '缺少数据', action: '采样', acceptance: '核验原始回答' }, '近14天')
  assert.equal(payload.advice_code, 'workqueue:v1:collect')
  assert.match(payload.action, /近14天/)
  assert.match(payload.action, /缺少数据/)
  assert.equal(payload.acceptance_desc, '核验原始回答')
  assert.equal(payload.acceptance_type, 'manual')
})
const data = (items = [], eligible = 0, excluded = {}) => ({ source_opportunities: { items, eligible_samples: eligible, excluded_samples: excluded } })
test('unavailable data never masquerades as a no-work result', () => {
  assert.deepEqual(evidenceWorkItems(null), [])
  assert.deepEqual(evidenceWorkItems({}), [])
})
test('no usable evidence requests collection, not content production', () => {
  const [item] = evidenceWorkItems(data())
  assert.equal(item.kind, '补充采样')
  assert.equal(item.opportunity, undefined)
})
test('usable evidence without opportunity does not invent a content gap', () => {
  assert.deepEqual(evidenceWorkItems(data([], 10)), [])
})
test('weak signal routes to collection while repeated signal can create a task', () => {
  const rows = [{ prompt_id: 2, priority: '补充采样' }, { prompt_id: 3, priority: '优先核对', sample_ids: [1, 2, 3] }]
  const result = evidenceWorkItems(data(rows, 4))
  assert.equal(result[0].opportunity, null)
  assert.equal(result[0].promptId, 2)
  assert.equal(result[1].opportunity, rows[1])
  assert.ok(result.every((x) => x.acceptance))
})
test('review and inaccurate citations produce verification work', () => {
  const [item] = evidenceWorkItems(data([], 0, { needs_review: 2, inaccurate_citation: 1 }))
  assert.equal(item.kind, '核验数据')
  assert.match(item.reason, /3 条/)
  assert.equal(item.opportunity, undefined)
})
test('published tasks suggest retest without declaring effectiveness', () => {
  assert.equal(taskNextWork({ status: 'published', prompt_id: 2 }).retest, true)
  assert.match(taskNextWork({ status: 'published' }).acceptance, /不代表效果提升/)
  assert.equal(taskNextWork({ status: 'archived', prompt_id: 2 }).retest, undefined)
  assert.match(taskNextWork({ status: 'failed' }).action, /失败/)
})
