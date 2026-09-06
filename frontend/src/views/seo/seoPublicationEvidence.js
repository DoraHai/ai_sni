// These labels describe recorded evidence, not independent page verification.
export function publicationEvidence(row) {
  if (row.status !== 'published') return '尚无发布成功记录'
  if (['manual', 'assisted', 'share'].includes(row.publish_mode)) return '人工确认 / 链接登记'
  if (['publish', 'draft'].includes(row.publish_mode)) return '接口任务，确认依据见尝试记录'
  return '历史发布记录，依据待确认'
}

export function channelBoundary(platform) {
  if (!platform.available) return '当前尚未开放'
  if (platform.mode === 'assisted') return '半自动填稿；登录、配图、排版及最终发布由真人完成。已登记账号不代表实测通过。'
  if (platform.mode === 'api') return '接口能力已实现；需对应应用权限与账号授权，连接成功不代表发布或审核通过。'
  return '按平台要求完成授权与人工确认；实际能力以账号验收结果为准。'
}

export function countPublishedListedContents(contents, publications) {
  const ids = new Set(contents.map(row => row.id))
  return new Set(publications.filter(row => row.status === 'published' && ids.has(row.content_id)).map(row => row.content_id)).size
}
