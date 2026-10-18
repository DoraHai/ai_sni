import test from 'node:test'
import assert from 'node:assert/strict'
import { prepareAdvisorSeoRequest } from '../src/api/seoAdvisorRequests.js'
const advisor = { isAdvisorSession: true, tenantId: 4 }

test('catalog and body-only writes carry the selected customer', () => {
  for (const config of [
    { url: '/api/v1/seo/content-distribution/catalog' },
    { url: '/api/v1/seo/keywords', method: 'post', data: { tenant_id: 4 } },
  ]) assert.equal(prepareAdvisorSeoRequest(config, advisor).params.tenant_id, 4)
})
test('stale body, query and URL scope are rejected', () => {
  for (const config of [
    { url: '/api/v1/seo/keywords', data: { tenant_id: 5 } },
    { url: '/api/v1/seo/keywords', params: { tenant_id: 5 } },
    { url: '/api/v1/seo/keywords?tenant_id=5' },
  ]) assert.throws(() => prepareAdvisorSeoRequest(config, advisor), /客户选择已变化/)
})
test('deleting and publishing require a confirmation and support cancel', () => {
  for (const config of [
    { url: '/api/v1/seo/keywords/1', method: 'delete' },
    { url: '/api/v1/seo/content-distribution/publish', method: 'post' },
    { url: '/api/v1/seo/content-distribution/video/upload', method: 'post', data: new FormData() },
    { url: '/api/v1/seo/site-pages/non-html-assets/cleanup', method: 'post', data: { dry_run: false } },
  ]) {
    let prompt
    assert.throws(() => prepareAdvisorSeoRequest(config, advisor, text => { prompt = text; return false }), /已取消/)
    assert.match(prompt, /确定/)
    assert.equal(prepareAdvisorSeoRequest(config, advisor, () => true), config)
  }
})
test('ordinary actors and other APIs keep their request unchanged', () => {
  const config = { url: '/api/v1/seo/keywords', method: 'post' }
  assert.equal(prepareAdvisorSeoRequest(config, { isAdvisorSession: false }), config)
  assert.equal(config.params, undefined)
})
