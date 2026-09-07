import assert from 'node:assert/strict'
import test from 'node:test'

import { isSecureCockpitRuntime, resolveTenantModuleCodes } from '../src/views/workspace/cockpit/scope.mjs'

const moduleMeta = {
  sem: { permission: ['monitor.dashboard'] },
  seo: { permission: ['seo.site'] },
  geo: { permission: ['geo.content'] },
}

test('local HTTP preview is offline and HTTPS can read', () => {
  assert.equal(isSecureCockpitRuntime({ protocol: 'http:' }), false)
  assert.equal(isSecureCockpitRuntime({ protocol: 'https:' }), true)
})

test('platform-level availability is narrowed to the selected customer', () => {
  const modules = ['sem', 'seo', 'geo'].map(module_code => ({ module_code, available: true }))
  const result = resolveTenantModuleCodes({
    modules,
    tenantId: 16,
    moduleMeta,
    canView: () => true,
    tenantsByModule: {
      sem: [{ id: 16 }],
      seo: [{ id: 1 }],
      geo: [],
    },
  })
  assert.deepEqual([...result], ['sem'])
})

test('permissions still narrow a customer-enabled module', () => {
  const result = resolveTenantModuleCodes({
    modules: [{ module_code: 'sem', available: true }],
    tenantId: 16,
    moduleMeta,
    canView: () => false,
    tenantsByModule: { sem: [{ id: 16 }] },
  })
  assert.deepEqual([...result], [])
})
