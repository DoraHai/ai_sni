import assert from 'node:assert/strict'
import { test } from 'node:test'
import { pageCaptureError, pageCaptureStatus, pageCaptureTarget, pageCaptureWarningCount, shouldPollPageCapture } from '../src/views/seo/seoPageCapture.js'

test('截图请求使用当前租户、站点、页面和 URL', () => {
  assert.deepEqual(pageCaptureTarget({ tenantId: 3, siteId: 5, page: { id: 8, url: 'https://example.com/a' } }), {
    tenantId: 3, siteId: 5, pageId: 8, url: 'https://example.com/a',
  })
})

test('状态和错误码使用中文，未知错误保留错误码', () => {
  assert.deepEqual(['pending', 'running', 'succeeded', 'failed'].map(pageCaptureStatus), ['排队中', '截图中', '成功', '失败'])
  assert.deepEqual(['capture_disabled', 'capture_recent', 'invalid_site_url', 'timeout', 'browser_error'].map(pageCaptureError),
    ['截图功能未开启', '刚提交过请稍后', '链接不属于该站点', '截图超时', 'browser_error'])
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
