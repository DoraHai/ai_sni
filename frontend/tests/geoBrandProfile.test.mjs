import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { advisorBrandProfile } from '../src/utils/geoBrandProfile.js'

const source = readFileSync(new URL('../src/views/geo/GeoBrandSettingsView.vue', import.meta.url), 'utf8')
const handler = source.slice(source.indexOf('async function save()'), source.indexOf('async function createBusiness()'))

test('advisor sends only allowed fields and round trips form list separators', () => {
  const profile = { product_name: '品牌', website: 'https://example.test', summary: '简介', industry: '行业',
    audience: '受众', cta: '了解更多', honors: '甲，乙', qualifications: '一,二；三\n四',
    capabilities: ['能力'], scenarios: '', competitors: '竞品甲，竞品乙', recommend_reasons: '理由', banned_claims: '禁用',
    geo_scope: '区域', tenant_id: 20, status: 'published', extra: { id: 20 } }
  const result = advisorBrandProfile(profile)
  assert.equal(Object.keys(result).length, 13)
  assert.deepEqual(result.qualifications, ['一', '二', '三', '四'])
  assert.deepEqual(result.competitors, ['竞品甲', '竞品乙'])
  assert.deepEqual(result.scenarios, [])
  for (const key of ['geo_scope', 'tenant_id', 'status', 'extra']) assert.equal(Object.hasOwn(result, key), false)
  assert.equal(profile.honors, '甲，乙')
  assert.deepEqual(advisorBrandProfile({ summary: '部分修改' }), { summary: '部分修改' })
})

test('save shows the backend reason and keeps the unsaved profile after rejection', async () => {
  const calls = [], errors = []
  const profile = { product_name: '品牌', geo_scope: '原区域' }
  const context = vm.createContext({
    current: { value: { id: 10 } }, tenantId: { value: 7 }, isAdvisor: { value: true },
    profile: { value: profile }, saving: { value: false }, advisorBrandProfile,
    patchGeoBusiness: async (...args) => { calls.push(args); throw new Error('品牌资料 summary 必须是文字，最多 500 个字符') },
    ElMessage: { error: (text) => errors.push(text), success: () => assert.fail('must not report success') },
    load: () => assert.fail('must not reload unsaved edits'),
  })
  vm.runInContext(handler, context)
  await context.save()
  assert.deepEqual(calls[0].slice(0, 2), [7, 10])
  assert.deepEqual({ ...calls[0][2].profile }, { product_name: '品牌' })
  assert.deepEqual(errors, ['品牌资料 summary 必须是文字，最多 500 个字符'])
  assert.equal(context.profile.value, profile)
  assert.equal(context.saving.value, false)
})
