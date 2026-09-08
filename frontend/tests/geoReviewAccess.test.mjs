import test from 'node:test'
import assert from 'node:assert/strict'
import { canDecideGeoReview, canSubmitGeoReview } from '../src/utils/geoReviewAccess.js'

test('tenant-bound brand customer can decide review but cannot submit it', () => {
  const user = { id: 7, tenant_id: 15, role_label: '品牌方客户', permissions: { 'geo.content': 'view' } }
  assert.equal(canDecideGeoReview(user), true)
  assert.equal(canSubmitGeoReview(user), false)
})

test('unbound or anonymous GEO viewers cannot decide customer review', () => {
  assert.equal(canDecideGeoReview({ id: 7, tenant_id: null, role_label: '品牌方客户', permissions: { 'geo.content': 'view' } }), false)
  assert.equal(canDecideGeoReview({ id: null, tenant_id: 15, role_label: '品牌方客户', permissions: { 'geo.content': 'view' } }), false)
})

test('GEO editors retain submit and decision controls', () => {
  const user = { id: 9, tenant_id: null, permissions: { 'geo.content': 'edit' } }
  assert.equal(canSubmitGeoReview(user), true)
  assert.equal(canDecideGeoReview(user), true)
})

test('accounts without GEO content access get no review controls', () => {
  const user = { id: 8, tenant_id: 15, role_label: '品牌方客户', permissions: { 'seo.content': 'view' } }
  assert.equal(canSubmitGeoReview(user), false)
  assert.equal(canDecideGeoReview(user), false)
})

test('custom tenant-bound read-only roles cannot decide customer review', () => {
  const user = { id: 5, tenant_id: 16, role_label: '__workbench_test_readonly__', permissions: { 'geo.content': 'view' } }
  assert.equal(canSubmitGeoReview(user), false)
  assert.equal(canDecideGeoReview(user), false)
})
