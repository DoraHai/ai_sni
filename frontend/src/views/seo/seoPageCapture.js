export function pageCaptureTarget({ tenantId, siteId, page, relationType = 'site_page' }) {
  if (relationType === 'publication') return { tenantId, siteId, relationType, relationId: page.id, ...(page.page_url ? { url: page.page_url } : {}) }
  return { tenantId, siteId, pageId: page.id, url: page.url }
}

export function pageCaptureStatus(status) {
  return { pending: '排队中', running: '截图中', succeeded: '成功', failed: '失败' }[status] || status
}

export function pageCaptureError(code) {
  return {
    capture_disabled: '截图功能未开启', capture_recent: '刚提交过请稍后',
    invalid_site_url: '链接不属于该站点', timeout: '截图超时',
    publication_url_missing: '该发布记录没有已登记的发布链接',
    publication_url_mismatch: '链接与发布记录不一致',
    captcha_page: '目标平台要求人机验证，未能截取正文',
    blocked_by_platform: '目标平台拒绝了自动访问（可能需要登录）',
    invalid_image: '图片文件无法识别', unsupported_image_type: '仅支持 PNG、JPG、WebP 图片',
    image_too_large: '图片过大',
  }[code] || code || '截图失败'
}

export function suggestManualPageCapture(code) {
  return ['blocked_by_platform', 'captcha_page'].includes(code)
}

export function pageCaptureUploadCheck(file, maxBytes = 10_000_000) {
  if (!file || !/\.(png|jpe?g|webp)$/i.test(file.name) ||
      (file.type && !['image/png', 'image/jpeg', 'image/webp'].includes(file.type))) return 'unsupported_image_type'
  if (file.size > maxBytes) return 'image_too_large'
  return ''
}

export function pageCaptureWarningCount(warnings) {
  return Number(warnings?.blocked_subresources || 0) + Number(warnings?.failed_subresources || 0)
}

export function shouldPollPageCapture(status, attempts, elapsedMs) {
  return ['pending', 'running'].includes(status) && attempts < 90 && elapsedMs < 180000
}
