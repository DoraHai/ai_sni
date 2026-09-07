import assert from 'node:assert/strict'
import test from 'node:test'
import { readSeoSiteScope } from './site-scope.mjs'
import { createReadonlyTransport } from '../workbench/readonly-transport.mjs'

function response(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body }
}

function fixture(body) {
  const calls = []
  const boundary = createReadonlyTransport({
    origin: 'https://example.invalid',
    getSession: () => ({ token: 'synthetic-session', revision: 1 }),
    fetchImpl: async (url, options) => {
      calls.push([url, options])
      return response(body)
    },
  })
  return { ...boundary, calls }
}

test('reads tenant-qualified minimal sites and preserves disabled visibility policy', async () => {
  const boundary = fixture({
    tenant_id: 16,
    selection_policy: { selectable_statuses: ['active'], disabled_statuses: ['paused', 'archived'] },
    sites: [
      { id: 3, name: 'Active', domain: 'active.example', status: 'active' },
      { id: 4, name: 'Paused', domain: 'paused.example', status: 'paused' },
      { id: 5, name: 'Archived', domain: 'archived.example', status: 'archived' },
    ],
  })

  const result = await readSeoSiteScope({ transport: boundary.transport, tenantId: 16 })

  assert.equal(boundary.calls[0][0], 'https://example.invalid/api/v1/seo/workbench/sites?tenant_id=16')
  assert.equal(boundary.calls[0][1].method, 'GET')
  assert.deepEqual(result.sites.map(item => [item.id, item.status]), [
    [3, 'active'], [4, 'paused'], [5, 'archived'],
  ])
  assert.deepEqual(result.selectableStatuses, ['active'])
  assert.deepEqual(result.disabledStatuses, ['paused', 'archived'])
})

test('keeps an authorized empty list distinct from permission failure', async () => {
  const boundary = fixture({
    tenant_id: 16,
    selection_policy: { selectable_statuses: ['active'], disabled_statuses: ['paused', 'archived'] },
    sites: [],
  })
  assert.deepEqual((await readSeoSiteScope({ transport: boundary.transport, tenantId: 16 })).sites, [])
  await assert.rejects(
    readSeoSiteScope({ transport: async () => response({}, 403), tenantId: 16 }),
    { code: 'NOT_AUTHORIZED', status: 403 },
  )
})

test('rejects cross-tenant, duplicate, unknown-status and malformed contracts', async () => {
  const validPolicy = { selectable_statuses: ['active'], disabled_statuses: ['paused', 'archived'] }
  for (const body of [
    { tenant_id: 17, selection_policy: validPolicy, sites: [] },
    { tenant_id: 16, selection_policy: validPolicy, sites: [
      { id: 3, name: 'One', domain: 'one.example', status: 'active' },
      { id: 3, name: 'Two', domain: 'two.example', status: 'active' },
    ] },
    { tenant_id: 16, selection_policy: validPolicy, sites: [
      { id: 3, name: 'One', domain: 'one.example', status: 'disabled' },
    ] },
    { tenant_id: 16, selection_policy: {}, sites: [] },
  ]) {
    await assert.rejects(
      readSeoSiteScope({ transport: async () => response(body), tenantId: 16 }),
      { code: 'CONTRACT_MISMATCH' },
    )
  }
})

test('transport rejects missing, duplicate and extra site-scope query parameters', async () => {
  const boundary = fixture({})
  for (const path of [
    '/api/v1/seo/workbench/sites',
    '/api/v1/seo/workbench/sites?tenant_id=16&tenant_id=17',
    '/api/v1/seo/workbench/sites?tenant_id=16&site_id=3',
  ]) {
    await assert.rejects(boundary.transport(path, { method: 'GET' }), { code: 'QUERY_DENIED' })
  }
  assert.equal(boundary.calls.length, 0)
})
