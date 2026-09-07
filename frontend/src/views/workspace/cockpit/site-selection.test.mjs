import assert from 'node:assert/strict'
import test from 'node:test'
import { resolveSeoSiteSelection } from './site-selection.mjs'

const active = id => ({ id, name: `站点 ${id}`, domain: `${id}.example`, status: 'active' })
test('保留明确选择的可用站点', () => assert.deepEqual(resolveSeoSiteSelection({ sites: [active(1), active(2)], currentSiteId: 2 }), { siteId: 2, reason: 'selected' }))
test('只有一个可用站点时自动选择', () => assert.deepEqual(resolveSeoSiteSelection({ sites: [active(7)] }), { siteId: 7, reason: 'single_selectable_site' }))
test('多个可用站点时要求客户选择', () => assert.deepEqual(resolveSeoSiteSelection({ sites: [active(1), active(2)] }), { siteId: null, reason: 'selection_required' }))
test('已停用的当前站点必须清空且不能静默切换', () => assert.deepEqual(resolveSeoSiteSelection({ sites: [{ ...active(1), status: 'paused' }, active(2)], currentSiteId: 1 }), { siteId: null, reason: 'selection_unavailable' }))
test('已停用站点清空后的第二轮也必须等待客户选择', () => {
  const sites = [{ ...active(1), status: 'paused' }, active(2)]
  const first = resolveSeoSiteSelection({ sites, currentSiteId: 1 })
  assert.deepEqual(first, { siteId: null, reason: 'selection_unavailable' })
  assert.deepEqual(resolveSeoSiteSelection({ sites, currentSiteId: first.siteId, allowAutomaticSelection: false }), { siteId: null, reason: 'selection_required' })
})
test('被删除站点清空后的第二轮也必须等待客户选择', () => {
  const sites = [active(2)]
  const first = resolveSeoSiteSelection({ sites, currentSiteId: 1 })
  assert.deepEqual(first, { siteId: null, reason: 'selection_unavailable' })
  assert.deepEqual(resolveSeoSiteSelection({ sites, currentSiteId: first.siteId, allowAutomaticSelection: false }), { siteId: null, reason: 'selection_required' })
})
test('没有可用站点时明确返回不可选择', () => assert.deepEqual(resolveSeoSiteSelection({ sites: [{ ...active(1), status: 'archived' }] }), { siteId: null, reason: 'no_selectable_site' }))
