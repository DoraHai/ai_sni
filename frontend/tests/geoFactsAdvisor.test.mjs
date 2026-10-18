import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { computed, effectScope, nextTick, ref, watch } from 'vue'

const source = readFileSync(new URL('../src/views/geo/GeoFactsView.vue', import.meta.url), 'utf8')
const script = source.match(/<script setup>([\s\S]*?)<\/script>/)[1]
  .replace(/^import[\s\S]*?from ['"][^'"]+['"]\r?\n/gm, '')

function fixture(t, { advisor = true, listBusinesses = async () => ({ items: [] }) } = {}) {
  const calls = { create: [], verify: [], warnings: [] }
  const tenantId = ref(10)
  const scope = effectScope()
  t.after(() => scope.stop())
  const deps = {
    computed, ref, watch, onMounted: () => {},
    ElMessage: { warning: (s) => calls.warnings.push(s), success: () => {}, error: assert.fail },
    createGeoFact: async (body) => calls.create.push(body),
    verifyGeoFact: async (...args) => calls.verify.push(args),
    listGeoFacts: async () => ({ items: [] }), listGeoBusinesses: listBusinesses,
    importGeoFactsCsv: () => assert.fail('unexpected import'), patchGeoFact: () => assert.fail('unexpected edit'),
    useClientPager: () => ({ resetPage() {} }), useGeoTenant: () => ({ tenantId }),
    getGeoPrototypePageSurface: () => ({}), advisorClaims: () => false, CUSTOMER_ROLE: 'customer',
    session: { user: { is_advisor: advisor }, canEdit: () => true },
  }
  const page = scope.run(() => new Function(...Object.keys(deps), script + `
    return { form, businesses, load, submitCreate, openVerify, submitVerify,
      verifyForm, verifyOpen, editOpen, canAuthorizePublicUse }
  `)(...Object.values(deps)))
  return { ...page, tenantId, calls }
}

test('a sole current-customer business is selected and submitted in the body', async (t) => {
  const page = fixture(t, { listBusinesses: async () => ({ items: [{ id: 10, name: '业务甲' }] }) })
  await page.load()
  assert.equal(page.form.value.business_id, 10)
  Object.assign(page.form.value, { title: '标题', statement: '事实陈述', source_name: '来源名' })
  await page.submitCreate()
  assert.equal(page.calls.create[0].business_id, 10)
  assert.equal(page.calls.create[0].tenant_id, 10)
  assert.equal('project_id' in page.calls.create[0], false)
  assert.equal(page.form.value.business_id, 10)
})

test('multiple businesses require a choice and stale business IDs cannot submit', async (t) => {
  const page = fixture(t, { listBusinesses: async () => ({ items: [{ id: 10 }, { id: 11 }] }) })
  await page.load()
  assert.equal(page.form.value.business_id, null)
  await page.submitCreate()
  page.form.value.business_id = 30
  await page.submitCreate()
  assert.deepEqual(page.calls.warnings, ['请先选所属业务', '请先选所属业务'])
  assert.equal(page.calls.create.length, 0)
})

test('customer switching clears selection and dialogs and ignores the previous response', async (t) => {
  let resolveOld
  const page = fixture(t, { listBusinesses: (tid) => tid === 10
    ? new Promise((resolve) => { resolveOld = resolve })
    : Promise.resolve({ items: [{ id: 20 }, { id: 21 }] }) })
  page.form.value.business_id = 10
  page.verifyOpen.value = page.editOpen.value = true
  const pending = page.load()
  page.tenantId.value = 20
  await nextTick()
  assert.equal(page.form.value.business_id, null)
  assert.equal(page.verifyOpen.value, false)
  assert.equal(page.editOpen.value, false)
  resolveOld({ items: [{ id: 10 }] })
  await pending
  assert.deepEqual(page.businesses.value.map((b) => b.id), [20, 21])
  assert.equal(page.form.value.business_id, null)
})

test('advisor sends only source verification; native editor keeps translation and consent', async (t) => {
  for (const advisor of [true, false]) {
    const page = fixture(t, { advisor })
    const row = { id: 10, statement: 'synthetic evidence statement', source_name: 'fixture source',
      source_url: 'https://source.example.test' }
    page.openVerify(row)
    page.verifyForm.value.verified_translation = '人工核验译文'
    page.verifyForm.value.public_use_allowed = true
    await page.submitVerify()
    const [tenantId, id, body] = page.calls.verify[0]
    assert.equal(tenantId, 10)
    assert.equal(id, 10)
    assert.equal(body.source_url, row.source_url)
    assert.equal(body.expected_source_name, row.source_name)
    assert.equal('verified_translation' in body, !advisor)
    assert.equal('public_use_allowed' in body, !advisor)
    assert.equal(page.canAuthorizePublicUse.value, !advisor)
  }
  assert.match(source, /<el-form-item label="所属业务" required>/)
  assert.match(source, /v-if="!isAdvisor" label="已核验译文/)
  assert.match(source, /v-if="canAuthorizePublicUse" label="公开内容授权"/)
})
