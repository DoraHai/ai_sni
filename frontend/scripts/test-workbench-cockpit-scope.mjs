import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  COCKPIT_PERMISSION_KEYS,
  MODULE_PERMISSION_KEYS,
  canViewCockpit,
  countUnresolvedModules,
  hasDataReadPermission,
  isCurrentCockpitScope,
  isSecureCockpitRuntime,
  resolveTenantModuleCodes,
  selectAvailableModules,
} from '../src/views/workspace/cockpit/scope.mjs'

const moduleMeta = {
  sem: { permission: ['monitor.dashboard', 'optimize.keywords', 'optimize.searchterms'] },
  seo: { permission: ['seo.site', 'seo.content'] },
  geo: { permission: ['geo.content'] },
}

const scoped = (codes, tenantId = 16) => resolveTenantModuleCodes({
  modules: ['sem', 'seo', 'geo'].map(module_code => ({
    module_code,
    available: codes.includes(module_code),
  })),
  tenantId,
  moduleMeta,
  tenantsByModule: Object.fromEntries(codes.map(code => [code, [{ id: tenantId }]])),
})

test('local HTTP preview is offline and HTTPS can read', () => {
  assert.equal(isSecureCockpitRuntime({ protocol: 'http:' }), false)
  assert.equal(isSecureCockpitRuntime({ protocol: 'https:' }), true)
})

test('single, dual and triple purchases expose exactly their customer-scoped modules', () => {
  assert.deepEqual([...scoped(['sem'])], ['sem'])
  assert.deepEqual([...scoped(['sem', 'seo'])], ['sem', 'seo'])
  assert.deepEqual([...scoped(['sem', 'seo', 'geo'])], ['sem', 'seo', 'geo'])
})

test('questions, data area, urgent state and ledger receive purchased modules only', () => {
  const modules = ['sem', 'seo', 'geo'].map(module_code => ({ module_code, available: true }))
  const single = selectAvailableModules(modules, scoped(['seo']), moduleMeta)
  const dual = selectAvailableModules(modules, scoped(['sem', 'geo']), moduleMeta)
  assert.deepEqual(single.map(item => item.module_code), ['seo'])
  assert.deepEqual(dual.map(item => item.module_code), ['sem', 'geo'])
  assert.equal(countUnresolvedModules(single, { sem: 'waiting', seo: 'denied', geo: 'waiting' }), 1)
  assert.equal(countUnresolvedModules(dual, { sem: 'ready', seo: 'error', geo: 'ready' }), 0)
})

test('unavailable, expired and other-customer modules stay hidden', () => {
  const result = resolveTenantModuleCodes({
    modules: [
      { module_code: 'sem', available: false, status: 'expired' },
      { module_code: 'seo', available: true },
      { module_code: 'geo', available: true },
    ],
    tenantId: 16,
    moduleMeta,
    tenantsByModule: { sem: [{ id: 16 }], seo: [{ id: 1 }], geo: [] },
  })
  assert.deepEqual([...result], [])
})

test('an entitled module remains visible when fine-grained data reads are unavailable', () => {
  const result = resolveTenantModuleCodes({
    modules: [{ module_code: 'sem', available: true }],
    tenantId: 16,
    moduleMeta,
    tenantsByModule: { sem: [{ id: 16 }] },
  })
  assert.deepEqual([...result], ['sem'])
  assert.equal(hasDataReadPermission('sem', () => false, moduleMeta), false)
})

test('cockpit route accepts every backend module view permission', () => {
  assert.deepEqual(COCKPIT_PERMISSION_KEYS, Object.values(MODULE_PERMISSION_KEYS).flat())
  for (const permission of COCKPIT_PERMISSION_KEYS) {
    assert.equal(canViewCockpit(key => key === permission), true, permission)
  }
  assert.equal(canViewCockpit(() => false), false)
})

test('frontend cockpit permissions cover the SEO registry and current backend module map', async () => {
  const source = await readFile(new URL('../../app/api/auth.py', import.meta.url), 'utf8')
  const block = source.match(/_MODULE_PERMISSION_KEYS = \{([\s\S]*?)\n\}/)?.[1]
  assert.ok(block, 'backend module permission map must remain discoverable')
  for (const moduleCode of ['sem', 'geo']) {
    const expected = MODULE_PERMISSION_KEYS[moduleCode]
    const nextCode = moduleCode === 'sem' ? 'seo' : null
    const pattern = nextCode
      ? new RegExp(`"${moduleCode}":[\\s\\S]*?(?=\\n\\s*"${nextCode}")`)
      : new RegExp(`"${moduleCode}":[\\s\\S]*$`)
    const moduleBlock = block.match(pattern)?.[0]
    assert.ok(moduleBlock, `${moduleCode} permissions must remain discoverable`)
    const observed = [...moduleBlock.matchAll(/"([a-z][a-z0-9_.]+)"/g)].map(match => match[1]).slice(1)
    assert.deepEqual(observed, expected, `${moduleCode} cockpit route permissions drifted from backend availability`)
  }
  const registry = await readFile(new URL('../../app/permissions.py', import.meta.url), 'utf8')
  const seoKeys = [...registry.matchAll(/\{"key": "(seo\.[a-z0-9_.]+)"/g)].map(match => match[1])
  assert.deepEqual(MODULE_PERMISSION_KEYS.seo, seoKeys, 'SEO cockpit permissions drifted from registered routes')
})

test('tenant switches and late authorization responses cannot publish stale scope', () => {
  const ticket = { generation: 4, tenantId: 16, authRevision: 8 }
  assert.equal(isCurrentCockpitScope(ticket, { generation: 4, tenantId: 16, authRevision: 8 }), true)
  assert.equal(isCurrentCockpitScope(ticket, { generation: 4, tenantId: 17, authRevision: 8 }), false)
  assert.equal(isCurrentCockpitScope(ticket, { generation: 5, tenantId: 16, authRevision: 8 }), false)
  assert.equal(isCurrentCockpitScope(ticket, { generation: 4, tenantId: 16, authRevision: 9 }), false)
})
