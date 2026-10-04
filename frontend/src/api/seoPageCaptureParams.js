export function pageCaptureCreatePayload({ tenantId, siteId, relationType = 'site_page', relationId, pageId, url }) {
  return { tenant_id: tenantId, site_id: siteId, relation_type: relationType,
    relation_id: relationId ?? pageId, ...(url == null ? {} : { url }) }
}

export function pageCaptureListParams({ tenantId, siteId, relationType, relationId,
  capturedFrom, capturedTo, status, latestPerRelation, page = 1, pageSize = 1 }) {
  return { tenant_id: tenantId, site_id: siteId, relation_type: relationType, relation_id: relationId,
    captured_from: capturedFrom, captured_to: capturedTo, status, latest_per_relation: latestPerRelation,
    page, page_size: pageSize }
}
