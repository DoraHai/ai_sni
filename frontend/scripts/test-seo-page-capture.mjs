import assert from 'node:assert/strict'
import { test } from 'node:test'
import { pageCaptureError, pageCaptureStatus, pageCaptureTarget, pageCaptureWarningCount, shouldPollPageCapture } from '../src/views/seo/seoPageCapture.js'
import { pageCaptureCreatePayload, pageCaptureListParams } from '../src/api/seoPageCaptureParams.js'

test('截图请求使用当前租户、站点、页面和 URL', () => {
  assert.deepEqual(pageCaptureTarget({ tenantId: 3, siteId: 5, page: { id: 8, url: 'https://example.com/a' } }), {
    tenantId: 3, siteId: 5, pageId: 8, url: 'https://example.com/a',
  })
  assert.deepEqual(pageCaptureCreatePayload(pageCaptureTarget({ tenantId: 3, siteId: 5, page: { id: 8, url: 'https://example.com/a' } })), {
    tenant_id: 3, site_id: 5, relation_type: 'site_page', relation_id: 8, url: 'https://example.com/a',
  })
  assert.deepEqual(pageCaptureCreatePayload(pageCaptureTarget({ tenantId: 3, siteId: 5,
    relationType: 'publication', page: { id: 12, page_url: null } })), {
    tenant_id: 3, site_id: 5, relation_type: 'publication', relation_id: 12,
  })
  assert.deepEqual(pageCaptureCreatePayload(pageCaptureTarget({ tenantId: 3, siteId: 5,
    relationType: 'publication', page: { id: 12, page_url: 'https://zhihu.example/a' } })), {
    tenant_id: 3, site_id: 5, relation_type: 'publication', relation_id: 12, url: 'https://zhihu.example/a',
  })
})

test('列表参数保留时间、状态、每关联最新和分页', () => {
  assert.deepEqual(pageCaptureListParams({ tenantId: 3, siteId: 5, relationType: 'publication',
    capturedFrom: '2026-10-01', capturedTo: '2026-10-31', status: 'succeeded', latestPerRelation: true,
    page: 2, pageSize: 20 }), {
    tenant_id: 3, site_id: 5, relation_type: 'publication', relation_id: undefined,
    captured_from: '2026-10-01', captured_to: '2026-10-31', status: 'succeeded',
    latest_per_relation: true, page: 2, page_size: 20,
  })
})

test('状态和错误码使用中文，未知错误保留错误码', () => {
  assert.deepEqual(['pending', 'running', 'succeeded', 'failed'].map(pageCaptureStatus), ['排队中', '截图中', '成功', '失败'])
  assert.deepEqual(['capture_disabled', 'capture_recent', 'invalid_site_url', 'timeout', 'browser_error'].map(pageCaptureError),
    ['截图功能未开启', '刚提交过请稍后', '链接不属于该站点', '截图超时', 'browser_error'])
  assert.deepEqual(['publication_url_missing', 'publication_url_mismatch'].map(pageCaptureError),
    ['该发布记录没有已登记的发布链接', '链接与发布记录不一致'])
})

test('只轮询未完成任务，次数和时长都有上限', () => {
  assert.equal(shouldPollPageCapture('pending', 0, 0), true)
  assert.equal(shouldPollPageCapture('running', 89, 179999), true)
  assert.equal(shouldPollPageCapture('running', 90, 0), false)
  assert.equal(shouldPollPageCapture('pending', 0, 180000), false)
  assert.equal(shouldPollPageCapture('succeeded', 0, 0), false)
  assert.equal(shouldPollPageCapture('failed', 0, 0), false)
})

test('部分资源计数包含被拦截和加载失败的资源', () => {
  assert.equal(pageCaptureWarningCount({ blocked_subresources: 2, failed_subresources: 3 }), 5)
  assert.equal(pageCaptureWarningCount({}), 0)
})
