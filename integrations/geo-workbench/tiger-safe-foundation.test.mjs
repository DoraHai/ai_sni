import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const fixture = JSON.parse(readFileSync(new URL('./tiger-safe-foundation.synthetic.json', import.meta.url), 'utf8'))

test('Tiger foundation fixture is explicitly offline and tenant scoped', () => {
  assert.match(fixture.fixture_notice, /离线安全建档载荷/)
  assert.match(fixture.fixture_notice, /禁止/)
  assert.equal(fixture.tenant_id, 4)
  assert.equal(fixture.identity.tenant_name, 'SZ-老虎新材料')
  assert.equal(fixture.identity.canonical_website, 'https://www.tiger-coatings.cn/')
  assert.equal(fixture.preconditions.geo_entitlement_available, true)
  assert.equal(fixture.preconditions.patrol_settings_enabled, false)
  assert.deepEqual(fixture.preconditions.persistent_tracking_engine_ids, [])
  assert.deepEqual(fixture.preconditions.persistent_channel_account_ids, [])
  assert.equal(fixture.preconditions.duplicate_checks_required, true)
})

test('Tiger foundation contains only the reviewed business, three manual questions and disabled website candidate', () => {
  const { optimization_business: business, prompts, publishing_channel: channel } = fixture.creates
  assert.equal(business.tenant_id, fixture.tenant_id)
  assert.equal(business.name, '粉末涂料与表面技术')
  assert.equal(business.profile.product_name, 'TIGER/老虎')
  assert.equal(business.profile.website, fixture.identity.canonical_website)
  assert.deepEqual(Object.keys(business.profile).sort(), ['industry', 'product_name', 'summary', 'website'])

  assert.equal(prompts.length, 3)
  assert.equal(new Set(prompts.map(row => row.question.trim())).size, 3)
  for (const row of prompts) {
    assert.equal(row.tenant_id, fixture.tenant_id)
    assert.equal(row.source, 'manual')
    assert.equal(row.language, 'zh-CN')
    assert.equal(row.market, 'cn')
    assert.equal(row.is_brand_probe, false)
    assert.equal(row.unit_id, null)
  }

  assert.equal(channel.tenant_id, fixture.tenant_id)
  assert.equal(channel.channel_type, 'website')
  assert.equal(channel.base_url, fixture.identity.canonical_website)
  assert.equal(channel.publish_mode, 'manual_only')
  assert.equal(channel.enabled, false)
})

test('Tiger foundation forbids every operation that could collect, generate or publish', () => {
  const required = [
    'create_optimization_unit',
    'put_tracking_engines',
    'enable_patrol_settings',
    'create_patrol_run',
    'create_content_task',
    'create_async_generation_job',
    'create_channel_account',
    'create_channel_variant',
    'create_publication',
  ]
  assert.deepEqual(fixture.prohibited_operations, required)
  assert.deepEqual(Object.keys(fixture.creates).sort(), ['optimization_business', 'prompts', 'publishing_channel'])
})
