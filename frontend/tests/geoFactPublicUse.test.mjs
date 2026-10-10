import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(
  new URL('../src/views/geo/GeoFactsView.vue', import.meta.url),
  'utf8',
)

test('fact verification requires an explicit public-use choice every time', () => {
  assert.match(source, /public_use_allowed:\s*false/)
  assert.match(source, /public_use_allowed:\s*verifyForm\.value\.public_use_allowed === true/)
  assert.match(source, /v-model="verifyForm\.public_use_allowed"/)
  assert.match(source, /默认关闭；每次重新核验都需要再次明确选择。/)
  assert.doesNotMatch(source, /public_use_allowed:\s*hasPublicUseAuthorization/)
})

test('only GEO content editors see authorization control and existing state remains visible', () => {
  assert.match(source, /session\.canEdit\('geo\.content'\)/)
  assert.match(source, /session\.user\?\.role_label !== CUSTOMER_ROLE/)
  assert.match(source, /v-if="canAuthorizePublicUse"/)
  assert.match(source, /row\?\.meta\?\.public_use\?\.allowed === true/)
  assert.match(source, /公开内容：已授权/)
})
