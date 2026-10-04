export function pageCaptureTarget({ tenantId, siteId, page }) {
  return { tenantId, siteId, pageId: page.id, url: page.url }
}

export function pageCaptureStatus(status) {
  return { pending: '排队中', running: '截图中', succeeded: '成功', failed: '失败' }[status] || status
}

export function pageCaptureError(code) {
  return {
    capture_disabled: '截图功能未开启', capture_recent: '刚提交过请稍后',
    invalid_site_url: '链接不属于该站点', timeout: '截图超时',
  }[code] || code || '截图失败'
}

export function pageCaptureWarningCount(warnings) {
  return Number(warnings?.blocked_subresources || 0) + Number(warnings?.failed_subresources || 0)
}

export function shouldPollPageCapture(status, attempts, elapsedMs) {
  return ['pending', 'running'].includes(status) && attempts < 90 && elapsedMs < 180000
}
