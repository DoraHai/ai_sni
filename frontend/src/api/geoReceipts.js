import client from './client'

export function importGeoReceipts({ tenantId, projectId, taskId, file, dryRun = true }) {
  const form = new FormData()
  form.append('file', file)
  return client.post(`/api/v1/geo/content-tasks/${taskId}/import-receipts`, form, {
    params: { tenant_id: tenantId, project_id: projectId, dry_run: dryRun },
  })
}
