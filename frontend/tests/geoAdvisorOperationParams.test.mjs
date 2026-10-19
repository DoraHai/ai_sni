import test from 'node:test'
import assert from 'node:assert/strict'
import { advisorOperationParams } from '../src/utils/geoAdvisorOperationParams.js'

const actor = { advisor: true, tenantId: 10, projectId: 40 }
test('tenant-wide operations carry the chosen customer and project', () => {
  const result = advisorOperationParams({ method: 'post', url: '/api/v1/geo/onboarding/apply' }, actor)
  assert.deepEqual(result.params, { tenant_id: 10, project_id: 40 })
})
test('task actions keep their object scope and explicit parameters', () => {
  const result = advisorOperationParams({ method: 'post', url: '/api/v1/geo/content-tasks/9/apply-patch',
    params: { tenant_id: 10 } }, actor)
  assert.deepEqual(result.params, { tenant_id: 10 })
})
test('system config and adjacent routes never receive a project grant', () => {
  for (const path of ['/tracking-engines', '/publishing-channels/3/other', '/projects/3/service-plan']) {
    const result = advisorOperationParams({ method: 'put', url: '/api/v1/geo' + path }, actor)
    assert.equal(result.params.project_id, undefined)
  }
})
test('administrators, reads and invalid selections retain existing requests', () => {
  const original = { method: 'get', url: '/api/v1/geo/facts' }
  assert.equal(advisorOperationParams(original, actor), original)
  assert.equal(advisorOperationParams({ ...original, method: 'post' }, { ...actor, advisor: false }).params, undefined)
  assert.equal(advisorOperationParams({ method: 'post', url: '/api/v1/geo/audits' },
    { ...actor, projectId: null }).params.project_id, undefined)
})
