export function pageCaptureCreatePayload({ tenantId, siteId, relationType = 'site_page', relationId, pageId, url }) {
  return { tenant_id: tenantId, site_id: siteId, relation_type: relationType,
    relation_id: relationId ?? pageId, ...(url == null ? {} : { url }) }
}

export function pageCaptureListParams({ tenantId, siteId, relationType, relationId,
  capturedFrom, capturedTo, status, source, latestPerRelation, page = 1, pageSize = 1 }) {
  return { tenant_id: tenantId, site_id: siteId, relation_type: relationType, relation_id: relationId,
    captured_from: capturedFrom, captured_to: capturedTo, status, source, latest_per_relation: latestPerRelation,
    page, page_size: pageSize }
}

export function pageCaptureUploadPayload({ tenantId, siteId, relationId, file }) {
  const form = new FormData()
  form.append('tenant_id', String(tenantId))
  form.append('site_id', String(siteId))
  form.append('relation_type', 'publication')
  form.append('relation_id', String(relationId))
  form.append('file', file)
  return form
}
