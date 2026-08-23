import test from 'node:test'
import assert from 'node:assert/strict'

import {
  normalizeGeoScope,
  parseGeoScopeId,
} from '../src/utils/geoPrototypeScope.js'
import { GEO_WORKBENCH_NAV } from '../src/utils/geoPrototypeNavigation.js'

test('invalid scope query values are treated as unset', () => {
  assert.equal(parseGeoScopeId('abc'), null)
  assert.equal(parseGeoScopeId('0'), null)
  assert.equal(parseGeoScopeId('-2'), null)
  assert.equal(parseGeoScopeId('12'), 12)
})

test('scope drops a unit outside the selected business', () => {
  const scope = normalizeGeoScope(
    { businessId: 1, unitId: 20, promptId: 100 },
    {
      businesses: [{ id: 1 }],
      units: [{ id: 10, business_id: 1 }, { id: 20, business_id: 2 }],
      prompts: [{ id: 100, unit_id: 20 }],
    },
  )

  assert.deepEqual(scope, {
    businessId: 1,
    unitId: null,
    promptId: null,
  })
})

test('scope drops a prompt outside the selected unit', () => {
  const scope = normalizeGeoScope(
    { businessId: 1, unitId: 10, promptId: 101 },
    {
      businesses: [{ id: 1 }],
      units: [{ id: 10, business_id: 1 }],
      prompts: [{ id: 100, unit_id: 10 }, { id: 101, unit_id: 11 }],
    },
  )

  assert.deepEqual(scope, {
    businessId: 1,
    unitId: 10,
    promptId: null,
  })
})

test('prototype navigation includes evaluation analysis and excludes team permissions', () => {
  const sections = GEO_WORKBENCH_NAV.map((group) => group.label)
  const items = GEO_WORKBENCH_NAV.flatMap((group) =>
    group.children.map((item) => item.label),
  )

  assert.deepEqual(sections, ['数据看板', '智能监测', 'GEO 执行', '设置'])
  assert.ok(items.includes('评价分析'))
  assert.ok(!items.includes('团队权限'))
})
