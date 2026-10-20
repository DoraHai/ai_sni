// Run with Node directly from a UTF-8 source file (never a shell text pipe).
import fs from 'node:fs'
import { createHash } from 'node:crypto'

const samples = [
  { schema: 2, eventId: '11111111-1111-4111-8111-111111111111', attemptId: '22222222-2222-4222-8222-222222222222', occurredAt: '2026-10-19T11:00:00.000Z', platform: '新平台', title: '合成标题 😀', reportedAccount: '演示账号', result: 'success', reasonCode: null, publicUrl: 'https://Example.INVALID/Article?b=2&a=1#fragment', reviewed: true },
  { schema: 2, eventId: '33333333-3333-4333-8333-333333333333', attemptId: '22222222-2222-4222-8222-222222222222', occurredAt: '2026-10-18T00:00:00.000Z', platform: 'other', title: null, reportedAccount: null, result: 'risk_control', reasonCode: 'risk_control', publicUrl: null, reviewed: true },
  { schema: 2, eventId: '44444444-4444-4444-8444-444444444444', attemptId: '55555555-5555-4555-8555-555555555555', occurredAt: '2026-10-19T11:00:00.000Z', platform: 'wechat', title: 'line\nquote"slash/反斜\\', reportedAccount: null, result: 'pending_review', reasonCode: 'pending_review', publicUrl: 'http://EXAMPLE.invalid:8080/a#x', reviewed: true },
]
const keys = ['schema','eventId','attemptId','occurredAt','platform','title','reportedAccount','result','reasonCode','publicUrl','reviewed']
const events = samples.map(event => {
  const canonicalJson = JSON.stringify(keys.map(k => event[k]))
  return { event: { ...event, payloadDigest: createHash('sha256').update(canonicalJson, 'utf8').digest('hex') }, canonicalJson }
})
const data = { version: '2.0.1', digestAlgorithm: 'sha256-json-array-utf8-v1', events,
  urlExamples: [
    { input: 'https://Example.INVALID/Article?b=2&a=1#fragment', canonical: 'https://example.invalid/Article?b=2&a=1' },
    { input: 'http://EXAMPLE.invalid:8080/a#x', canonical: 'http://example.invalid:8080/a' },
  ],
  reject: [
    { change: { tenantId: 1 }, code: 'INVALID_SHAPE' }, { change: { reviewed: false }, code: 'INVALID_SHAPE' },
    { change: { publicUrl: 'https://user:pass@example.invalid/' }, code: 'INVALID_PUBLIC_URL' },
    { change: { publicUrl: 'file:///test' }, code: 'INVALID_PUBLIC_URL' },
  ],
}
fs.writeFileSync(new URL('../tests/fixtures/inbox_vectors_v2.json', import.meta.url), JSON.stringify(data, null, 2)+'\n', 'utf8')
